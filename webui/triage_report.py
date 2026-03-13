import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from openai import OpenAI


GHIDRAAAS_BASE = os.getenv("GHIDRAAAS_BASE", "http://localhost:8080/ghidra/api")
DYNAMIC_EVIDENCE_DIR = Path(os.getenv("DYNAMIC_EVIDENCE_DIR", "/app/data/dynamic_evidence"))
TRIAGE_REPORT_DIR = Path(os.getenv("TRIAGE_REPORT_DIR", "/app/data/triage_reports"))
API_BASE = os.getenv("API_BASE")
API_KEY = os.getenv("API_KEY", "ollama")
MODEL_NAME = os.getenv("MODEL_NAME")
TRIAGE_USE_LLM = os.getenv("TRIAGE_USE_LLM", "0").lower() in {"1", "true", "yes", "on"}

_jobs_in_progress = set()
_jobs_lock = threading.Lock()

CAPABILITY_RULES = {
    "process_execution": ["CreateProcess", "WinExec", "ShellExecute", "TerminateProcess", "Process32First", "Process32Next"],
    "filesystem": ["CreateFile", "WriteFile", "CopyFile", "MoveFile", "DeleteFile", "FindFirstFile", "FindNextFile", "CreateDirectory", "RemoveDirectory", "GetTempPath"],
    "registry": ["RegOpenKey", "RegCreateKey", "RegSetValue", "RegQueryValue", "RegDeleteValue", "RegDeleteKey"],
    "networking": ["InternetOpen", "InternetConnect", "HttpSendRequest", "URLDownloadToFile", "WinHttp", "WSA", "socket", "connect", "recv", "send", "Dns"],
    "services": ["CreateService", "OpenSCManager", "StartService", "ControlService"],
    "crypto": ["Crypt", "BCrypt", "NCrypt", "Cert", "MD5", "SHA", "AES", "RSA"],
    "anti_analysis": ["IsDebuggerPresent", "CheckRemoteDebuggerPresent", "OutputDebugString", "NtQueryInformationProcess", "QueryPerformanceCounter"],
    "installer_update": ["Msi", "msiexec", "Prereq", "Update", "Download", "Azure Key Vault"],
}

STRING_PATTERNS = [
    ("urls", re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)),
    ("registry_paths", re.compile(r"(Software|SOFTWARE|SYSTEM)\\[^\r\n\"']+", re.IGNORECASE)),
    ("powershell_commands", re.compile(r"powershell(?:\.exe)?", re.IGNORECASE)),
    ("command_shell", re.compile(r"(cmd\.exe|@echo off|timeout\.exe|attrib\.exe)", re.IGNORECASE)),
    ("temp_or_programdata", re.compile(r"(ProgramData|AppData|Temp|RunOnce|Uninstall)", re.IGNORECASE)),
    ("cloud_or_secrets", re.compile(r"(Azure Key Vault|token|password|proxy server)", re.IGNORECASE)),
    ("package_installation", re.compile(r"(\.msi|\.msix|Add-AppxPackage|Prereq|installer|setup)", re.IGNORECASE)),
]

BORING_FUNCTION_PREFIXES = ("FUN_", "Unwind@", "Catch@")


def _ensure_report_dir() -> None:
    TRIAGE_REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _report_json_path(job_id: str) -> Path:
    return TRIAGE_REPORT_DIR / f"{job_id}.json"


def _report_md_path(job_id: str) -> Path:
    return TRIAGE_REPORT_DIR / f"{job_id}.md"


def _parse_response(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text.strip()}


def _ghidra_get(path: str, timeout: int = 120) -> Dict[str, Any]:
    response = requests.get(f"{GHIDRAAAS_BASE}/{path}", timeout=timeout)
    payload = _parse_response(response)
    if response.status_code == 202:
        payload.setdefault("status", "processing")
        return payload
    response.raise_for_status()
    return payload


def _load_dynamic_evidence(job_id: str) -> Dict[str, Any]:
    evidence_path = DYNAMIC_EVIDENCE_DIR / f"{job_id}.json"
    if not evidence_path.exists():
        return {"job_id": job_id, "artifacts": []}
    try:
        return json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"job_id": job_id, "artifacts": []}


