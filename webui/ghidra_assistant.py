# Biniam Demissie
# 09/29/2025
import os
import json
import time
import requests
from pathlib import Path
from typing import Dict, Any, Generator
from openai import OpenAI

GHIDRAAAS_BASE = os.getenv("GHIDRAAAS_BASE", "http://localhost:8080/ghidra/api")
DYNAMIC_EVIDENCE_DIR = Path(os.getenv("DYNAMIC_EVIDENCE_DIR", "/app/data/dynamic_evidence"))
WEBUI_BASE = os.getenv("WEBUI_BASE", "http://localhost:5000")

SYSTEM_PROMPT = """You are a helpful reverse engineering assistant operating on a binary identified by job_id.

Follow a pragmatic workflow inspired by common reverse engineering practice:
1. Start with static triage: capabilities, likely purpose, suspicious clusters of behavior.
2. Use imports as a fast capability signal for filesystem, process, registry, service, crypto, and network behavior.
3. Use discovered strings to identify URLs, paths, mutexes, config markers, product branding, and feature toggles.
4. Use function lists to identify promising paths, then decompile only the most relevant functions.
5. If dynamic evidence artifacts are available, correlate them with the static findings and call out matches and mismatches.
6. If x64dbg debugging context is available, use it to ground live-debug conclusions and separate them from static-only hypotheses.
7. Clearly label when a conclusion is an inference from static evidence rather than a confirmed runtime behavior.

You do not execute unknown binaries yourself in this environment. Dynamic conclusions must come from uploaded sandbox or telemetry artifacts rather than fresh execution.
Format the final response in Markdown."""
TURNS = 5 

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_functions",
            "description": "Retrieve the list of discovered functions for a job.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_imports",
            "description": "Retrieve imported APIs grouped by library for a job.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_strings",
            "description": "Retrieve extracted strings for a job.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dynamic_evidence",
            "description": "Retrieve uploaded dynamic evidence artifacts and summary for a job.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decompile_function",
            "description": "Get decompiled pseudocode for a function at a given address.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}, "addr": {"type": "string"}},
                "required": ["job_id", "addr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_x64dbg_state",
            "description": "Retrieve the current x64dbg MCP session state for a job.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_x64dbg_findings",
            "description": "Retrieve stored x64dbg MCP findings captured during debugging.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "queue_x64dbg_request",
            "description": "Queue a debugging request for the x64dbg MCP bridge, such as setting a breakpoint or inspecting an address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "action": {"type": "string"},
                    "notes": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["job_id", "action"],
            },
        },
    },
]

TOOL_INTENT_DESCRIPTIONS = {
    "list_functions": "Listing analyzed functions from Ghidraaas.",
    "list_imports": "Inspecting imported APIs and libraries via Ghidraaas.",
    "list_strings": "Extracting strings and textual indicators via Ghidraaas.",
    "get_dynamic_evidence": "Correlating uploaded dynamic evidence artifacts.",
    "decompile_function": "Decompiling a specific function via Ghidraaas.",
    "get_x64dbg_state": "Checking the current x64dbg MCP session state.",
    "list_x64dbg_findings": "Reviewing findings captured through x64dbg MCP.",
    "queue_x64dbg_request": "Queuing a new x64dbg MCP debugging request.",
}

TOOL_ACTIVE_MESSAGES = {
    "list_functions": "Scanning the cached function index for this target.",
    "list_imports": "Reading the binary's imported libraries and APIs.",
    "list_strings": "Reading extracted strings and text indicators.",
    "get_dynamic_evidence": "Loading sandbox and telemetry artifacts for correlation.",
    "decompile_function": "Opening a function body and preparing pseudocode.",
    "get_x64dbg_state": "Reading the live debugger bridge state for this target.",
    "list_x64dbg_findings": "Loading debugger findings captured from x64dbg MCP.",
    "queue_x64dbg_request": "Submitting a new debugger task to the x64dbg bridge.",
}

TOOL_READY_MESSAGES = {
    "list_functions": "Function index loaded from cache.",
    "list_imports": "Import table loaded from cache.",
    "list_strings": "Strings list loaded from cache.",
    "get_dynamic_evidence": "Dynamic evidence loaded.",
    "decompile_function": "Decompilation ready from cache.",
    "get_x64dbg_state": "x64dbg MCP session state loaded.",
    "list_x64dbg_findings": "x64dbg findings loaded.",
    "queue_x64dbg_request": "x64dbg debugging request queued.",
}

PROCESSING_STATUS_MESSAGES = {
    "list_functions": "The function index is still being generated by Ghidra. Try the same request again in a little while.",
    "list_imports": "The import table is still being generated by Ghidra. Try again shortly.",
    "list_strings": "The strings list is still being generated by Ghidra. Try again shortly.",
    "decompile_function": "The decompilation backend is still preparing data for this sample. Try again shortly.",
}

