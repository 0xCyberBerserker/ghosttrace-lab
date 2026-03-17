import os
import re


MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", str(1024 * 1024)))
MAX_JOB_LABEL_LENGTH = int(os.getenv("MAX_JOB_LABEL_LENGTH", "120"))
MAX_ARTIFACTS_PER_REQUEST = int(os.getenv("MAX_ARTIFACTS_PER_REQUEST", "100"))
MAX_HIGHLIGHTS_PER_ARTIFACT = int(os.getenv("MAX_HIGHLIGHTS_PER_ARTIFACT", "20"))
MAX_STRING_FIELD_LENGTH = int(os.getenv("MAX_STRING_FIELD_LENGTH", "512"))
MAX_FINDINGS_PER_REQUEST = int(os.getenv("MAX_FINDINGS_PER_REQUEST", "100"))
MAX_X64DBG_REQUEST_PARAMS = int(os.getenv("MAX_X64DBG_REQUEST_PARAMS", "20"))
MAX_RECONSTRUCTION_LINKS = int(os.getenv("MAX_RECONSTRUCTION_LINKS", "20"))
MAX_VALIDATION_CHECKS = int(os.getenv("MAX_VALIDATION_CHECKS", "25"))

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value, max_length=MAX_STRING_FIELD_LENGTH):
    text = _CONTROL_CHARS_RE.sub("", str(value)).strip()
    return text[:max_length]


def require_json_body(request):
    if not request.is_json:
        return False, ("Request body must be JSON", 415)
    if request.content_length is not None and request.content_length > MAX_JSON_BODY_BYTES:
        return False, (f"JSON body exceeds the limit of {MAX_JSON_BODY_BYTES} bytes", 413)
    return True, None


def normalize_job_label(raw_label):
    label = _clean_text(raw_label, max_length=MAX_JOB_LABEL_LENGTH)
    return label or None


def validate_artifacts_payload(data):
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        return None, ("JSON body must include an 'artifacts' array", 400)
    if len(artifacts) > MAX_ARTIFACTS_PER_REQUEST:
        return None, (f"Too many artifacts; limit is {MAX_ARTIFACTS_PER_REQUEST}", 400)

    sanitized_artifacts = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return None, ("Each artifact must be a JSON object", 400)

        sanitized = {}
        artifact_type = _clean_text(artifact.get("type", "unknown"), max_length=64)
        sanitized["type"] = artifact_type or "unknown"

        highlights = artifact.get("highlights", [])
        if highlights is None:
            highlights = []
        if not isinstance(highlights, list):
            return None, ("Artifact 'highlights' must be an array", 400)
        if len(highlights) > MAX_HIGHLIGHTS_PER_ARTIFACT:
            return None, (f"Too many highlights per artifact; limit is {MAX_HIGHLIGHTS_PER_ARTIFACT}", 400)
        sanitized["highlights"] = [
            _clean_text(highlight)
            for highlight in highlights
            if str(highlight).strip()
        ]

        for field in ("summary", "path", "value", "timestamp", "source"):
            if field in artifact:
                sanitized[field] = _clean_text(artifact[field])

        if "metadata" in artifact:
            metadata = artifact["metadata"]
            if not isinstance(metadata, dict):
                return None, ("Artifact 'metadata' must be an object", 400)
            sanitized["metadata"] = {
                _clean_text(key, max_length=64): _clean_text(value)
                for key, value in list(metadata.items())[:MAX_X64DBG_REQUEST_PARAMS]
                if _clean_text(key, max_length=64)
            }

        sanitized_artifacts.append(sanitized)

    return {"artifacts": sanitized_artifacts}, None


def validate_x64dbg_state_payload(data):
    if not isinstance(data, dict):
        return None, ("x64dbg state payload must be a JSON object", 400)

    sanitized = {}
    for key, value in list(data.items())[:MAX_X64DBG_REQUEST_PARAMS]:
        clean_key = _clean_text(key, max_length=64)
        if not clean_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[clean_key] = _clean_text(value) if isinstance(value, str) else value
        elif isinstance(value, list):
            sanitized[clean_key] = [_clean_text(item) for item in value[:MAX_HIGHLIGHTS_PER_ARTIFACT]]
        elif isinstance(value, dict):
            sanitized[clean_key] = {
                _clean_text(inner_key, max_length=64): _clean_text(inner_value)
                for inner_key, inner_value in list(value.items())[:MAX_X64DBG_REQUEST_PARAMS]
                if _clean_text(inner_key, max_length=64)
            }
    return sanitized, None


