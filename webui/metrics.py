import json
import os
from pathlib import Path

import pika
import requests


def _service_probe(name: str, url: str | None, timeout: int = 5) -> dict:
    if not url:
        return {"name": name, "status": "unconfigured"}
    try:
        response = requests.get(url, timeout=timeout)
        payload = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return {
            "name": name,
            "status": "ok" if response.status_code < 500 else "error",
            "http_status": response.status_code,
            "details": payload,
        }
    except requests.exceptions.RequestException as error:
        return {"name": name, "status": "error", "error": str(error)}


def _triage_stats(triage_report_dir: Path) -> dict:
    stats = {"completed": 0, "processing": 0, "other": 0}
    if not triage_report_dir.exists():
        return stats

    for path in triage_report_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["other"] += 1
            continue
        status = payload.get("status")
        if status == "completed":
            stats["completed"] += 1
        elif status == "processing":
            stats["processing"] += 1
        else:
            stats["other"] += 1
    return stats


def _rabbitmq_queue_stats() -> dict:
    rabbitmq_url = os.getenv("RABBITMQ_URL", "").strip()
    queue_names = {
        "triage": os.getenv("RABBITMQ_TRIAGE_QUEUE", "ghosttrace.triage"),
        "sandbox_run": os.getenv("RABBITMQ_SANDBOX_QUEUE", "ghosttrace.sandbox.run"),
        "x64dbg_requests": os.getenv("RABBITMQ_X64DBG_QUEUE", "ghosttrace.x64dbg.requests"),
    }
    if not rabbitmq_url:
        return {
            queue_key: {"name": queue_name, "status": "disabled", "messages": 0, "consumers": 0}
            for queue_key, queue_name in queue_names.items()
        }

    connection = None
    try:
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        queue_stats = {}
        for queue_key, queue_name in queue_names.items():
            result = channel.queue_declare(queue=queue_name, durable=True, passive=True)
            queue_stats[queue_key] = {
                "name": queue_name,
                "status": "ok",
                "messages": result.method.message_count,
                "consumers": result.method.consumer_count,
            }
        return queue_stats
    except Exception as error:
        return {
            queue_key: {
                "name": queue_name,
                "status": "error",
                "messages": 0,
                "consumers": 0,
                "error": str(error),
            }
            for queue_key, queue_name in queue_names.items()
        }
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def build_metrics_summary(job_store, triage_report_dir: Path) -> dict:
    metadata = job_store.load_job_metadata()
    evidence_jobs = 0
    for job_id in metadata:
        payload = job_store.load_dynamic_evidence(job_id)
        if payload.get("artifacts"):
            evidence_jobs += 1

    triage_stats = _triage_stats(triage_report_dir)
    queue_stats = _rabbitmq_queue_stats()
    services = {
        "ghidraaas": _service_probe("ghidraaas", os.getenv("GHIDRAAAS_METRICS_URL") or f"{os.getenv('GHIDRAAAS_BASE', '').rsplit('/ghidra/api', 1)[0]}/ghidra/api/projects"),
        "sandbox_runner": _service_probe("sandbox_runner", f"{os.getenv('SANDBOX_RUNNER_URL', '').rstrip('/')}/health" if os.getenv("SANDBOX_RUNNER_URL") else None),
        "ollama": _service_probe("ollama", f"{os.getenv('API_BASE', '').rsplit('/v1', 1)[0]}/api/tags" if os.getenv("API_BASE") else None),
    }

    return {
        "jobs": {
            "total": len(metadata),
            "archived": sum(1 for entry in metadata.values() if entry.get("archived")),
            "active": sum(1 for entry in metadata.values() if not entry.get("archived")),
            "with_dynamic_evidence": evidence_jobs,
        },
        "triage": triage_stats,
        "queues": queue_stats,
        "runtime": {
            "rabbitmq_enabled": bool(os.getenv("RABBITMQ_URL")),
            "sandbox_configured": bool(os.getenv("SANDBOX_RUNNER_URL")),
            "operator_auth_enabled": bool(os.getenv("OPERATOR_USERNAME") and os.getenv("OPERATOR_PASSWORD")),
        },
        "services": services,
    }


def build_prometheus_metrics(summary: dict) -> str:
    lines = [
        "# HELP ghosttrace_jobs_total Total jobs tracked by GhostTrace",
        "# TYPE ghosttrace_jobs_total gauge",
        f"ghosttrace_jobs_total {summary['jobs']['total']}",
        "# HELP ghosttrace_jobs_archived Archived jobs tracked by GhostTrace",
        "# TYPE ghosttrace_jobs_archived gauge",
        f"ghosttrace_jobs_archived {summary['jobs']['archived']}",
        "# HELP ghosttrace_jobs_with_dynamic_evidence Jobs with dynamic evidence",
        "# TYPE ghosttrace_jobs_with_dynamic_evidence gauge",
        f"ghosttrace_jobs_with_dynamic_evidence {summary['jobs']['with_dynamic_evidence']}",
        "# HELP ghosttrace_triage_completed Completed triage reports",
        "# TYPE ghosttrace_triage_completed gauge",
        f"ghosttrace_triage_completed {summary['triage']['completed']}",
        "# HELP ghosttrace_triage_processing Processing triage reports",
        "# TYPE ghosttrace_triage_processing gauge",
        f"ghosttrace_triage_processing {summary['triage']['processing']}",
        "# HELP ghosttrace_runtime_feature Runtime feature toggles",
        "# TYPE ghosttrace_runtime_feature gauge",
        f"ghosttrace_runtime_feature{{name=\"rabbitmq_enabled\"}} {1 if summary['runtime']['rabbitmq_enabled'] else 0}",
        f"ghosttrace_runtime_feature{{name=\"sandbox_configured\"}} {1 if summary['runtime']['sandbox_configured'] else 0}",
        f"ghosttrace_runtime_feature{{name=\"operator_auth_enabled\"}} {1 if summary['runtime']['operator_auth_enabled'] else 0}",
    ]

    for service_name, payload in summary["services"].items():
        value = 1 if payload.get("status") == "ok" else 0
        lines.append(f"ghosttrace_service_up{{service=\"{service_name}\"}} {value}")
    lines.extend([
        "# HELP ghosttrace_queue_messages Messages ready in GhostTrace queues",
        "# TYPE ghosttrace_queue_messages gauge",
    ])
    for queue_name, payload in summary.get("queues", {}).items():
        lines.append(f"ghosttrace_queue_messages{{queue=\"{queue_name}\"}} {payload.get('messages', 0)}")
    lines.extend([
        "# HELP ghosttrace_queue_consumers Consumers attached to GhostTrace queues",
        "# TYPE ghosttrace_queue_consumers gauge",
    ])
    for queue_name, payload in summary.get("queues", {}).items():
        lines.append(f"ghosttrace_queue_consumers{{queue=\"{queue_name}\"}} {payload.get('consumers', 0)}")

    return "\n".join(lines) + "\n"
