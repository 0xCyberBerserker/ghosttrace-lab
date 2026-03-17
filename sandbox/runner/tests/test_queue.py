import os
import sys
import tempfile
import unittest
from importlib import reload
from pathlib import Path
from unittest.mock import patch


RUNNER_DIR = Path(__file__).resolve().parents[1]
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

import app as runner_app  # noqa: E402


class SandboxRunnerQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ.pop("RABBITMQ_URL", None)
        self.module = reload(runner_app)
        self.module.QUEUE_DIR = Path(self.temp_dir.name) / "queue"
        self.module.SAMPLES_DIR = Path(self.temp_dir.name) / "shared"
        self.module.X64DBG_DIR = Path(self.temp_dir.name) / "queue" / "x64dbg"
        self.module.BRIDGE_DIR = Path(self.temp_dir.name) / "bridge"
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_processes_inline_when_rabbit_disabled(self):
        response = self.client.post("/run", json={"job_id": "job-1", "filename": "sample.exe"})

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["job_id"], "job-1")
        self.assertTrue((self.module.QUEUE_DIR / "job-1.json").exists())

    def test_run_publishes_when_rabbit_enabled(self):
        with patch("app.rabbitmq_enabled", return_value=True), patch("app.publish_json", return_value=True) as publish:
            response = self.client.post("/run", json={"job_id": "job-1", "filename": "sample.exe"})

        self.assertEqual(response.status_code, 202)
        publish.assert_called_once_with(
            self.module.RABBITMQ_SANDBOX_QUEUE,
            {"job_id": "job-1", "filename": "sample.exe"},
        )
        self.assertFalse((self.module.QUEUE_DIR / "job-1.json").exists())

    def test_x64dbg_request_processes_inline_when_rabbit_disabled(self):
        response = self.client.post("/jobs/job-1/x64dbg/requests", json={"action": "trace_api"})

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["request"]["action"], "trace_api")
        requests_path = self.module.X64DBG_DIR / "job-1" / "requests.json"
        self.assertTrue(requests_path.exists())

    def test_x64dbg_request_publishes_when_rabbit_enabled(self):
        with patch("app.rabbitmq_enabled", return_value=True), patch("app.publish_json", return_value=True) as publish:
            response = self.client.post("/jobs/job-1/x64dbg/requests", json={"action": "trace_api"})

        self.assertEqual(response.status_code, 202)
        publish.assert_called_once()
        queue_name, published_payload = publish.call_args.args
        self.assertEqual(queue_name, self.module.RABBITMQ_X64DBG_QUEUE)
        self.assertEqual(published_payload["job_id"], "job-1")
        self.assertEqual(published_payload["request"]["action"], "trace_api")
        requests_path = self.module.X64DBG_DIR / "job-1" / "requests.json"
        self.assertFalse(requests_path.exists())


if __name__ == "__main__":
    unittest.main()