def validate_x64dbg_findings_payload(data):
    if not isinstance(data, dict):
        return None, ("x64dbg findings payload must be a JSON object", 400)

    findings = data.get("findings")
    if not isinstance(findings, list):
        return None, ("x64dbg findings payload must include a 'findings' array", 400)
    if len(findings) > MAX_FINDINGS_PER_REQUEST:
        return None, (f"Too many findings; limit is {MAX_FINDINGS_PER_REQUEST}", 400)

    sanitized_findings = []
    for finding in findings:
        if not isinstance(finding, dict):
            return None, ("Each finding must be a JSON object", 400)
        sanitized_findings.append({
            "summary": _clean_text(finding.get("summary", ""), max_length=256),
            "severity": _clean_text(finding.get("severity", ""), max_length=32),
            "address": _clean_text(finding.get("address", ""), max_length=64),
            "notes": _clean_text(finding.get("notes", "")),
        })
    return {"findings": sanitized_findings}, None


def validate_x64dbg_request_payload(data):
    if not isinstance(data, dict):
        return None, ("x64dbg request payload must be a JSON object", 400)

    action = _clean_text(data.get("action", ""), max_length=64)
    if not action:
        return None, ("x64dbg request payload must include a non-empty 'action'", 400)

    sanitized = {"action": action}
    params = data.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return None, ("x64dbg request 'params' must be an object", 400)
    sanitized["params"] = {
        _clean_text(key, max_length=64): _clean_text(value)
        for key, value in list(params.items())[:MAX_X64DBG_REQUEST_PARAMS]
        if _clean_text(key, max_length=64)
    }

    if "notes" in data:
        sanitized["notes"] = _clean_text(data["notes"])

    return sanitized, None


def _clean_text_list(raw_items, *, limit, item_max_length=MAX_STRING_FIELD_LENGTH):
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise ValueError("Expected an array")
    return [
        _clean_text(item, max_length=item_max_length)
        for item in raw_items[:limit]
        if _clean_text(item, max_length=item_max_length)
    ]


def validate_reconstruction_target_payload(data):
    if not isinstance(data, dict):
        return None, ("Reconstruction target payload must be a JSON object", 400)

    title = _clean_text(data.get("title", ""), max_length=160)
    scope = _clean_text(data.get("scope", ""), max_length=64)
    target_id = _clean_text(data.get("target_id", ""), max_length=64)
    if not title or not scope or not target_id:
        return None, ("Reconstruction targets require non-empty 'target_id', 'title', and 'scope'", 400)

    try:
        evidence_links = _clean_text_list(data.get("evidence_links", []), limit=MAX_RECONSTRUCTION_LINKS)
    except ValueError:
        return None, ("Reconstruction target 'evidence_links' must be an array", 400)

    status = _clean_text(data.get("status", "proposed"), max_length=32) or "proposed"
    priority_raw = data.get("priority", 50)
    try:
        priority = int(priority_raw)
    except (TypeError, ValueError):
        return None, ("Reconstruction target 'priority' must be an integer", 400)

    return {
        "target_id": target_id,
        "title": title,
        "scope": scope,
        "status": status,
        "rationale": _clean_text(data.get("rationale", "")),
        "priority": max(0, min(priority, 1000)),
        "evidence_links": evidence_links,
    }, None


