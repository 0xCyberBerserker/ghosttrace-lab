import os
import sys
import tempfile
import unittest
from importlib import reload
from pathlib import Path


RUNNER_DIR = Path(__file__).resolve().parents[1]
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

import app as runner_app  # noqa: E402


class SandboxRunnerAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["INTERNAL_API_TOKEN"] = "shared-secret"
        self.module = reload(runner_app)
        self.module.QUEUE_DIR = Path(self.temp_dir.name) / "queue"
        self.module.SAMPLES_DIR = Path(self.temp_dir.name) / "shared"
        self.module.X64DBG_DIR = Path(self.temp_dir.name) / "queue" / "x64dbg"
        self.module.BRIDGE_DIR = Path(self.temp_dir.name) / "bridge"
        self.client = self.module.app.test_client()

    def tearDown(self):
        os.environ.pop("INTERNAL_API_TOKEN", None)
        self.temp_dir.cleanup()

    def test_run_requires_internal_token_when_configured(self):
        response = self.client.post("/run", json={"job_id": "job-1", "filename": "sample.exe"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "unauthorized")

    def test_run_accepts_valid_internal_token(self):
        response = self.client.post(
            "/run",
            json={"job_id": "job-1", "filename": "sample.exe"},
            headers={"X-Internal-Token": "shared-secret"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["job_id"], "job-1")

    def test_health_includes_request_id_and_service_name(self):
        response = self.client.get("/health", headers={"X-Request-ID": "runner-123"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["service"], "sandbox_runner")
        self.assertEqual(response.headers["X-Request-ID"], "runner-123")


if __name__ == "__main__":
    unittest.main()
