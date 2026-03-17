import json
import os
import shutil
import threading
import time
import hmac
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request
from observability import init_observability
from task_queue import (
    RABBITMQ_SANDBOX_QUEUE,
    RABBITMQ_X64DBG_QUEUE,
    consume_json,
    publish_json,
    rabbitmq_enabled,
)


app = Flask(__name__)

SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", "/shared"))
QUEUE_DIR = Path(os.getenv("QUEUE_DIR", "/queue"))
WEBUI_BASE = os.getenv("WEBUI_BASE", "http://webui:5000")
X64DBG_DIR = Path(os.getenv("X64DBG_DIR", "/queue/x64dbg"))
BRIDGE_DIR = Path(os.getenv("BRIDGE_DIR", "/bridge"))
BRIDGE_POLL_INTERVAL = float(os.getenv("BRIDGE_POLL_INTERVAL", "2.5"))
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN")
RUNNER_ENABLE_BRIDGE = os.getenv("RUNNER_ENABLE_BRIDGE", "0").lower() in {"1", "true", "yes", "on"}
_bridge_thread_started = False
_bridge_thread_lock = threading.Lock()


def _runner_readiness():
    checks = {
        "samples_dir_ready": SAMPLES_DIR.exists() or SAMPLES_DIR.parent.exists(),
        "queue_dir_ready": QUEUE_DIR.exists() or QUEUE_DIR.parent.exists(),
        "bridge_dir_ready": BRIDGE_DIR.exists() or BRIDGE_DIR.parent.exists(),
        "rabbitmq_enabled": rabbitmq_enabled(),
    }
    return {
        "ready": checks["samples_dir_ready"] and checks["queue_dir_ready"] and checks["bridge_dir_ready"],
        "checks": checks,
    }


init_observability(app, "sandbox_runner", _runner_readiness)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _require_internal_token():
    if not INTERNAL_API_TOKEN:
        return None

    provided = request.headers.get("X-Internal-Token", "")
    if not hmac.compare_digest(provided, INTERNAL_API_TOKEN):
        return jsonify({"error": "unauthorized"}), 401
    return None


def _job_path(job_id: str) -> Path:
    return QUEUE_DIR / f"{job_id}.json"


def _sample_path(job_id: str) -> Path:
    return SAMPLES_DIR / f"{job_id}.bin"