def validate_hypothesis_payload(data):
    if not isinstance(data, dict):
        return None, ("Hypothesis payload must be a JSON object", 400)

    hypothesis_id = _clean_text(data.get("hypothesis_id", ""), max_length=64)
    title = _clean_text(data.get("title", ""), max_length=160)
    claim = _clean_text(data.get("claim", ""), max_length=1024)
    if not hypothesis_id or not title or not claim:
        return None, ("Hypotheses require non-empty 'hypothesis_id', 'title', and 'claim'", 400)

    try:
        supporting_evidence = _clean_text_list(data.get("supporting_evidence", []), limit=MAX_RECONSTRUCTION_LINKS)
        missing_evidence = _clean_text_list(data.get("missing_evidence", []), limit=MAX_RECONSTRUCTION_LINKS)
    except ValueError:
        return None, ("Hypothesis evidence fields must be arrays", 400)

    return {
        "hypothesis_id": hypothesis_id,
        "target_id": _clean_text(data.get("target_id", ""), max_length=64) or None,
        "title": title,
        "claim": claim,
        "confidence": _clean_text(data.get("confidence", "medium"), max_length=32) or "medium",
        "supporting_evidence": supporting_evidence,
        "missing_evidence": missing_evidence,
        "next_step": _clean_text(data.get("next_step", "")),
    }, None


def validate_draft_artifact_payload(data):
    if not isinstance(data, dict):
        return None, ("Draft artifact payload must be a JSON object", 400)

    artifact_id = _clean_text(data.get("artifact_id", ""), max_length=64)
    title = _clean_text(data.get("title", ""), max_length=160)
    artifact_type = _clean_text(data.get("artifact_type", ""), max_length=64)
    if not artifact_id or not title or not artifact_type:
        return None, ("Draft artifacts require non-empty 'artifact_id', 'title', and 'artifact_type'", 400)

    try:
        evidence_links = _clean_text_list(data.get("evidence_links", []), limit=MAX_RECONSTRUCTION_LINKS)
        assumptions = _clean_text_list(data.get("assumptions", []), limit=MAX_RECONSTRUCTION_LINKS)
    except ValueError:
        return None, ("Draft artifact list fields must be arrays", 400)

    return {
        "artifact_id": artifact_id,
        "target_id": _clean_text(data.get("target_id", ""), max_length=64) or None,
        "title": title,
        "artifact_type": artifact_type,
        "summary": _clean_text(data.get("summary", ""), max_length=1024),
        "body": _clean_text(data.get("body", ""), max_length=8000),
        "evidence_links": evidence_links,
        "assumptions": assumptions,
        "validation_status": _clean_text(data.get("validation_status", "draft"), max_length=32) or "draft",
    }, None


def validate_validation_plan_payload(data):
    if not isinstance(data, dict):
        return None, ("Validation plan payload must be a JSON object", 400)

    plan_id = _clean_text(data.get("plan_id", ""), max_length=64)
    title = _clean_text(data.get("title", ""), max_length=160)
    if not plan_id or not title:
        return None, ("Validation plans require non-empty 'plan_id' and 'title'", 400)

    checks = data.get("checks", [])
    if checks is None:
        checks = []
    if not isinstance(checks, list):
        return None, ("Validation plan 'checks' must be an array", 400)
    if len(checks) > MAX_VALIDATION_CHECKS:
        return None, (f"Too many validation checks; limit is {MAX_VALIDATION_CHECKS}", 400)

    sanitized_checks = []
    for check in checks:
        if not isinstance(check, dict):
            return None, ("Each validation check must be an object", 400)
        label = _clean_text(check.get("label", ""), max_length=160)
        if not label:
            return None, ("Each validation check requires a non-empty 'label'", 400)
        sanitized_checks.append({
            "label": label,
            "expected": _clean_text(check.get("expected", ""), max_length=512),
            "method": _clean_text(check.get("method", ""), max_length=128),
            "status": _clean_text(check.get("status", "pending"), max_length=32) or "pending",
        })

    try:
        open_risks = _clean_text_list(data.get("open_risks", []), limit=MAX_RECONSTRUCTION_LINKS)
    except ValueError:
        return None, ("Validation plan 'open_risks' must be an array", 400)

    return {
        "plan_id": plan_id,
        "target_id": _clean_text(data.get("target_id", ""), max_length=64) or None,
        "title": title,
        "checks": sanitized_checks,
        "open_risks": open_risks,
        "status": _clean_text(data.get("status", "draft"), max_length=32) or "draft",
    }, None


def validate_reconstruction_generate_payload(data):
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, ("Generation payload must be a JSON object", 400)

    target_id = _clean_text(data.get("target_id", ""), max_length=64) or None
    return {"target_id": target_id}, None
