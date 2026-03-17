import hashlib
import json


def build_assistant_next_steps(job_id, job_store, triage_report, x64dbg_snapshot):
    metadata_entry = job_store.load_job_metadata().get(job_id, {})
    if not isinstance(metadata_entry, dict):
        metadata_entry = {"filename": str(metadata_entry)}

    filename = metadata_entry.get("label") or metadata_entry.get("filename") or f"{job_id[:8]}.bin"
    evidence = job_store.load_dynamic_evidence(job_id)
    evidence_summary = job_store.summarize_evidence(evidence)
    x64dbg_state = x64dbg_snapshot.get("state", {})
    x64dbg_findings = x64dbg_snapshot.get("findings", {}).get("findings", [])
    x64dbg_requests = x64dbg_snapshot.get("requests", {}).get("requests", [])

    summary = {
        "triage_status": (triage_report or {}).get("status", "missing"),
        "dynamic_artifacts": evidence_summary.get("artifact_count", 0),
        "x64dbg_status": x64dbg_state.get("status", "idle"),
        "x64dbg_findings": len(x64dbg_findings),
        "x64dbg_requests": len(x64dbg_requests),
    }

    capabilities = []
    if triage_report and triage_report.get("status") == "completed":
        capabilities = triage_report.get("summary", {}).get("capabilities", [])

    suggestions = []
    stage = "analysis"
    stage_headline = "Static analysis is the current focus."
    stage_copy = "Use the report, imports, strings, and function list to build the first explanation of the target."
    alerts = []

    if not triage_report or triage_report.get("status") in {"processing", "queued"}:
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
