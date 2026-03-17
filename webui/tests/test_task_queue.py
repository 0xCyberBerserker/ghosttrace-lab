import sys
import unittest
from pathlib import Path
from unittest.mock import patch


WEBUI_DIR = Path(__file__).resolve().parents[1]
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

import triage_report  # noqa: E402


class TriageQueueTest(unittest.TestCase):
    def test_queue_triage_report_falls_back_to_local_worker_when_rabbit_disabled(self):
        with patch("triage_report.rabbitmq_enabled", return_value=False), patch(
            "triage_report._run_local_triage_worker", return_value=True
        ) as local_worker:
            queued = triage_report.queue_triage_report("job-1", "sample.exe")

        self.assertTrue(queued)
        local_worker.assert_called_once_with("job-1", "sample.exe")

    def test_queue_triage_report_publishes_when_rabbit_enabled(self):
        with patch("triage_report.rabbitmq_enabled", return_value=True), patch(
            "triage_report.publish_json", return_value=True
        ) as publish:
            queued = triage_report.queue_triage_report("job-1", "sample.exe")

        self.assertTrue(queued)
        publish.assert_called_once_with(
            triage_report.RABBITMQ_TRIAGE_QUEUE,
            {"job_id": "job-1", "filename": "sample.exe"},
        )


if __name__ == "__main__":
    unittest.main()