PROCESSING_PROGRESS_MESSAGES = {
    "list_functions": "Indexing functions from the analyzed project.",
    "list_imports": "Extracting imported APIs and library references.",
    "list_strings": "Extracting strings and textual indicators from the analyzed project.",
    "decompile_function": "Decompiling the selected function and warming the cache.",
}

PROCESSING_READY_MESSAGES = {
    "list_functions": "Function index ready.",
    "list_imports": "Import table ready.",
    "list_strings": "Strings list ready.",
    "decompile_function": "Decompilation ready and cached.",
}
PROCESSING_RETRY_ATTEMPTS = 4
PROCESSING_RETRY_DELAY_SECONDS = 5


def _parse_response(response: requests.Response) -> Dict[str, Any]:
    text = response.text.strip()
    try:
        return response.json()
    except ValueError:
        return {"raw": text}


def _ghidra_get(path: str, timeout: int = 600) -> Dict[str, Any]:
    try:
        response = requests.get(f"{GHIDRAAAS_BASE}/{path}", timeout=timeout)
        payload = _parse_response(response)
        if response.ok:
            return payload
        return {
            "error": {
                "status_code": response.status_code,
                "message": response.text.strip()[:1000] or "Empty response from Ghidraaas",
                "payload": payload,
            }
        }
    except requests.exceptions.RequestException as e:
        return {"error": {"message": str(e)}}


def list_functions(job_id: str) -> Dict[str, Any]:
    return _ghidra_get(f"get_functions_list/{job_id}")


def list_imports(job_id: str) -> Dict[str, Any]:
    return _ghidra_get(f"get_imports_list/{job_id}")


def list_strings(job_id: str) -> Dict[str, Any]:
    return _ghidra_get(f"get_strings_list/{job_id}")


def get_dynamic_evidence(job_id: str) -> Dict[str, Any]:
    evidence_path = DYNAMIC_EVIDENCE_DIR / f"{job_id}.json"
    if not evidence_path.exists():
        return {
            "job_id": job_id,
            "artifacts": [],
            "summary": {
                "artifact_count": 0,
                "artifact_types": {},
                "highlight_count": 0,
                "highlights": [],
            },
        }

    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        payload.setdefault("job_id", job_id)
        artifacts = payload.get("artifacts", [])
        artifact_types = {}
        highlights = []
        for artifact in artifacts:
            artifact_type = artifact.get("type", "unknown")
            artifact_types[artifact_type] = artifact_types.get(artifact_type, 0) + 1
            highlights.extend(artifact.get("highlights", []))
        payload["summary"] = {
            "artifact_count": len(artifacts),
            "artifact_types": artifact_types,
            "highlight_count": len(highlights),
            "highlights": highlights[:30],
        }
        return payload
    except (OSError, json.JSONDecodeError) as e:
        return {"error": {"message": str(e)}}


def _webui_get(path: str, timeout: int = 60) -> Dict[str, Any]:
    try:
        response = requests.get(f"{WEBUI_BASE.rstrip('/')}{path}", timeout=timeout)
        payload = _parse_response(response)
        if response.ok:
            return payload
        return {
            "error": {
                "status_code": response.status_code,
                "message": response.text.strip()[:1000] or "Empty response from webui bridge",
                "payload": payload,
            }
        }
    except requests.exceptions.RequestException as e:
        return {"error": {"message": str(e)}}


