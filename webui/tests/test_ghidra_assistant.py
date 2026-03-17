import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

WEBUI_DIR = Path(__file__).resolve().parents[1]
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

import ghidra_assistant


def _chunk(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise Exception(
                "Error code: 400 - {'error': {'message': 'registry.ollama.ai/Godmoded/llama3-lexi-uncensored:latest does not support tools', 'type': 'invalid_request_error'}}"
            )
        if kwargs.get("stream"):
            return [_chunk("Fallback answer from cached context.")]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Fallback answer from cached context."))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


class GhidraAssistantFallbackTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "API_BASE": "http://ollama:11434/v1",
            "MODEL_NAME": "Godmoded/llama3-lexi-uncensored:latest",
            "API_KEY": "not-used",
        },
        clear=False,
    )
    @patch.object(ghidra_assistant, "OpenAI", autospec=True)
    @patch.object(ghidra_assistant, "list_x64dbg_findings", autospec=True)
    @patch.object(ghidra_assistant, "get_x64dbg_state", autospec=True)
    @patch.object(ghidra_assistant, "get_dynamic_evidence", autospec=True)
    @patch.object(ghidra_assistant, "_webui_get", autospec=True)
    def test_chat_falls_back_when_model_does_not_support_tools(
        self,
        mock_webui_get,
        mock_dynamic_evidence,
        mock_x64dbg_state,
        mock_x64dbg_findings,
        mock_openai,
    ):
        mock_openai.return_value = _FakeClient()
        mock_webui_get.return_value = {
            "job_id": "job-1",
            "status": "completed",
            "markdown": "# Auto Triage Report\n\n- Capability: filesystem\n- Capability: process_execution",
        }
        mock_dynamic_evidence.return_value = {
            "summary": {
                "artifact_count": 0,
                "artifact_types": {},
                "highlight_count": 0,
                "highlights": [],
            }
        }
        mock_x64dbg_state.return_value = {"status": "bridge-online"}
        mock_x64dbg_findings.return_value = {"findings": []}

        assistant = ghidra_assistant.GhidraAssistant()
        events = [json.loads(chunk) for chunk in assistant.chat_completion_stream("Summarize the sample.", "job-1")]

        self.assertEqual(events[0]["type"], "tool_state")
        self.assertIn("cannot use tools", events[0]["content"].lower())
        token_events = [event for event in events if event["type"] == "token"]
        self.assertTrue(token_events)
        self.assertIn("Fallback answer from cached context.", token_events[-1]["content"])


if __name__ == "__main__":
    unittest.main()