def _load_job(job_id: str):
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_job(job_id: str, payload):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    _job_path(job_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_run_payload(job_id: str, filename: str):
    sample_path = _sample_path(job_id)
    return {
        "job_id": job_id,
        "filename": filename,
        "sample_path": str(sample_path),
        "sample_present": sample_path.exists(),
        "status": "queued",
        "queued_at": _utc_now(),
        "notes": [
            "Runner queued safely. External sandbox execution must be operated separately."
        ],
    }


def process_run_request(job_id: str, filename: str):
    payload = _build_run_payload(job_id, filename)
    _save_job(job_id, payload)
    return payload


def process_run_message(payload: dict):
    job_id = payload.get("job_id")
    filename = payload.get("filename")
    if not job_id or not filename:
        return
    process_run_request(job_id, filename)


def process_x64dbg_request(job_id: str, request_payload: dict):
    payload = _append_x64dbg_request(job_id, request_payload)
    _save_x64dbg_state(job_id, {
        "status": "waiting_for_debugger",
        "last_request_at": request_payload["requested_at"],
        "last_requested_action": request_payload["action"],
    })
    _write_bridge_requests_snapshot(job_id)
    _write_bridge_state_snapshot(job_id)
    return payload


def process_x64dbg_message(payload: dict):
    job_id = payload.get("job_id")
    request_payload = payload.get("request")
    if not job_id or not isinstance(request_payload, dict):
        return
    process_x64dbg_request(job_id, request_payload)


def start_sandbox_queue_worker():
    threading.Thread(
        target=consume_json,
        args=(RABBITMQ_X64DBG_QUEUE, process_x64dbg_message),
        daemon=True,
        name="sandbox-x64dbg-queue-consumer",
    ).start()
    consume_json(RABBITMQ_SANDBOX_QUEUE, process_run_message)


def _delete_job_artifacts(job_id: str):
    removed = {
        "job_queue": False,
        "x64dbg": False,
        "bridge": False,
    }

    job_path = _job_path(job_id)
    if job_path.exists():
        try:
            job_path.unlink()
            removed["job_queue"] = True
        except OSError:
            pass

    x64dbg_dir = _x64dbg_job_dir(job_id)
    if x64dbg_dir.exists():
        try:
            shutil.rmtree(x64dbg_dir)
            removed["x64dbg"] = True
        except OSError:
            pass

    bridge_dir = _bridge_job_dir(job_id)
    if bridge_dir.exists():
        try:
            shutil.rmtree(bridge_dir)
            removed["bridge"] = True
        except OSError:
            pass

    return removed


def _x64dbg_job_dir(job_id: str) -> Path:
    return X64DBG_DIR / job_id


def _x64dbg_state_path(job_id: str) -> Path:
    return _x64dbg_job_dir(job_id) / "state.json"


def _x64dbg_findings_path(job_id: str) -> Path:
    return _x64dbg_job_dir(job_id) / "findings.json"


def _x64dbg_requests_path(job_id: str) -> Path:
    return _x64dbg_job_dir(job_id) / "requests.json"


def _bridge_job_dir(job_id: str) -> Path:
    return BRIDGE_DIR / job_id


def _bridge_incoming_dir(job_id: str, kind: str) -> Path:
    return _bridge_job_dir(job_id) / "incoming" / kind


def _bridge_processed_dir(job_id: str, kind: str) -> Path:
    return _bridge_job_dir(job_id) / "processed" / kind


def _bridge_requests_snapshot_path(job_id: str) -> Path:
    return _bridge_job_dir(job_id) / "requests.pending.json"


def _bridge_state_snapshot_path(job_id: str) -> Path:
    return _bridge_job_dir(job_id) / "state.current.json"


def _load_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        # PowerShell 5.x writes UTF-8 with BOM by default, so accept utf-8-sig
        # for bridge payloads produced inside the Windows guest.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json_file(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _get_x64dbg_state(job_id: str):
    default = {
        "job_id": job_id,
        "status": "idle",
        "updated_at": None,
        "transport": "mcp",
        "notes": [],
        "sample_path": str(_sample_path(job_id)),
        "sample_present": _sample_path(job_id).exists(),
    }
    state = _load_json_file(_x64dbg_state_path(job_id), default)
    state.setdefault("job_id", job_id)
    state.setdefault("status", "idle")
    state.setdefault("transport", "mcp")
    state.setdefault("notes", [])
    state["sample_path"] = str(_sample_path(job_id))
    state["sample_present"] = _sample_path(job_id).exists()
    return state


def _save_x64dbg_state(job_id: str, payload):
    existing = _get_x64dbg_state(job_id)
    existing.update(payload)
    existing["job_id"] = job_id
    existing["updated_at"] = _utc_now()
    existing["sample_path"] = str(_sample_path(job_id))
    existing["sample_present"] = _sample_path(job_id).exists()
    _save_json_file(_x64dbg_state_path(job_id), existing)
    return existing


def _get_x64dbg_findings(job_id: str):
    payload = _load_json_file(_x64dbg_findings_path(job_id), {"job_id": job_id, "findings": []})
    payload.setdefault("job_id", job_id)
    payload.setdefault("findings", [])
    payload["findings"] = [
        finding for finding in payload["findings"]
        if isinstance(finding, dict) and any(value not in (None, "", [], {}) for value in finding.values())
    ]
    return payload


def _append_x64dbg_findings(job_id: str, findings):
    payload = _get_x64dbg_findings(job_id)
    payload["findings"].extend(findings)
    payload["updated_at"] = _utc_now()
    _save_json_file(_x64dbg_findings_path(job_id), payload)
    _write_bridge_state_snapshot(job_id)
    return payload


def _get_x64dbg_requests(job_id: str):
    payload = _load_json_file(_x64dbg_requests_path(job_id), {"job_id": job_id, "requests": []})
    payload.setdefault("job_id", job_id)
    payload.setdefault("requests", [])
    return payload


def _append_x64dbg_request(job_id: str, request_payload):
    payload = _get_x64dbg_requests(job_id)
    payload["requests"].append(request_payload)
    payload["updated_at"] = _utc_now()
    _save_json_file(_x64dbg_requests_path(job_id), payload)
    _write_bridge_requests_snapshot(job_id)
    return payload


def _write_bridge_requests_snapshot(job_id: str):
    payload = _get_x64dbg_requests(job_id)
    path = _bridge_requests_snapshot_path(job_id)
    _save_json_file(path, payload)


def _write_bridge_state_snapshot(job_id: str):
    payload = {
        "state": _get_x64dbg_state(job_id),
        "findings": _get_x64dbg_findings(job_id),
        "requests": _get_x64dbg_requests(job_id),
    }
    _save_json_file(_bridge_state_snapshot_path(job_id), payload)


def _consume_bridge_state_file(job_id: str, path: Path):
    payload = _load_json_file(path, {})
    if not isinstance(payload, dict) or not payload:
        return
    _save_x64dbg_state(job_id, payload)
    _write_bridge_state_snapshot(job_id)


def _consume_bridge_findings_file(job_id: str, path: Path):
    payload = _load_json_file(path, {})
    if not isinstance(payload, dict) or not payload:
        return
    findings = payload.get("findings") if isinstance(payload, dict) else None
    if findings is None and isinstance(payload, dict) and any(payload.values()):
        findings = [payload]
    if not isinstance(findings, list) or not findings:
        return
    _append_x64dbg_findings(job_id, findings)
    _save_x64dbg_state(job_id, {"status": "ready", "last_findings_at": _utc_now()})
    _write_bridge_requests_snapshot(job_id)


def _mark_bridge_file_processed(job_id: str, kind: str, path: Path):
    destination_dir = _bridge_processed_dir(job_id, kind)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    try:
        path.replace(destination)
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass


def _process_bridge_job(job_id: str):
    for path in sorted(_bridge_incoming_dir(job_id, "state").glob("*.json")):
        _consume_bridge_state_file(job_id, path)
        _mark_bridge_file_processed(job_id, "state", path)

    for path in sorted(_bridge_incoming_dir(job_id, "findings").glob("*.json")):
        _consume_bridge_findings_file(job_id, path)
        _mark_bridge_file_processed(job_id, "findings", path)

    _write_bridge_requests_snapshot(job_id)
    _write_bridge_state_snapshot(job_id)


def _bridge_worker():
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            for job_dir in BRIDGE_DIR.iterdir():
                if job_dir.is_dir():
                    _process_bridge_job(job_dir.name)
        except Exception:
            pass
        time.sleep(BRIDGE_POLL_INTERVAL)


def _start_bridge_worker_once():
    global _bridge_thread_started
    with _bridge_thread_lock:
        if _bridge_thread_started:
            return
        threading.Thread(target=_bridge_worker, daemon=True, name="sandbox-bridge-worker").start()
        _bridge_thread_started = True


def _forward_evidence(job_id: str, artifacts):
    headers = {}
    if INTERNAL_API_TOKEN:
        headers["X-Internal-Token"] = INTERNAL_API_TOKEN
    response = requests.post(
        f"{WEBUI_BASE.rstrip('/')}/evidence/{job_id}",
        json={"artifacts": artifacts},
        timeout=30,
        headers=headers,
    )
    response.raise_for_status()
    return response.json()


@app.post("/run")
def queue_run():
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    filename = data.get("filename")

    if not job_id or not filename:
        return jsonify({"error": "job_id and filename are required"}), 400

    payload = _build_run_payload(job_id, filename)
    if rabbitmq_enabled():
        publish_json(RABBITMQ_SANDBOX_QUEUE, {"job_id": job_id, "filename": filename})
    else:
        process_run_request(job_id, filename)
    return jsonify(payload), 202


@app.get("/jobs/<job_id>")
def get_job(job_id: str):
    payload = _load_job(job_id)
    if payload is None:
        return jsonify({"error": "job not found"}), 404
    payload["sample_present"] = _sample_path(job_id).exists()
    return jsonify(payload)


@app.delete("/jobs/<job_id>")
def delete_job(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    removed = _delete_job_artifacts(job_id)
    return jsonify({
        "job_id": job_id,
        "status": "deleted",
        "removed": removed,
    })


@app.post("/jobs/<job_id>/evidence")
def ingest_job_evidence(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    data = request.get_json(silent=True) or {}
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        return jsonify({"error": "artifacts array is required"}), 400

    try:
        forwarded = _forward_evidence(job_id, artifacts)
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": f"Failed to forward evidence to webui: {exc}"}), 502

    payload = _load_job(job_id) or {
        "job_id": job_id,
        "filename": f"{job_id}.bin",
        "sample_path": str(_sample_path(job_id)),
        "status": "queued",
        "queued_at": _utc_now(),
        "notes": [],
    }
    payload["status"] = "evidence-recorded"
    payload["last_evidence_at"] = _utc_now()
    _save_job(job_id, payload)

    return jsonify({
        "job_id": job_id,
        "status": "forwarded",
        "webui": forwarded,
    })


@app.get("/jobs/<job_id>/x64dbg")
def get_x64dbg_state(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    _write_bridge_state_snapshot(job_id)
    return jsonify(_get_x64dbg_state(job_id))


@app.post("/jobs/<job_id>/x64dbg")
def update_x64dbg_state(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    data = request.get_json(silent=True) or {}
    state = _save_x64dbg_state(job_id, data)
    _write_bridge_state_snapshot(job_id)
    payload = _load_job(job_id) or {
        "job_id": job_id,
        "filename": f"{job_id}.bin",
        "sample_path": str(_sample_path(job_id)),
        "queued_at": _utc_now(),
        "notes": [],
    }
    payload["status"] = "x64dbg-active"
    payload["last_x64dbg_at"] = state["updated_at"]
    _save_job(job_id, payload)
    return jsonify(state)


@app.get("/jobs/<job_id>/x64dbg/findings")
def get_x64dbg_findings(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    _write_bridge_state_snapshot(job_id)
    return jsonify(_get_x64dbg_findings(job_id))


@app.post("/jobs/<job_id>/x64dbg/findings")
def add_x64dbg_findings(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    data = request.get_json(silent=True) or {}
    findings = data.get("findings")
    if not isinstance(findings, list):
        return jsonify({"error": "findings array is required"}), 400
    payload = _append_x64dbg_findings(job_id, findings)
    _save_x64dbg_state(job_id, {"status": "ready", "last_findings_at": payload.get("updated_at")})
    _write_bridge_requests_snapshot(job_id)
    return jsonify(payload)


@app.get("/jobs/<job_id>/x64dbg/requests")
def get_x64dbg_requests(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    _write_bridge_requests_snapshot(job_id)
    return jsonify(_get_x64dbg_requests(job_id))


@app.post("/jobs/<job_id>/x64dbg/requests")
def add_x64dbg_request(job_id: str):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if not action:
        return jsonify({"error": "action is required"}), 400

    request_payload = {
        "action": action,
        "notes": data.get("notes", ""),
        "address": data.get("address"),
        "requested_at": _utc_now(),
        "status": "queued",
    }
    if rabbitmq_enabled():
        publish_json(
            RABBITMQ_X64DBG_QUEUE,
            {"job_id": job_id, "request": request_payload},
        )
        queued_requests = _get_x64dbg_requests(job_id)["requests"]
    else:
        payload = process_x64dbg_request(job_id, request_payload)
        queued_requests = payload["requests"]
    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "request": request_payload,
        "requests": queued_requests,
    }), 202


if RUNNER_ENABLE_BRIDGE:
    _start_bridge_worker_once()


if __name__ == "__main__":
    _start_bridge_worker_once()
    app.run(host="0.0.0.0", port=9001, debug=False)
