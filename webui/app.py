# Biniam Demissie
# 09/29/2025
import hashlib
import json
import os
from pathlib import Path
import requests
from flask import Flask, render_template, request, jsonify, Response
from ghidra_assistant import GhidraAssistant 
from triage_report import get_cached_triage_report, queue_triage_report

app = Flask(__name__)
assistant = GhidraAssistant()
GHIDRAAAS_BASE = os.getenv("GHIDRAAAS_BASE", "http://localhost:8080/ghidra/api")
JOB_METADATA_PATH = Path(os.getenv("JOB_METADATA_PATH", "/app/data/job_metadata.json"))
DYNAMIC_EVIDENCE_DIR = Path(os.getenv("DYNAMIC_EVIDENCE_DIR", "/app/data/dynamic_evidence"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/app/data/uploads"))
SANDBOX_RUNNER_URL = os.getenv("SANDBOX_RUNNER_URL")
TRIAGE_REPORT_DIR = Path(os.getenv("TRIAGE_REPORT_DIR", "/app/data/triage_reports"))


def _response_error_details(response: requests.Response) -> str:
    body = response.text.strip()
    if response.status_code == 413:
        return body or "HTTP 413: Uploaded file is larger than the configured backend limit"
    if not body:
        return f"HTTP {response.status_code}"
    return f"HTTP {response.status_code}: {body[:500]}"


def _parse_json_response(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        return None


def _load_job_metadata():
    if not JOB_METADATA_PATH.exists():
        return {}
    try:
        raw = json.loads(JOB_METADATA_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}

        normalized = {}
        dirty = False
        for job_id, value in raw.items():
            if isinstance(value, str):
                normalized[job_id] = {"filename": value}
                dirty = True
            elif isinstance(value, dict):
                normalized[job_id] = value
            else:
                dirty = True

        if dirty:
            _save_job_metadata(normalized)
        return normalized
    except (OSError, json.JSONDecodeError):
        return {}


def _save_job_metadata(metadata):
    JOB_METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _record_job_filename(job_id, filename):
    metadata = _load_job_metadata()
    entry = metadata.get(job_id, {})
    if not isinstance(entry, dict):
        entry = {"filename": str(entry)}
    entry["filename"] = filename
    metadata[job_id] = entry
    _save_job_metadata(metadata)


def _update_job_metadata(job_id, **updates):
    metadata = _load_job_metadata()
    entry = metadata.get(job_id, {})
    if not isinstance(entry, dict):
        entry = {"filename": str(entry)}

    allowed = {"filename", "label", "archived"}
    for key, value in updates.items():
        if key not in allowed:
            continue
        if value is None or value == "":
            entry.pop(key, None)
        else:
            entry[key] = value

    if entry:
        metadata[job_id] = entry
    elif job_id in metadata:
        del metadata[job_id]
    _save_job_metadata(metadata)
    return entry


def _delete_job_filename(job_id):
    metadata = _load_job_metadata()
    if job_id in metadata:
        del metadata[job_id]
        _save_job_metadata(metadata)


def _job_display_name(job):
    return job.get("label") or job.get("filename") or f"{job.get('job_id', '')[:8]}.bin"


def _save_uploaded_sample(job_id: str, file_storage) -> Path:
    """
    Persist the raw uploaded sample on disk so that external sandboxes
    (for example a Windows VM) can execute it for dynamic analysis.
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    sample_path = UPLOADS_DIR / f"{job_id}.bin"

    file_storage.stream.seek(0)
    with sample_path.open("wb") as f_out:
        for chunk in iter(lambda: file_storage.stream.read(4096), b""):
            if not chunk:
                break
            f_out.write(chunk)

    return sample_path


def _trigger_sandbox_run(job_id: str, filename: str):
    """
    Notify an external sandbox runner that a new sample is ready.
    The sandbox runner is responsible for executing the binary safely
    and posting dynamic evidence to /evidence/<job_id>.
    """
    if not SANDBOX_RUNNER_URL:
        return

    payload = {
        "job_id": job_id,
        "filename": filename,
    }

    try:
        requests.post(
            SANDBOX_RUNNER_URL.rstrip("/") + "/run",
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException:
        # Dynamic analysis is best-effort and should not break static analysis.
        return


def _evidence_path(job_id):
    return DYNAMIC_EVIDENCE_DIR / f"{job_id}.json"


def _load_dynamic_evidence(job_id):
    path = _evidence_path(job_id)
    if not path.exists():
        return {"job_id": job_id, "artifacts": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("job_id", job_id)
        payload.setdefault("artifacts", [])
        return payload
    except (OSError, json.JSONDecodeError):
        return {"job_id": job_id, "artifacts": []}


def _save_dynamic_evidence(job_id, payload):
    DYNAMIC_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    _evidence_path(job_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _summarize_evidence(payload):
    artifacts = payload.get("artifacts", [])
    artifact_types = {}
    suspicious_hits = []
    for artifact in artifacts:
        artifact_type = artifact.get("type", "unknown")
        artifact_types[artifact_type] = artifact_types.get(artifact_type, 0) + 1
        for hit in artifact.get("highlights", []):
            suspicious_hits.append(hit)

    return {
        "artifact_count": len(artifacts),
        "artifact_types": artifact_types,
        "highlight_count": len(suspicious_hits),
        "highlights": suspicious_hits[:30],
    }


def _fetch_projects(timeout=30):
    response = requests.get(f"{GHIDRAAAS_BASE}/list_projects/", timeout=timeout)
    if not response.ok:
        raise requests.HTTPError(_response_error_details(response), response=response)
    payload = _parse_json_response(response) or {}
    return payload.get("projects", [])


def _sandbox_runner_request(method: str, path: str, **kwargs):
    if not SANDBOX_RUNNER_URL:
        raise RuntimeError("SANDBOX_RUNNER_URL is not configured.")

    response = requests.request(
        method=method,
        url=SANDBOX_RUNNER_URL.rstrip("/") + path,
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    if not response.ok:
        raise requests.HTTPError(_response_error_details(response), response=response)
    return _parse_json_response(response) or {}


def _safe_x64dbg_snapshot(job_id):
    if not SANDBOX_RUNNER_URL:
        return {
            "state": {"status": "unavailable"},
            "findings": {"findings": []},
            "requests": {"requests": []},
        }

    snapshot = {
        "state": {"status": "idle"},
        "findings": {"findings": []},
        "requests": {"requests": []},
    }
    try:
        snapshot["state"] = _sandbox_runner_request("GET", f"/jobs/{job_id}/x64dbg", timeout=10)
    except Exception:
        pass
    try:
        snapshot["findings"] = _sandbox_runner_request("GET", f"/jobs/{job_id}/x64dbg/findings", timeout=10)
    except Exception:
        pass
    try:
        snapshot["requests"] = _sandbox_runner_request("GET", f"/jobs/{job_id}/x64dbg/requests", timeout=10)
    except Exception:
        pass
    return snapshot


def _delete_local_job_artifacts(job_id):
    removed = {}
    paths = {
        "dynamic_evidence": _evidence_path(job_id),
        "uploaded_sample": UPLOADS_DIR / f"{job_id}.bin",
        "triage_json": TRIAGE_REPORT_DIR / f"{job_id}.json",
        "triage_markdown": TRIAGE_REPORT_DIR / f"{job_id}.md",
    }

    for label, path in paths.items():
        try:
            if path.exists():
                path.unlink()
                removed[label] = True
            else:
                removed[label] = False
        except OSError:
            removed[label] = False

    _delete_job_filename(job_id)
    removed["job_metadata"] = True
    return removed


def _reset_local_job_runtime_artifacts(job_id):
    removed = {}
    for label, path in {
        "dynamic_evidence": _evidence_path(job_id),
        "triage_json": TRIAGE_REPORT_DIR / f"{job_id}.json",
        "triage_markdown": TRIAGE_REPORT_DIR / f"{job_id}.md",
    }.items():
        try:
            if path.exists():
                path.unlink()
                removed[label] = True
            else:
                removed[label] = False
        except OSError:
            removed[label] = False
    return removed


def _assistant_next_steps(job_id):
    metadata_entry = _load_job_metadata().get(job_id, {})
    if not isinstance(metadata_entry, dict):
        metadata_entry = {"filename": str(metadata_entry)}
    filename = metadata_entry.get("label") or metadata_entry.get("filename") or f"{job_id[:8]}.bin"
    triage = get_cached_triage_report(job_id)
    evidence = _load_dynamic_evidence(job_id)
    evidence_summary = _summarize_evidence(evidence)
    x64dbg = _safe_x64dbg_snapshot(job_id)
    x64dbg_state = x64dbg.get("state", {})
    x64dbg_findings = x64dbg.get("findings", {}).get("findings", [])
    x64dbg_requests = x64dbg.get("requests", {}).get("requests", [])

    summary = {
        "triage_status": (triage or {}).get("status", "missing"),
        "dynamic_artifacts": evidence_summary.get("artifact_count", 0),
        "x64dbg_status": x64dbg_state.get("status", "idle"),
        "x64dbg_findings": len(x64dbg_findings),
        "x64dbg_requests": len(x64dbg_requests),
    }

    capabilities = []
    if triage and triage.get("status") == "completed":
        capabilities = triage.get("summary", {}).get("capabilities", [])

    suggestions = []
    stage = "analysis"
    stage_headline = "Static analysis is the current focus."
    stage_copy = "Use the report, imports, strings, and function list to build the first explanation of the target."
    alerts = []

    if not triage or triage.get("status") in {"processing", "queued"}:
        stage = "triage_building"
        stage_headline = "The assistant is still assembling the first-pass triage."
        stage_copy = "Stay in triage while Ghidra finishes preparing artifacts, then pivot into the most valuable functions."
        suggestions.append({
            "kind": "open_view",
            "label": "Open Triage",
            "description": "Watch the cached triage report while Ghidra finishes preparing artifacts.",
            "payload": {"view": "triage"},
        })
        suggestions.append({
            "kind": "chat_prompt",
            "label": "Ask For Static Triage",
            "description": "Use the assistant to summarize current static capabilities while the full report warms up.",
            "payload": {"prompt": "Summarize the binary's main capabilities and likely purpose."},
        })
    else:
        stage = "triage_ready"
        stage_headline = "Triage is ready and the target is ripe for guided inspection."
        stage_copy = "Start by explaining the most interesting functions and deciding whether you need runtime confirmation."
        suggestions.append({
            "kind": "chat_prompt",
            "label": "Explain Priority Functions",
            "description": "Ask the assistant to focus on the most valuable static functions before diving deeper.",
            "payload": {"prompt": "Use the triage report to explain which priority functions should be investigated first and why."},
        })

    if summary["dynamic_artifacts"] == 0:
        alerts.append({
            "level": "warning",
            "title": "No dynamic evidence attached yet",
            "description": "The assistant can go deeper once the sandbox starts feeding behavior or telemetry back into this job.",
        })
        suggestions.append({
            "kind": "chat_prompt",
            "label": "Plan Dynamic Collection",
            "description": "Ask for a collection plan that matches the current static evidence.",
            "payload": {"prompt": "Based on the current imports, strings, and triage report, what dynamic evidence should I collect next?"}
        })
    else:
        alerts.append({
            "level": "info",
            "title": "Fresh dynamic evidence available",
            "description": f"{summary['dynamic_artifacts']} dynamic artifact(s) are attached and ready for correlation.",
        })

    if "process_execution" in capabilities or "filesystem" in capabilities or summary["x64dbg_status"] != "idle":
        stage = "debug_ready"
        stage_headline = "The target is ready for live debugger-guided validation."
        stage_copy = "Use x64dbg to confirm the most important execution path and feed those findings back into the assistant."
        if not x64dbg_findings:
            suggestions.append({
                "kind": "debug_request",
                "label": "Trace APIs",
                "description": "Queue an API tracing request through the x64dbg bridge.",
                "payload": {
                    "action": "trace_api",
                    "notes": "Trace high-signal WinAPI calls around process creation, file writes, and registry changes."
                },
            })
            suggestions.append({
                "kind": "debug_request",
                "label": "Entry Breakpoint",
                "description": "Pause near the PE entry point and capture initial debugger context.",
                "payload": {
                    "action": "set_breakpoint",
                    "address": "0x401000",
                    "notes": "Pause at the PE entry point and capture register state."
                },
            })
        else:
            stage = "debug_active"
            stage_headline = "Debugger findings are flowing back into the platform."
            stage_copy = "Correlate those findings with the triage report so the assistant can explain the real execution path."
            alerts.append({
                "level": "success",
                "title": "Debugger findings imported",
                "description": f"{len(x64dbg_findings)} finding(s) have already been captured for this job.",
            })
            suggestions.append({
                "kind": "open_view",
                "label": "Open x64dbg View",
                "description": "Inspect the live debugger state, findings, and queued actions.",
                "payload": {"view": "x64dbg"},
            })
            suggestions.append({
                "kind": "chat_prompt",
                "label": "Interpret Debugger Findings",
                "description": "Ask the assistant to connect x64dbg findings back to the static triage.",
                "payload": {"prompt": "Correlate the current x64dbg findings with the static triage report and explain the likely execution path."},
            })

    checklist = [
        {
            "id": "triage",
            "label": "Review cached triage",
            "description": "Confirm capabilities, imports, strings, and priority functions before you pivot deeper.",
            "status": "completed" if summary["triage_status"] == "completed" else "active" if stage == "triage_building" else "pending",
        },
        {
            "id": "dynamic",
            "label": "Attach or inspect dynamic evidence",
            "description": "Bring in sandbox artifacts or telemetry so the assistant can validate static inferences.",
            "status": "completed" if summary["dynamic_artifacts"] > 0 else "active" if summary["triage_status"] == "completed" else "pending",
        },
        {
            "id": "debug",
            "label": "Drive a debugger session",
            "description": "Use x64dbg requests and findings to validate runtime behavior.",
            "status": "completed" if summary["x64dbg_findings"] > 0 else "active" if summary["x64dbg_status"] != "idle" else "pending",
        },
    ]

    primary_action = suggestions[0] if suggestions else None
    digest_payload = {
        "stage": stage,
        "summary": summary,
        "suggestions": suggestions[:5],
        "alerts": alerts,
    }
    state_digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    return {
        "job_id": job_id,
        "filename": filename,
        "stage": stage,
        "state_digest": state_digest,
        "summary": summary,
        "stage_headline": stage_headline,
        "stage_copy": stage_copy,
        "alerts": alerts[:4],
        "checklist": checklist,
        "primary_action": primary_action,
        "suggestions": suggestions[:5],
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        file.stream.seek(0)
        sha256_hash = hashlib.sha256()
        for chunk in iter(lambda: file.stream.read(4096), b""):
            sha256_hash.update(chunk)
        job_id = sha256_hash.hexdigest()

        _reset_local_job_runtime_artifacts(job_id)
        if SANDBOX_RUNNER_URL:
            try:
                _sandbox_runner_request("DELETE", f"/jobs/{job_id}", timeout=15)
            except Exception:
                pass

        _save_uploaded_sample(job_id, file)

        file.stream.seek(0)
        files = {"sample": (file.filename, file.stream, "application/octet-stream")}
        response = requests.post(f"{GHIDRAAAS_BASE}/analyze_sample/", files=files, timeout=600)
        if not response.ok:
            return jsonify({
                "error": f"Ghidraaas analysis failed for {file.filename}. {_response_error_details(response)}"
            }), 502

        _record_job_filename(job_id, file.filename)
        _trigger_sandbox_run(job_id, file.filename)
        queue_triage_report(job_id, file.filename)
        return jsonify({"job_id": job_id, "status": "DONE"})
        
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to connect to Ghidra service: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message')
    job_id = data.get('job_id')

    if not user_message or not job_id:
        return jsonify({"error": "Message and job_id are required"}), 400

    def generate():
        try:
            for chunk in assistant.chat_completion_stream(user_message, job_id):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            error_event = json.dumps({"type": "error", "content": str(e)})
            yield f"data: {error_event}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/jobs', methods=['GET'])
def list_jobs():
    try:
        metadata = _load_job_metadata()
        payload_projects = _fetch_projects(timeout=30)
        jobs = []
        for job in payload_projects:
            entry = metadata.get(job.get("job_id"), {})
            if not isinstance(entry, dict):
                entry = {"filename": str(entry)}
            jobs.append({
                **job,
                "filename": entry.get("filename"),
                "label": entry.get("label"),
                "archived": bool(entry.get("archived", False)),
            })
        return jsonify({"jobs": jobs})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to list jobs from Ghidraaas: {e}"}), 502


@app.route('/jobs/<job_id>', methods=['PATCH'])
def update_job(job_id):
    payload = request.get_json(silent=True) or {}
    updates = {}

    if "label" in payload:
        label = str(payload.get("label") or "").strip()
        updates["label"] = label or None

    if "archived" in payload:
        updates["archived"] = bool(payload.get("archived"))

    if not updates:
        return jsonify({"error": "No supported job updates provided"}), 400

    entry = _update_job_metadata(job_id, **updates)
    return jsonify({
        "job_id": job_id,
        "status": "updated",
        "job": {
            "job_id": job_id,
            "filename": entry.get("filename"),
            "label": entry.get("label"),
            "archived": bool(entry.get("archived", False)),
            "display_name": entry.get("label") or entry.get("filename") or f"{job_id[:8]}.bin",
        },
    })


@app.route('/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    summary = {
        "job_id": job_id,
        "ghidraaas": {"status": "skipped"},
        "sandbox_runner": {"status": "skipped"},
        "local": {},
    }

    try:
        response = requests.get(f"{GHIDRAAAS_BASE}/analysis_terminated/{job_id}", timeout=60)
        if response.ok:
            summary["ghidraaas"] = {"status": "deleted"}
        else:
            summary["ghidraaas"] = {
                "status": "error",
                "detail": _response_error_details(response),
            }
    except requests.exceptions.RequestException as e:
        summary["ghidraaas"] = {"status": "error", "detail": str(e)}

    if SANDBOX_RUNNER_URL:
        try:
            runner_payload = _sandbox_runner_request("DELETE", f"/jobs/{job_id}", timeout=20)
            summary["sandbox_runner"] = {"status": "deleted", **runner_payload}
        except Exception as e:
            summary["sandbox_runner"] = {"status": "error", "detail": str(e)}

    summary["local"] = _delete_local_job_artifacts(job_id)
    return jsonify({
        "job_id": job_id,
        "status": "deleted",
        "summary": summary,
    })


@app.route('/evidence/<job_id>', methods=['GET'])
def get_dynamic_evidence(job_id):
    payload = _load_dynamic_evidence(job_id)
    return jsonify({
        **payload,
        "summary": _summarize_evidence(payload),
    })


@app.route('/evidence/<job_id>', methods=['POST'])
def record_dynamic_evidence(job_id):
    data = request.get_json(silent=True) or {}
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        return jsonify({"error": "JSON body must include an 'artifacts' array"}), 400

    payload = _load_dynamic_evidence(job_id)
    existing = payload.get("artifacts", [])
    existing.extend(artifacts)
    payload["artifacts"] = existing
    _save_dynamic_evidence(job_id, payload)
    queue_triage_report(job_id, _load_job_metadata().get(job_id))
    return jsonify({
        "job_id": job_id,
        "status": "recorded",
        "summary": _summarize_evidence(payload),
    })


@app.route('/triage/<job_id>', methods=['GET'])
def get_triage_report(job_id):
    report = get_cached_triage_report(job_id)
    if report is None:
        queued = queue_triage_report(job_id, _load_job_metadata().get(job_id))
        return jsonify({
            "job_id": job_id,
            "status": "queued" if queued else "processing",
        }), 202

    status = report.get("status", "unknown")
    if status == "processing":
        queue_triage_report(job_id, _load_job_metadata().get(job_id))
        return jsonify(report), 202

    return jsonify(report)


@app.route('/triage/<job_id>/export', methods=['GET'])
def export_triage_report(job_id):
    report = get_cached_triage_report(job_id)
    if not report or report.get("status") != "completed":
        return jsonify({"error": "Triage report is not ready yet"}), 409

    export_format = str(request.args.get("format", "md")).lower()
    metadata = _load_job_metadata().get(job_id, {})
    if not isinstance(metadata, dict):
        metadata = {"filename": str(metadata)}
    base_name = metadata.get("label") or metadata.get("filename") or f"{job_id[:12]}"
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in base_name).strip("._") or job_id[:12]

    if export_format == "json":
        body = json.dumps(report, indent=2)
        mimetype = "application/json"
        filename = f"{safe_name}-triage.json"
    else:
        body = report.get("markdown") or "# Triage Report\n\n_No markdown report available._\n"
        mimetype = "text/markdown; charset=utf-8"
        filename = f"{safe_name}-triage.md"

    return Response(
        body,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route('/debug/x64dbg/<job_id>', methods=['GET'])
def get_x64dbg_state(job_id):
    try:
        return jsonify(_sandbox_runner_request("GET", f"/jobs/{job_id}/x64dbg", timeout=15))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to load x64dbg state: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>', methods=['POST'])
def update_x64dbg_state(job_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(_sandbox_runner_request("POST", f"/jobs/{job_id}/x64dbg", json=payload, timeout=20))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to update x64dbg state: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/findings', methods=['GET'])
def get_x64dbg_findings(job_id):
    try:
        return jsonify(_sandbox_runner_request("GET", f"/jobs/{job_id}/x64dbg/findings", timeout=15))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to load x64dbg findings: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/findings', methods=['POST'])
def add_x64dbg_findings(job_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(_sandbox_runner_request("POST", f"/jobs/{job_id}/x64dbg/findings", json=payload, timeout=20))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to store x64dbg findings: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/requests', methods=['GET'])
def get_x64dbg_requests(job_id):
    try:
        return jsonify(_sandbox_runner_request("GET", f"/jobs/{job_id}/x64dbg/requests", timeout=15))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to load x64dbg requests: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/requests', methods=['POST'])
def add_x64dbg_request(job_id):
    payload = request.get_json(silent=True) or {}
    try:
        sandbox_payload = _sandbox_runner_request("POST", f"/jobs/{job_id}/x64dbg/requests", json=payload, timeout=20)
        return jsonify(sandbox_payload), 202
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to queue x64dbg request: {e}"}), 502


@app.route('/assistant/next_steps/<job_id>', methods=['GET'])
def assistant_next_steps(job_id):
    try:
        return jsonify(_assistant_next_steps(job_id))
    except Exception as e:
        return jsonify({"error": f"Failed to compute assistant next steps: {e}"}), 500
        
@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    metadata = _load_job_metadata()
    cached_triage = get_cached_triage_report(job_id)

    if cached_triage:
        triage_status = cached_triage.get("status")
        if triage_status == "completed":
            return jsonify({
                "job_id": job_id,
                "status": "done",
                "phase": "triage_ready",
            })
        if triage_status in {"queued", "processing"}:
            return jsonify({
                "job_id": job_id,
                "status": "analyzing",
                "phase": "triage_building",
            })

    try:
        projects = _fetch_projects(timeout=10)
        project_exists = any(project.get("job_id") == job_id for project in projects)

        if project_exists:
            try:
                functions_response = requests.get(
                    f"{GHIDRAAAS_BASE}/get_functions_list/{job_id}",
                    timeout=15,
                )
                if functions_response.status_code == 200:
                    return jsonify({
                        "job_id": job_id,
                        "status": "done",
                        "phase": "function_index_ready",
                    })
                if functions_response.status_code == 202:
                    return jsonify({
                        "job_id": job_id,
                        "status": "analyzing",
                        "phase": "function_indexing",
                    })
                if functions_response.status_code == 400:
                    return jsonify({
                        "job_id": job_id,
                        "status": "analyzing",
                        "phase": "ghidra_processing",
                    })
                return jsonify({
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                    "warning": _response_error_details(functions_response),
                })
            except requests.Timeout:
                return jsonify({
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                    "warning": "Ghidraaas is still processing this sample.",
                })

        if job_id in metadata:
            return jsonify({
                "job_id": job_id,
                "status": "analyzing",
                "phase": "uploaded",
            })

        return jsonify({"job_id": job_id, "status": "pending"})
    except requests.Timeout:
        if job_id in metadata:
            return jsonify({
                "job_id": job_id,
                "status": "analyzing",
                "phase": "ghidra_processing",
                "warning": "Ghidraaas is still busy processing this sample.",
            })
        return jsonify({"job_id": job_id, "status": "pending"})
    except requests.HTTPError as error:
        response = getattr(error, "response", None)
        if response is not None and response.status_code == 400:
            response_text = response.text.strip()
            if "Sample has not been analyzed" in response_text:
                return jsonify({"job_id": job_id, "status": "pending"})

        if job_id in metadata:
            return jsonify({
                "job_id": job_id,
                "status": "analyzing",
                "phase": "ghidra_processing",
            })
        return jsonify({"job_id": job_id, "status": "error", "error": str(error)}), 502
    except requests.exceptions.RequestException as e:
        if job_id in metadata:
            return jsonify({
                "job_id": job_id,
                "status": "analyzing",
                "phase": "ghidra_processing",
                "warning": f"Ghidraaas is temporarily unavailable: {e}",
            })
        return jsonify({"job_id": job_id, "status": "error", "error": str(e)}), 502

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