def _webui_post(path: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    try:
        response = requests.post(f"{WEBUI_BASE.rstrip('/')}{path}", json=payload, timeout=timeout)
        response_payload = _parse_response(response)
        if response.ok:
            return response_payload
        return {
            "error": {
                "status_code": response.status_code,
                "message": response.text.strip()[:1000] or "Empty response from webui bridge",
                "payload": response_payload,
            }
        }
    except requests.exceptions.RequestException as e:
        return {"error": {"message": str(e)}}


def get_x64dbg_state(job_id: str) -> Dict[str, Any]:
    return _webui_get(f"/debug/x64dbg/{job_id}")


def list_x64dbg_findings(job_id: str) -> Dict[str, Any]:
    return _webui_get(f"/debug/x64dbg/{job_id}/findings")


def queue_x64dbg_request(job_id: str, action: str, notes: str = "", address: str | None = None) -> Dict[str, Any]:
    payload = {
        "action": action,
        "notes": notes,
    }
    if address:
        payload["address"] = address
    return _webui_post(f"/debug/x64dbg/{job_id}/requests", payload)


def decompile_function(job_id: str, addr: str) -> Dict[str, Any]:
    return _ghidra_get(f"get_decompiled_function/{job_id}/{addr}")


def _retry_processing_result(function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if function_name == "list_functions":
        retried_result = list_functions(args["job_id"])
    elif function_name == "list_imports":
        retried_result = list_imports(args["job_id"])
    elif function_name == "list_strings":
        retried_result = list_strings(args["job_id"])
    elif function_name == "decompile_function":
        retried_result = decompile_function(args["job_id"], args["addr"])
    else:
        return {"status": "processing"}
    return retried_result

class GhidraAssistant:
    def __init__(self):
        base_url = os.getenv("API_BASE")
        model_name = os.getenv("MODEL_NAME")
        if not base_url:
            raise RuntimeError("API_BASE is not configured for the OpenAI-compatible client.")
        if not model_name:
            raise RuntimeError("MODEL_NAME is not configured for the OpenAI-compatible client.")

        # OpenAI compatible client
        self.client = OpenAI(
           base_url=base_url,
           api_key=os.getenv("API_KEY", "not-used")
        )
        self.model = model_name

        self.available_tools = {
            "list_functions": lambda **kwargs: list_functions(kwargs["job_id"]),
            "list_imports": lambda **kwargs: list_imports(kwargs["job_id"]),
            "list_strings": lambda **kwargs: list_strings(kwargs["job_id"]),
            "get_dynamic_evidence": lambda **kwargs: get_dynamic_evidence(kwargs["job_id"]),
            "decompile_function": lambda **kwargs: decompile_function(kwargs["job_id"], kwargs["addr"]),
            "get_x64dbg_state": lambda **kwargs: get_x64dbg_state(kwargs["job_id"]),
            "list_x64dbg_findings": lambda **kwargs: list_x64dbg_findings(kwargs["job_id"]),
            "queue_x64dbg_request": lambda **kwargs: queue_x64dbg_request(
                kwargs["job_id"],
                kwargs["action"],
                kwargs.get("notes", ""),
                kwargs.get("address"),
            ),
        }
        
    def chat_completion_stream(self, user_message: str, job_id: str) -> Generator[str, None, None]:
        contextual_message = f"For job_id '{job_id}', {user_message}"
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": contextual_message}
        ]

        for i in range(TURNS):
            try:
                first_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto"
                )
            except Exception as exc:
                raise RuntimeError(f"LLM tool-planning request failed: {exc}") from exc
            message = first_response.choices[0].message
            messages.append(message)
            
            if not message.tool_calls:
                break            

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    if function_name in self.available_tools:
                        
                        intent_description = TOOL_INTENT_DESCRIPTIONS.get(function_name, f"Executing tool: {function_name}...")
                        yield json.dumps({"type": "tool_call", "description": intent_description})
                        yield json.dumps({
                            "type": "tool_state",
                            "state": "active",
                            "content": TOOL_ACTIVE_MESSAGES.get(function_name, intent_description),
                        })
                        

                        function_to_call = self.available_tools[function_name]
                        args = json.loads(tool_call.function.arguments)
                        if 'job_id' not in args:
                            args['job_id'] = job_id
                            
                        result = function_to_call(**args)
                        if result.get("status") == "processing":
                            yield json.dumps({
                                "type": "processing_status",
                                "state": "start",
                                "content": PROCESSING_PROGRESS_MESSAGES.get(
                                    function_name,
                                    "Ghidra is still preparing analysis artifacts.",
                                ),
                            })
                            yield json.dumps({
                                "type": "tool_call",
                                "description": "Ghidra is still building analysis artifacts. Waiting for the index to become available.",
                            })
                            for _ in range(PROCESSING_RETRY_ATTEMPTS):
                                time.sleep(PROCESSING_RETRY_DELAY_SECONDS)
                                result = _retry_processing_result(function_name, args)
                                if result.get("status") != "processing":
                                    break

                            if result.get("status") == "processing":
                                processing_message = PROCESSING_STATUS_MESSAGES.get(
                                    function_name,
                                    "Ghidra is still processing this request. Try again shortly.",
                                )
                                yield json.dumps({
                                    "type": "processing_status",
                                    "state": "end",
                                    "content": processing_message,
                                })
                                yield json.dumps({
                                    "type": "tool_state",
                                    "state": "idle",
                                    "content": processing_message,
                                })
                                yield json.dumps({
                                    "type": "tool_call",
                                    "description": processing_message,
                                })
                                yield json.dumps({
                                    "type": "token",
                                    "content": processing_message,
                                })
                                return
                            yield json.dumps({
                                "type": "processing_status",
                                "state": "end",
                                "content": PROCESSING_READY_MESSAGES.get(
                                    function_name,
                                    "Artifacts ready.",
                                ),
                            })
                            yield json.dumps({
                                "type": "tool_state",
                                "state": "ready",
                                "content": PROCESSING_READY_MESSAGES.get(
                                    function_name,
                                    "Artifacts ready.",
                                ),
                            })
                        else:
                            yield json.dumps({
                                "type": "tool_state",
                                "state": "ready",
                                "content": TOOL_READY_MESSAGES.get(
                                    function_name,
                                    f"{function_name} completed.",
                                ),
                            })
                        
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(result)
                        })

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True
            )
        except Exception as exc:
            raise RuntimeError(f"LLM streaming request failed: {exc}") from exc

        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield json.dumps({"type": "token", "content": content})
