import sys
import unittest
from pathlib import Path
from unittest.mock import patch


WEBUI_DIR = Path(__file__).resolve().parents[1]
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

from sandbox_client import SandboxClient  # noqa: E402


class SandboxClientTest(unittest.TestCase):
    def test_request_includes_internal_token_header(self):
        client = SandboxClient(
            "http://sandbox_runner:9001",
            lambda response: "error",
            auth_token="shared-secret",
        )

        with patch("sandbox_client.requests.request") as request_mock:
            request_mock.return_value.ok = True
            request_mock.return_value.content = b"{}"
            request_mock.return_value.json.return_value = {"status": "ok"}

            payload = client.request("GET", "/jobs/job-1")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            request_mock.call_args.kwargs["headers"]["X-Internal-Token"],
            "shared-secret",
        )

    def test_trigger_run_includes_internal_token_header(self):
        client = SandboxClient(
            "http://sandbox_runner:9001",
            lambda response: "error",
            auth_token="shared-secret",
        )

        with patch("sandbox_client.requests.post") as post_mock:
            client.trigger_run("job-1", "sample.exe")

        self.assertEqual(
            post_mock.call_args.kwargs["headers"]["X-Internal-Token"],
            "shared-secret",
        )


if __name__ == "__main__":
    unittest.main()
