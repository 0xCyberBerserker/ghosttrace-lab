import json
import os
import hmac
from pathlib import Path
import requests
from assistant_guidance import build_assistant_next_steps
from flask import Flask, render_template, request, jsonify, Response
from ghidra_client import GhidraClient
from ghidra_assistant import GhidraAssistant 
from input_validation import (
    normalize_job_label,
    require_json_body,
    validate_draft_artifact_payload,
    validate_artifacts_payload,
    validate_hypothesis_payload,
    validate_reconstruction_generate_payload,
    validate_reconstruction_target_payload,
    validate_validation_plan_payload,
    validate_x64dbg_findings_payload,
    validate_x64dbg_request_payload,
    validate_x64dbg_state_payload,
)
from sandbox_credentials import SandboxCredentialsManager
from observability import init_observability
from security import RateLimitRule, init_security
from job_service import JobService
from job_store import JobStore
from job_workflow import JobWorkflow
from metrics import build_metrics_summary, build_prometheus_metrics
from sandbox_client import SandboxClient
from triage_report import get_cached_triage_report, queue_triage_report
from reconstruction_service import ReconstructionService
from e2e_fixture import E2EFixture

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(100 * 1024 * 1024)))
app.config["OPERATOR_USERNAME"] = os.getenv("OPERATOR_USERNAME", "")
app.config["OPERATOR_PASSWORD"] = os.getenv("OPERATOR_PASSWORD", "")
app.config["RATE_LIMIT_UPLOAD"] = RateLimitRule(
    limit=int(os.getenv("RATE_LIMIT_UPLOAD_COUNT", "10")),
    window_seconds=int(os.getenv("RATE_LIMIT_UPLOAD_WINDOW_SECONDS", "60")),
)
app.config["RATE_LIMIT_CHAT"] = RateLimitRule(
    limit=int(os.getenv("RATE_LIMIT_CHAT_COUNT", "30")),
    window_seconds=int(os.getenv("RATE_LIMIT_CHAT_WINDOW_SECONDS", "60")),
)
app.config["RATE_LIMIT_REVEAL"] = RateLimitRule(
    limit=int(os.getenv("RATE_LIMIT_REVEAL_COUNT", "6")),
    window_seconds=int(os.getenv("RATE_LIMIT_REVEAL_WINDOW_SECONDS", "60")),
)
app.config["RATE_LIMIT_X64DBG"] = RateLimitRule(
    limit=int(os.getenv("RATE_LIMIT_X64DBG_COUNT", "30")),
    window_seconds=int(os.getenv("RATE_LIMIT_X64DBG_WINDOW_SECONDS", "60")),
)
assistant = GhidraAssistant()
GHIDRAAAS_BASE = os.getenv("GHIDRAAAS_BASE", "http://localhost:8080/ghidra/api")
JOB_METADATA_PATH = Path(os.getenv("JOB_METADATA_PATH", "/app/data/job_metadata.json"))
DYNAMIC_EVIDENCE_DIR = Path(os.getenv("DYNAMIC_EVIDENCE_DIR", "/app/data/dynamic_evidence"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/app/data/uploads"))
JOB_STORE_DB_PATH = Path(os.getenv("JOB_STORE_DB_PATH", "/app/data/ghosttrace.db"))
SANDBOX_RUNNER_URL = os.getenv("SANDBOX_RUNNER_URL")
SANDBOX_SHARED_TOKEN = os.getenv("SANDBOX_SHARED_TOKEN")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN") or SANDBOX_SHARED_TOKEN
TRIAGE_REPORT_DIR = Path(os.getenv("TRIAGE_REPORT_DIR", "/app/data/triage_reports"))
WINDOWS_SANDBOX_CREDENTIALS_PATH = Path(
    os.getenv("WINDOWS_SANDBOX_CREDENTIALS_PATH", "/app/config/sandbox/windows-sandbox.env")
)
E2E_FIXTURE_ENABLED = os.getenv("GHOSTTRACE_E2E_FIXTURE", "").lower() in {"1", "true", "yes", "on"}
job_store = JobStore(
    metadata_path=JOB_METADATA_PATH,
    uploads_dir=UPLOADS_DIR,
    dynamic_evidence_dir=DYNAMIC_EVIDENCE_DIR,
    triage_report_dir=TRIAGE_REPORT_DIR,
    db_path=JOB_STORE_DB_PATH,
)
sandbox_credentials = SandboxCredentialsManager(WINDOWS_SANDBOX_CREDENTIALS_PATH)
e2e_fixture = E2EFixture(job_store, TRIAGE_REPORT_DIR, WINDOWS_SANDBOX_CREDENTIALS_PATH) if E2E_FIXTURE_ENABLED else None
if e2e_fixture is not None:
    e2e_fixture.seed()
init_security(app)


def _webui_readiness():
    if E2E_FIXTURE_ENABLED:
        return {
            "ready": True,
            "checks": {
                "sqlite_db_present": True,
                "ollama_configured": True,
                "ghidra_configured": True,
                "sandbox_runner_configured": True,
                "e2e_fixture": True,
            },
        }
    checks = {
        "sqlite_db_present": JOB_STORE_DB_PATH.exists(),
        "ollama_configured": bool(os.getenv("API_BASE") and os.getenv("MODEL_NAME")),
        "ghidra_configured": bool(GHIDRAAAS_BASE),
        "sandbox_runner_configured": bool(SANDBOX_RUNNER_URL),
    }
    return {
        "ready": checks["sqlite_db_present"] and checks["ollama_configured"] and checks["ghidra_configured"],
        "checks": checks,
    }


init_observability(app, "webui", _webui_readiness)


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


ghidra_client = GhidraClient(GHIDRAAAS_BASE, _response_error_details)
sandbox_client = SandboxClient(SANDBOX_RUNNER_URL, _response_error_details, auth_token=SANDBOX_SHARED_TOKEN)
job_service = JobService(
    job_store,
    ghidra_client=ghidra_client,
    sandbox_client=sandbox_client,
    ghidra_base=GHIDRAAAS_BASE,
    response_error_details=_response_error_details,
)
job_workflow = JobWorkflow(
    job_store=job_store,
    job_service=job_service,
    ghidra_client=ghidra_client,
    sandbox_client=sandbox_client,
    queue_triage_report=queue_triage_report,
)
reconstruction_service = ReconstructionService(job_store)


def _summarize_evidence(payload):
    return job_store.summarize_evidence(payload)


def _safe_x64dbg_snapshot(job_id):
    return sandbox_client.safe_x64dbg_snapshot(job_id)


def _require_internal_token():
    if not INTERNAL_API_TOKEN:
        return None

    provided = request.headers.get("X-Internal-Token", "")
    if not hmac.compare_digest(provided, INTERNAL_API_TOKEN):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/sandbox/windows_lab_credentials', methods=['GET'])
def get_windows_lab_credentials():
    payload = sandbox_credentials.load_credentials()
    if not payload:
        return jsonify({
            "error": "Windows sandbox credentials are not available yet. Start the optional windows_sandbox profile once to generate them."
        }), 404
    response = jsonify({
        "username": payload.get("USERNAME", sandbox_credentials.default_username),
        "password_available": bool(payload.get("PASSWORD")),
        "vnc_url": "http://127.0.0.1:8006",
        "rdp_host": "127.0.0.1:3389",
        "ssh_host": "127.0.0.1:2222",
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route('/sandbox/windows_lab_credentials/reveal', methods=['POST'])
def reveal_windows_lab_credentials():
    payload = sandbox_credentials.load_credentials()
    if not payload or not payload.get("PASSWORD"):
        return jsonify({
            "error": "Windows sandbox credentials are not available yet. Start the optional windows_sandbox profile once to generate them."
        }), 404

    response = jsonify({
        "username": payload.get("USERNAME", sandbox_credentials.default_username),
        "password": payload.get("PASSWORD"),
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route('/metrics/summary', methods=['GET'])
def metrics_summary():
    summary = e2e_fixture.metrics_summary() if e2e_fixture is not None else build_metrics_summary(job_store, TRIAGE_REPORT_DIR)
    return jsonify(summary)


@app.route('/metrics', methods=['GET'])
def metrics_text():
    summary = e2e_fixture.metrics_summary() if e2e_fixture is not None else build_metrics_summary(job_store, TRIAGE_REPORT_DIR)
    return Response(build_prometheus_metrics(summary), mimetype="text/plain; version=0.0.4; charset=utf-8")

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        response, job_id, safe_filename = job_workflow.upload_and_analyze(file)
        if not response.ok:
            return jsonify({
                "error": f"Ghidraaas analysis failed for {safe_filename}. {_response_error_details(response)}"
            }), 502
        return jsonify({"job_id": job_id, "status": "ANALYZING", "filename": safe_filename})
        
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
    if e2e_fixture is not None:
        jobs = [job.to_dict() for job in job_service.list_jobs(e2e_fixture.list_jobs())]
        return jsonify({"jobs": jobs})
    try:
        payload_projects = ghidra_client.list_projects(timeout=30)
        jobs = [job.to_dict() for job in job_service.list_jobs(payload_projects)]
        return jsonify({"jobs": jobs})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to list jobs from Ghidraaas: {e}"}), 502


@app.route('/jobs/<job_id>', methods=['PATCH'])
def update_job(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code

    payload = request.get_json(silent=True) or {}
    updates = {}

    if "label" in payload:
        updates["label"] = normalize_job_label(payload.get("label"))

    if "archived" in payload:
        updates["archived"] = bool(payload.get("archived"))

    if not updates:
        return jsonify({"error": "No supported job updates provided"}), 400

    job = job_service.update_job(job_id, **updates)
    return jsonify({
        "job_id": job_id,
        "status": "updated",
        "job": job.to_dict(),
    })


@app.route('/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    summary = job_service.delete_job(job_id)
    return jsonify({
        "job_id": job_id,
        "status": "deleted",
        "summary": summary,
    })


@app.route('/evidence/<job_id>', methods=['GET'])
def get_dynamic_evidence(job_id):
    payload = job_store.load_dynamic_evidence(job_id)
    return jsonify({
        **payload,
        "summary": _summarize_evidence(payload),
    })


@app.route('/evidence/<job_id>', methods=['POST'])
def record_dynamic_evidence(job_id):
    unauthorized = _require_internal_token()
    if unauthorized:
        return unauthorized

    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code

    data = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_artifacts_payload(data)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code

    payload = job_store.load_dynamic_evidence(job_id)
    existing = payload.get("artifacts", [])
    existing.extend(sanitized_payload["artifacts"])
    payload["artifacts"] = existing
    job_store.save_dynamic_evidence(job_id, payload)
    queue_triage_report(job_id, job_service.triage_filename_hint(job_id))
    return jsonify({
        "job_id": job_id,
        "status": "recorded",
        "summary": _summarize_evidence(payload),
    })


@app.route('/triage/<job_id>', methods=['GET'])
def get_triage_report(job_id):
    report = get_cached_triage_report(job_id)
    if report is None:
        queued = queue_triage_report(job_id, job_service.triage_filename_hint(job_id))
        return jsonify({
            "job_id": job_id,
            "status": "queued" if queued else "processing",
        }), 202

    status = report.get("status", "unknown")
    if status == "processing":
        queue_triage_report(job_id, job_service.triage_filename_hint(job_id))
        return jsonify(report), 202

    return jsonify(report)


@app.route('/triage/<job_id>/export', methods=['GET'])
def export_triage_report(job_id):
    report = get_cached_triage_report(job_id)
    if not report or report.get("status") != "completed":
        return jsonify({"error": "Triage report is not ready yet"}), 409

    export_format = str(request.args.get("format", "md")).lower()
    safe_name = job_service.export_filename_root(job_id)

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
    if e2e_fixture is not None:
        return jsonify(e2e_fixture.x64dbg_state(job_id))
    try:
        return jsonify(sandbox_client.request("GET", f"/jobs/{job_id}/x64dbg", timeout=15))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to load x64dbg state: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>', methods=['POST'])
def update_x64dbg_state(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code

    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_x64dbg_state_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    try:
        return jsonify(sandbox_client.request("POST", f"/jobs/{job_id}/x64dbg", json=sanitized_payload, timeout=20))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to update x64dbg state: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/findings', methods=['GET'])
def get_x64dbg_findings(job_id):
    if e2e_fixture is not None:
        return jsonify(e2e_fixture.x64dbg_findings(job_id))
    try:
        return jsonify(sandbox_client.request("GET", f"/jobs/{job_id}/x64dbg/findings", timeout=15))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to load x64dbg findings: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/findings', methods=['POST'])
def add_x64dbg_findings(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code

    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_x64dbg_findings_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    try:
        return jsonify(sandbox_client.request("POST", f"/jobs/{job_id}/x64dbg/findings", json=sanitized_payload, timeout=20))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to store x64dbg findings: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/requests', methods=['GET'])
def get_x64dbg_requests(job_id):
    if e2e_fixture is not None:
        return jsonify(e2e_fixture.x64dbg_requests(job_id))
    try:
        return jsonify(sandbox_client.request("GET", f"/jobs/{job_id}/x64dbg/requests", timeout=15))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to load x64dbg requests: {e}"}), 502


@app.route('/debug/x64dbg/<job_id>/requests', methods=['POST'])
def add_x64dbg_request(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code

    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_x64dbg_request_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    try:
        sandbox_payload = sandbox_client.request("POST", f"/jobs/{job_id}/x64dbg/requests", json=sanitized_payload, timeout=20)
        return jsonify(sandbox_payload), 202
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to queue x64dbg request: {e}"}), 502


@app.route('/assistant/next_steps/<job_id>', methods=['GET'])
def assistant_next_steps(job_id):
    try:
        return jsonify(
            build_assistant_next_steps(
                job_id=job_id,
                job_store=job_store,
                triage_report=get_cached_triage_report(job_id),
                x64dbg_snapshot=_safe_x64dbg_snapshot(job_id),
            )
        )
    except Exception as e:
        return jsonify({"error": f"Failed to compute assistant next steps: {e}"}), 500


@app.route('/reconstruction/<job_id>', methods=['GET'])
def get_reconstruction_bundle(job_id):
    return jsonify(reconstruction_service.list_bundle(job_id))


@app.route('/reconstruction/<job_id>/targets', methods=['POST'])
def add_reconstruction_target(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code
    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_reconstruction_target_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    target = reconstruction_service.save_target(job_id, sanitized_payload)
    return jsonify({"status": "stored", "target": target.to_dict()}), 201


@app.route('/reconstruction/<job_id>/targets/generate', methods=['POST'])
def generate_reconstruction_targets(job_id):
    triage_report = get_cached_triage_report(job_id)
    if not triage_report or triage_report.get("status") != "completed":
        return jsonify({"error": "Completed triage report is required before generating reconstruction targets"}), 409

    evidence_payload = job_store.load_dynamic_evidence(job_id)
    targets = reconstruction_service.generate_targets(job_id, triage_report, evidence_payload)
    return jsonify({
        "status": "generated",
        "job_id": job_id,
        "targets": targets,
    }), 201


@app.route('/reconstruction/<job_id>/hypotheses', methods=['POST'])
def add_reconstruction_hypothesis(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code
    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_hypothesis_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    hypothesis = reconstruction_service.save_hypothesis(job_id, sanitized_payload)
    return jsonify({"status": "stored", "hypothesis": hypothesis.to_dict()}), 201


@app.route('/reconstruction/<job_id>/hypotheses/generate', methods=['POST'])
def generate_reconstruction_hypotheses(job_id):
    triage_report = get_cached_triage_report(job_id)
    if not triage_report or triage_report.get("status") != "completed":
        return jsonify({"error": "Completed triage report is required before generating hypotheses"}), 409

    targets = job_store.list_reconstruction_targets(job_id)
    if not targets:
        return jsonify({"error": "At least one reconstruction target is required before generating hypotheses"}), 409

    evidence_payload = job_store.load_dynamic_evidence(job_id)
    hypotheses = reconstruction_service.generate_hypotheses(job_id, triage_report, evidence_payload)
    return jsonify({
        "status": "generated",
        "job_id": job_id,
        "hypotheses": hypotheses,
    }), 201


@app.route('/reconstruction/<job_id>/drafts', methods=['POST'])
def add_reconstruction_draft(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code
    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_draft_artifact_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    artifact = reconstruction_service.save_draft_artifact(job_id, sanitized_payload)
    return jsonify({"status": "stored", "draft_artifact": artifact.to_dict()}), 201


@app.route('/reconstruction/<job_id>/drafts/generate', methods=['POST'])
def generate_reconstruction_drafts(job_id):
    payload = request.get_json(silent=True) if request.is_json else None
    sanitized_payload, validation_error = validate_reconstruction_generate_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code

    triage_report = get_cached_triage_report(job_id)
    if not triage_report or triage_report.get("status") != "completed":
        return jsonify({"error": "Completed triage report is required before generating draft artifacts"}), 409

    targets = job_store.list_reconstruction_targets(job_id)
    if not targets:
        return jsonify({"error": "At least one reconstruction target is required before generating draft artifacts"}), 409

    hypotheses = job_store.list_hypotheses(job_id)
    if not hypotheses:
        return jsonify({"error": "At least one hypothesis is required before generating draft artifacts"}), 409

    if sanitized_payload.get("target_id") and not reconstruction_service.get_target(job_id, sanitized_payload["target_id"]):
        return jsonify({"error": "Requested reconstruction target does not exist"}), 404

    evidence_payload = job_store.load_dynamic_evidence(job_id)
    draft_artifacts = reconstruction_service.generate_drafts(
        job_id,
        triage_report,
        evidence_payload,
        target_id=sanitized_payload.get("target_id"),
    )
    return jsonify({
        "status": "generated",
        "job_id": job_id,
        "draft_artifacts": draft_artifacts,
    }), 201


@app.route('/reconstruction/<job_id>/drafts/<artifact_id>/export', methods=['GET'])
def export_reconstruction_draft(job_id, artifact_id):
    bundle = reconstruction_service.export_draft_bundle(job_id, artifact_id)
    if bundle is None:
        return jsonify({"error": "Requested reconstruction artifact was not found"}), 404

    export_format = str(request.args.get("format", "md")).lower()
    safe_name = job_service.export_filename_root(job_id)

    if export_format == "json":
        body = json.dumps(bundle, indent=2)
        mimetype = "application/json"
        filename = f"{safe_name}-{artifact_id}.json"
    else:
        artifact = bundle["artifact"]
        target = bundle.get("target") or {}
        hypotheses = bundle.get("hypotheses") or []
        plans = bundle.get("validation_plans") or []
        lines = [
            f"# {artifact.get('title') or 'Reconstruction Package'}",
            "",
            "## Summary",
            artifact.get("summary") or "_No summary available._",
            "",
            "## Target",
            f"- ID: `{target.get('target_id', artifact.get('target_id') or 'unscoped')}`",
            f"- Title: {target.get('title', 'Unknown target')}",
            f"- Scope: `{target.get('scope', 'unknown')}`",
            f"- Validation status: `{artifact.get('validation_status', 'draft')}`",
            "",
            "## Assumptions",
        ]
        assumptions = artifact.get("assumptions") or []
        if assumptions:
            lines.extend([f"- {item}" for item in assumptions])
        else:
            lines.append("- No assumptions recorded.")
        lines.extend([
            "",
            "## Evidence Links",
        ])
        evidence_links = artifact.get("evidence_links") or []
        if evidence_links:
            lines.extend([f"- {item}" for item in evidence_links])
        else:
            lines.append("- No evidence links recorded.")
        lines.extend([
            "",
            "## Draft Body",
            artifact.get("body") or "_No draft body available._",
            "",
            "## Hypotheses",
        ])
        if hypotheses:
            for hypothesis in hypotheses:
                lines.extend([
                    f"### {hypothesis.get('title', 'Hypothesis')}",
                    f"- Claim: {hypothesis.get('claim', '')}",
                    f"- Confidence: `{hypothesis.get('confidence', 'unknown')}`",
                    f"- Next step: {hypothesis.get('next_step', 'n/a')}",
                ])
        else:
            lines.append("- No linked hypotheses recorded.")
        lines.extend([
            "",
            "## Validation Plans",
        ])
        if plans:
            for plan in plans:
                lines.append(f"### {plan.get('title', 'Validation plan')}")
                for check in plan.get("checks", []):
                    lines.append(
                        f"- [{ 'x' if check.get('status') == 'completed' else ' ' }] {check.get('label', 'Check')} | expected: {check.get('expected', 'n/a')} | method: {check.get('method', 'n/a')}"
                    )
                for risk in plan.get("open_risks", []):
                    lines.append(f"- Open risk: {risk}")
        else:
            lines.append("- No validation plan recorded.")
        body = "\n".join(lines)
        mimetype = "text/markdown; charset=utf-8"
        filename = f"{safe_name}-{artifact_id}.md"

    return Response(
        body,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route('/reconstruction/<job_id>/validation_plans', methods=['POST'])
def add_reconstruction_validation_plan(job_id):
    ok, error = require_json_body(request)
    if not ok:
        message, status_code = error
        return jsonify({"error": message}), status_code
    payload = request.get_json(silent=True) or {}
    sanitized_payload, validation_error = validate_validation_plan_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code
    plan = reconstruction_service.save_validation_plan(job_id, sanitized_payload)
    return jsonify({"status": "stored", "validation_plan": plan.to_dict()}), 201


@app.route('/reconstruction/<job_id>/validation_plans/generate', methods=['POST'])
def generate_reconstruction_validation_plans(job_id):
    payload = request.get_json(silent=True) if request.is_json else None
    sanitized_payload, validation_error = validate_reconstruction_generate_payload(payload)
    if validation_error:
        message, status_code = validation_error
        return jsonify({"error": message}), status_code

    triage_report = get_cached_triage_report(job_id)
    if not triage_report or triage_report.get("status") != "completed":
        return jsonify({"error": "Completed triage report is required before generating validation plans"}), 409

    targets = job_store.list_reconstruction_targets(job_id)
    if not targets:
        return jsonify({"error": "At least one reconstruction target is required before generating validation plans"}), 409

    hypotheses = job_store.list_hypotheses(job_id)
    if not hypotheses:
        return jsonify({"error": "At least one hypothesis is required before generating validation plans"}), 409

    if sanitized_payload.get("target_id") and not reconstruction_service.get_target(job_id, sanitized_payload["target_id"]):
        return jsonify({"error": "Requested reconstruction target does not exist"}), 404

    evidence_payload = job_store.load_dynamic_evidence(job_id)
    validation_plans = reconstruction_service.generate_validation_plans(
        job_id,
        triage_report,
        evidence_payload,
        target_id=sanitized_payload.get("target_id"),
    )
    return jsonify({
        "status": "generated",
        "job_id": job_id,
        "validation_plans": validation_plans,
    }), 201
        
@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    if e2e_fixture is not None and job_id == e2e_fixture.job_id:
        payload, status_code = e2e_fixture.status(job_id)
        return jsonify(payload), status_code
    cached_triage = get_cached_triage_report(job_id)
    payload, status_code = job_service.get_status(job_id, cached_triage)
    return jsonify(payload), status_code

if __name__ == '__main__':
    flask_debug = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=flask_debug, host="0.0.0.0", port=port)