def _interesting_imports(import_payload: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    imports_by_library = import_payload.get("imports_by_library", {})
    interesting_imports = []
    capabilities = set()

    for _, imports in imports_by_library.items():
        for entry in imports:
            name = entry.get("name", "")
            for capability, patterns in CAPABILITY_RULES.items():
                if any(pattern.lower() in name.lower() for pattern in patterns):
                    capabilities.add(capability)
                    interesting_imports.append(name)
                    break

    deduped_imports = []
    seen = set()
    for name in interesting_imports:
        if name not in seen:
            seen.add(name)
            deduped_imports.append(name)

    return deduped_imports[:30], sorted(capabilities)


def _interesting_strings(strings_payload: Dict[str, Any]) -> Dict[str, List[str]]:
    grouped = {key: [] for key, _ in STRING_PATTERNS}
    for entry in strings_payload.get("strings", []):
        value = entry.get("value", "").strip()
        if len(value) < 8:
            continue
        for label, pattern in STRING_PATTERNS:
            if pattern.search(value):
                if value not in grouped[label]:
                    grouped[label].append(value)
                break

    return {label: values[:15] for label, values in grouped.items() if values}


def _priority_functions(functions_payload: Dict[str, Any], interesting_imports: List[str]) -> List[Dict[str, str]]:
    functions = functions_payload.get("functions_list", {})
    import_keywords = []
    for import_name in interesting_imports:
        short_name = import_name.split("::")[-1]
        import_keywords.append(short_name.lower())

    selected = []

    for address, name in functions.items():
        lowered = name.lower()
        if not name.startswith(BORING_FUNCTION_PREFIXES):
            selected.append({"address": address, "name": name, "reason": "named_symbol"})
            if len(selected) >= 12:
                return selected

        if any(keyword and keyword in lowered for keyword in import_keywords[:12]):
            selected.append({"address": address, "name": name, "reason": "matches_import_keyword"})
            if len(selected) >= 12:
                return selected

    fallback = []
    for address, name in functions.items():
        if name.startswith("FUN_"):
            fallback.append({"address": address, "name": name, "reason": "unnamed_function"})
        if len(fallback) >= 8:
            break

    return (selected + fallback)[:12]


def _summarize_dynamic_evidence(payload: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = payload.get("artifacts", [])
    artifact_types = {}
    highlights = []
    for artifact in artifacts:
        artifact_type = artifact.get("type", "unknown")
        artifact_types[artifact_type] = artifact_types.get(artifact_type, 0) + 1
        highlights.extend(artifact.get("highlights", []))
    return {
        "artifact_count": len(artifacts),
        "artifact_types": artifact_types,
        "highlights": highlights[:20],
    }


def _build_triage_input(job_id: str, filename: str | None) -> Dict[str, Any]:
    imports_payload = _ghidra_get(f"get_imports_list/{job_id}")
    strings_payload = _ghidra_get(f"get_strings_list/{job_id}")
    functions_payload = _ghidra_get(f"get_functions_list/{job_id}")

    processing = []
    for name, payload in (
        ("imports", imports_payload),
        ("strings", strings_payload),
        ("functions", functions_payload),
    ):
        if payload.get("status") == "processing":
            processing.append(name)

    if processing:
        return {"status": "processing", "job_id": job_id, "processing": processing}

    interesting_imports, capabilities = _interesting_imports(imports_payload)
    interesting_strings = _interesting_strings(strings_payload)
    priority_functions = _priority_functions(functions_payload, interesting_imports)
    dynamic_evidence = _load_dynamic_evidence(job_id)
    dynamic_summary = _summarize_dynamic_evidence(dynamic_evidence)

    return {
        "status": "ready",
        "job_id": job_id,
        "filename": filename,
        "capabilities": capabilities,
        "imports_summary": {
            "library_count": imports_payload.get("library_count", 0),
            "import_count": imports_payload.get("import_count", 0),
            "libraries": imports_payload.get("libraries", [])[:20],
            "interesting_imports": interesting_imports,
        },
        "strings_summary": {
            "string_count": strings_payload.get("string_count", 0),
            "interesting_strings": interesting_strings,
        },
        "functions_summary": {
            "function_count": len(functions_payload.get("functions_list", {})),
            "priority_functions": priority_functions,
        },
        "dynamic_summary": dynamic_summary,
    }


def _fallback_markdown(summary: Dict[str, Any]) -> str:
    filename = summary.get("filename") or "Unknown filename"
    capabilities = summary.get("capabilities", [])
    imports_summary = summary.get("imports_summary", {})
    strings_summary = summary.get("strings_summary", {})
    functions_summary = summary.get("functions_summary", {})
    dynamic_summary = summary.get("dynamic_summary", {})

    lines = [
        f"# Auto Triage Report: {filename}",
        "",
        "## Executive Summary",
        f"- Static evidence suggests the sample is primarily associated with: {', '.join(capabilities) or 'general installer or utility behavior'}.",
        f"- Imports analyzed: {imports_summary.get('import_count', 0)} across {imports_summary.get('library_count', 0)} libraries.",
        f"- Strings extracted: {strings_summary.get('string_count', 0)}.",
        f"- Dynamic artifacts available: {dynamic_summary.get('artifact_count', 0)}.",
        "",
        "## Evidence Labels",
        "- `static evidence`: directly observed in imports, strings, or function metadata.",
        "- `dynamic evidence`: directly observed in uploaded sandbox or telemetry artifacts.",
        "- `inference`: analyst-facing hypothesis derived from the previous two categories.",
        "",
        "## Capabilities",
    ]

    for capability in capabilities[:10]:
        lines.append(f"- `static evidence` {capability}")

    lines.extend([
        "",
        "## Notable Imports",
    ])
    for entry in imports_summary.get("interesting_imports", [])[:15]:
        lines.append(f"- `static evidence` `{entry}`")

    lines.extend([
        "",
        "## Notable Strings",
    ])
    for category, values in strings_summary.get("interesting_strings", {}).items():
        if not values:
            continue
        lines.append(f"- `static evidence` {category}: `{values[0][:140]}`")

    lines.extend([
        "",
        "## Priority Functions",
    ])
    for function in functions_summary.get("priority_functions", [])[:10]:
        lines.append(f"- `static evidence` `{function['name']}` at `{function['address']}`")

    lines.extend([
        "",
        "## Dynamic Evidence",
        f"- `dynamic evidence` artifact count: {dynamic_summary.get('artifact_count', 0)}",
    ])
    for highlight in dynamic_summary.get("highlights", [])[:8]:
        lines.append(f"- `dynamic evidence` {highlight}")

    lines.extend([
        "",
        "## Recommended Next Steps",
        "- `inference` Decompile the listed priority functions and look for installer, update, registry, or network paths.",
        "- `inference` Correlate any Procmon or network artifacts with the strings and imports already extracted.",
        "- `inference` Prioritize functions that touch process creation, file writes, and package management behavior.",
    ])

    return "\n".join(lines)


def _llm_markdown(summary: Dict[str, Any]) -> str:
    if not TRIAGE_USE_LLM or not API_BASE or not MODEL_NAME:
        return _fallback_markdown(summary)

    client = OpenAI(base_url=API_BASE, api_key=API_KEY)
    prompt = (
        "You are generating an evidence-grounded reverse-engineering triage report.\n"
        "Use these labels literally in the report: `static evidence`, `dynamic evidence`, `inference`.\n"
        "Keep the report concise and analyst-friendly.\n"
        "Sections required: Executive Summary, Capabilities, Notable Imports, Notable Strings, Priority Functions, Dynamic Evidence, Recommended Next Steps.\n"
        "Do not claim runtime behavior unless it appears in dynamic evidence.\n"
        "Input summary JSON follows.\n\n"
        f"{json.dumps(summary, ensure_ascii=True)}"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Produce a Markdown reverse-engineering triage report."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        return content.strip() or _fallback_markdown(summary)
    except Exception:
        return _fallback_markdown(summary)


def _write_report(job_id: str, report_json: Dict[str, Any], markdown: str) -> None:
    _ensure_report_dir()
    _report_json_path(job_id).write_text(json.dumps(report_json, indent=2), encoding="utf-8")
    _report_md_path(job_id).write_text(markdown, encoding="utf-8")


def generate_triage_report(job_id: str, filename: str | None = None) -> Dict[str, Any]:
    _ensure_report_dir()
    _write_report(
        job_id,
        {"job_id": job_id, "filename": filename, "status": "processing"},
        "",
    )
    summary = _build_triage_input(job_id, filename)

    if summary.get("status") == "processing":
        report_json = {
            "job_id": job_id,
            "filename": filename,
            "status": "processing",
            "processing": summary.get("processing", []),
        }
        _write_report(job_id, report_json, "")
        return report_json

    markdown = _llm_markdown(summary)
    report_json = {
        "job_id": job_id,
        "filename": filename,
        "status": "completed",
        "summary": summary,
        "markdown_path": str(_report_md_path(job_id)),
    }
    _write_report(job_id, report_json, markdown)
    return report_json


def queue_triage_report(job_id: str, filename: str | None = None) -> bool:
    with _jobs_lock:
        if job_id in _jobs_in_progress:
            return False
        _jobs_in_progress.add(job_id)

    def worker() -> None:
        try:
            generate_triage_report(job_id, filename)
        finally:
            with _jobs_lock:
                _jobs_in_progress.discard(job_id)

    threading.Thread(target=worker, daemon=True).start()
    return True


def get_cached_triage_report(job_id: str) -> Dict[str, Any] | None:
    json_path = _report_json_path(job_id)
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    md_path = _report_md_path(job_id)
    payload["markdown"] = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    return payload
