import os
import sys
import tempfile
import unittest
from base64 import b64encode
from io import BytesIO
from pathlib import Path


WEBUI_DIR = Path(__file__).resolve().parents[1]
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

os.environ.setdefault("API_BASE", "http://localhost:11434/v1")
os.environ.setdefault("MODEL_NAME", "test-model")

import app as webui_app  # noqa: E402
from e2e_fixture import E2EFixture  # noqa: E402
from job_store import JobStore  # noqa: E402
from sandbox_credentials import SandboxCredentialsManager  # noqa: E402


class JobStorePersistenceTest(unittest.TestCase):
    def test_sqlite_store_migrates_legacy_metadata_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            metadata_path = base / "job_metadata.json"
            evidence_dir = base / "dynamic_evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)

            metadata_path.write_text(
                '{"job-1": {"filename": "sample.exe", "label": "Legacy"}, "job-2": "fallback.bin"}',
                encoding="utf-8",
            )
            (evidence_dir / "job-1.json").write_text(
                '{"artifacts": [{"type": "network", "highlights": ["dns"]}]}',
                encoding="utf-8",
            )

            store = JobStore(
                metadata_path=metadata_path,
                uploads_dir=base / "uploads",
                dynamic_evidence_dir=evidence_dir,
                triage_report_dir=base / "triage_reports",
                db_path=base / "ghosttrace.db",
            )

            metadata = store.load_job_metadata()
            evidence = store.load_dynamic_evidence("job-1")

            self.assertEqual(metadata["job-1"]["filename"], "sample.exe")
            self.assertEqual(metadata["job-1"]["label"], "Legacy")
            self.assertEqual(metadata["job-2"]["filename"], "fallback.bin")
            self.assertEqual(evidence["job_id"], "job-1")
            self.assertEqual(evidence["artifacts"][0]["type"], "network")


class FakeGhidraClient:
    def __init__(self):
        self.projects = []
        self.analyze_calls = []
        self.list_projects_error = None

    def list_projects(self, timeout=30):
        if self.list_projects_error is not None:
            raise self.list_projects_error
        return list(self.projects)

    def analyze_sample(self, filename, file_stream, timeout=600):
        self.analyze_calls.append(
            {
                "filename": filename,
                "content": file_stream.read(),
                "timeout": timeout,
            }
        )

        class Response:
            ok = True
            status_code = 200
            text = ""

        return Response()

    def terminate_analysis(self, job_id, timeout=60):
        class Response:
            ok = True
            status_code = 200
            text = ""
        return Response()


class FakeSandboxClient:
    configured = True

    def __init__(self):
        self.calls = []
        self.snapshot = {
            "state": {"status": "idle"},
            "findings": {"findings": []},
            "requests": {"requests": []},
        }

    def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, "kwargs": kwargs})
        if path.endswith("/x64dbg"):
            return {"status": "attached", "transport": "mcp"}
        if path.endswith("/x64dbg/findings"):
            if method == "POST":
                return {"status": "stored"}
            return {"findings": [{"summary": "Breakpoint hit"}]}
        if path.endswith("/x64dbg/requests"):
            if method == "POST":
                return {"status": "queued"}
            return {"requests": [{"action": "trace_api"}]}
        return {"status": "deleted"}

    def trigger_run(self, job_id, filename, timeout=10):
        self.calls.append({"method": "POST", "path": "/run", "kwargs": {"json": {"job_id": job_id, "filename": filename}, "timeout": timeout}})

    def safe_x64dbg_snapshot(self, job_id):
        return self.snapshot


class UnconfiguredSandboxClient(FakeSandboxClient):
    configured = False

    def request(self, method, path, **kwargs):
        raise RuntimeError("SANDBOX_RUNNER_URL is not configured.")


class WebUiRoutesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.original_job_store = webui_app.job_store
        self.original_ghidra_client = webui_app.ghidra_client
        self.original_sandbox_client = webui_app.sandbox_client
        self.original_job_service = webui_app.job_service
        self.original_job_workflow = webui_app.job_workflow
        self.original_reconstruction_service = webui_app.reconstruction_service
        self.original_internal_api_token = webui_app.INTERNAL_API_TOKEN
        self.original_operator_username = webui_app.app.config.get("OPERATOR_USERNAME", "")
        self.original_operator_password = webui_app.app.config.get("OPERATOR_PASSWORD", "")
        self.original_rate_limit_upload = webui_app.app.config.get("RATE_LIMIT_UPLOAD")
        self.original_rate_limit_reveal = webui_app.app.config.get("RATE_LIMIT_REVEAL")
        self.original_windows_sandbox_credentials_path = webui_app.WINDOWS_SANDBOX_CREDENTIALS_PATH
        self.original_sandbox_credentials = webui_app.sandbox_credentials
        self.original_triage_report_dir = webui_app.TRIAGE_REPORT_DIR
        self.original_get_cached_triage_report = webui_app.get_cached_triage_report
        self.original_queue_triage_report = webui_app.queue_triage_report
        self.original_e2e_fixture = webui_app.e2e_fixture

        triage_report_dir = base / "triage_reports"
        webui_app.job_store = JobStore(
            metadata_path=base / "job_metadata.json",
            uploads_dir=base / "uploads",
            dynamic_evidence_dir=base / "dynamic_evidence",
            triage_report_dir=triage_report_dir,
            db_path=base / "ghosttrace.db",
        )
        webui_app.TRIAGE_REPORT_DIR = triage_report_dir
        webui_app.ghidra_client = FakeGhidraClient()
        webui_app.sandbox_client = FakeSandboxClient()
        webui_app.job_service = webui_app.JobService(
            webui_app.job_store,
            ghidra_client=webui_app.ghidra_client,
            sandbox_client=webui_app.sandbox_client,
            ghidra_base=webui_app.GHIDRAAAS_BASE,
            response_error_details=webui_app._response_error_details,
        )
        webui_app.get_cached_triage_report = lambda job_id: None
        webui_app.queue_triage_report = lambda job_id, filename: True
        webui_app.WINDOWS_SANDBOX_CREDENTIALS_PATH = base / "sandbox" / "windows-sandbox.env"
        webui_app.sandbox_credentials = SandboxCredentialsManager(webui_app.WINDOWS_SANDBOX_CREDENTIALS_PATH)
        webui_app.sandbox_credentials.ensure_credentials()
        webui_app.job_workflow = webui_app.JobWorkflow(
            job_store=webui_app.job_store,
            job_service=webui_app.job_service,
            ghidra_client=webui_app.ghidra_client,
            sandbox_client=webui_app.sandbox_client,
            queue_triage_report=webui_app.queue_triage_report,
        )
        webui_app.reconstruction_service = webui_app.ReconstructionService(webui_app.job_store)

        webui_app.app.config["TESTING"] = True
        self.client = webui_app.app.test_client()

    def tearDown(self):
        webui_app.job_store = self.original_job_store
        webui_app.ghidra_client = self.original_ghidra_client
        webui_app.sandbox_client = self.original_sandbox_client
        webui_app.job_service = self.original_job_service
        webui_app.job_workflow = self.original_job_workflow
        webui_app.reconstruction_service = self.original_reconstruction_service
        webui_app.INTERNAL_API_TOKEN = self.original_internal_api_token
        webui_app.app.config["OPERATOR_USERNAME"] = self.original_operator_username
        webui_app.app.config["OPERATOR_PASSWORD"] = self.original_operator_password
        webui_app.app.config["RATE_LIMIT_UPLOAD"] = self.original_rate_limit_upload
        webui_app.app.config["RATE_LIMIT_REVEAL"] = self.original_rate_limit_reveal
        webui_app.WINDOWS_SANDBOX_CREDENTIALS_PATH = self.original_windows_sandbox_credentials_path
        webui_app.sandbox_credentials = self.original_sandbox_credentials
        webui_app.TRIAGE_REPORT_DIR = self.original_triage_report_dir
        webui_app.get_cached_triage_report = self.original_get_cached_triage_report
        webui_app.queue_triage_report = self.original_queue_triage_report
        webui_app.e2e_fixture = self.original_e2e_fixture
        self.temp_dir.cleanup()

    def _basic_auth_headers(self, username="operator", password="secret-pass"):
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def test_patch_job_updates_label_and_archived_metadata(self):
        webui_app.job_store.record_job_filename("job-1", "sample.exe")

        response = self.client.patch(
            "/jobs/job-1",
            json={"label": "Priority Sample", "archived": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["job"]["label"], "Priority Sample")
        self.assertTrue(payload["job"]["archived"])

        metadata = webui_app.job_store.load_job_metadata()
        self.assertEqual(metadata["job-1"]["filename"], "sample.exe")
        self.assertEqual(metadata["job-1"]["label"], "Priority Sample")
        self.assertTrue(metadata["job-1"]["archived"])

    def test_list_jobs_merges_remote_projects_with_local_metadata(self):
        webui_app.job_store.update_job_metadata(
            "job-1",
            filename="sample.exe",
            label="Renamed Sample",
            archived=True,
        )
        webui_app.ghidra_client.projects = [
            {"job_id": "job-1", "status": "done", "phase": "triage_ready"},
            {"job_id": "job-2", "status": "analyzing"},
        ]

        response = self.client.get("/jobs")

        self.assertEqual(response.status_code, 200)
        jobs = response.get_json()["jobs"]
        self.assertEqual(len(jobs), 2)
        first = next(job for job in jobs if job["job_id"] == "job-1")
        self.assertEqual(first["filename"], "sample.exe")
        self.assertEqual(first["label"], "Renamed Sample")
        self.assertTrue(first["archived"])
        self.assertEqual(first["display_name"], "Renamed Sample")
        self.assertEqual(first["phase"], "triage_ready")

    def test_status_reports_done_when_cached_triage_completed(self):
        webui_app.get_cached_triage_report = lambda job_id: {"status": "completed"}

        response = self.client.get("/status/job-1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["phase"], "triage_ready")

    def test_record_and_get_dynamic_evidence(self):
        post_response = self.client.post(
            "/evidence/job-1",
            headers={"X-Internal-Token": webui_app.INTERNAL_API_TOKEN} if webui_app.INTERNAL_API_TOKEN else None,
            json={
                "artifacts": [
                    {
                        "type": "network",
                        "highlights": ["connects to example.com"],
                    }
                ]
            },
        )

        self.assertEqual(post_response.status_code, 200)
        summary = post_response.get_json()["summary"]
        self.assertEqual(summary["artifact_count"], 1)
        self.assertEqual(summary["highlight_count"], 1)

        get_response = self.client.get("/evidence/job-1")
        self.assertEqual(get_response.status_code, 200)
        payload = get_response.get_json()
        self.assertEqual(len(payload["artifacts"]), 1)
        self.assertEqual(payload["summary"]["artifact_types"]["network"], 1)

    def test_upload_persists_sample_and_records_job(self):
        response = self.client.post(
            "/upload",
            data={"file": (BytesIO(b"MZ-test-binary"), "sample.exe")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ANALYZING")

        job_id = payload["job_id"]
        metadata = webui_app.job_store.load_job_metadata()
        self.assertEqual(metadata[job_id]["filename"], "sample.exe")
        self.assertTrue((webui_app.job_store.uploads_dir / f"{job_id}.bin").exists())
        self.assertEqual(webui_app.ghidra_client.analyze_calls[0]["filename"], "sample.exe")

    def test_upload_sanitizes_filename_before_dispatching_to_backends(self):
        response = self.client.post(
            "/upload",
            data={"file": (BytesIO(b"MZ-test-binary-2"), "payload?.exe")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        job_id = payload["job_id"]
        metadata = webui_app.job_store.load_job_metadata()
        self.assertEqual(metadata[job_id]["filename"], "payload.exe")
        self.assertEqual(webui_app.ghidra_client.analyze_calls[0]["filename"], "payload.exe")

    def test_triage_route_queues_when_report_missing(self):
        webui_app.queue_triage_report = lambda job_id, filename: True

        response = self.client.get("/triage/job-1")

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["status"], "queued")

    def test_triage_export_returns_markdown_attachment(self):
        webui_app.job_store.record_job_filename("job-1", "sample.exe")
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "markdown": "# Report",
            "job_id": job_id,
        }

        response = self.client.get("/triage/job-1/export?format=md")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        self.assertIn("# Report", response.get_data(as_text=True))

    def test_triage_export_uses_sanitized_label_for_attachment_name(self):
        webui_app.job_store.update_job_metadata(
            "job-1",
            filename="sample.exe",
            label="APT sample: stage/1",
        )
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "markdown": "# Report",
            "job_id": job_id,
        }

        response = self.client.get("/triage/job-1/export?format=md")

        self.assertEqual(response.status_code, 200)
        self.assertIn('APT_sample__stage_1-triage.md', response.headers["Content-Disposition"])

    def test_x64dbg_endpoints_proxy_to_sandbox_client(self):
        state_response = self.client.get("/debug/x64dbg/job-1")
        findings_response = self.client.get("/debug/x64dbg/job-1/findings")
        request_response = self.client.post(
            "/debug/x64dbg/job-1/requests",
            json={"action": "trace_api"},
        )

        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(state_response.get_json()["status"], "attached")
        self.assertEqual(findings_response.status_code, 200)
        self.assertEqual(findings_response.get_json()["findings"][0]["summary"], "Breakpoint hit")
        self.assertEqual(request_response.status_code, 202)
        self.assertEqual(request_response.get_json()["status"], "queued")

    def test_evidence_rejects_non_json_payloads(self):
        response = self.client.post(
            "/evidence/job-1",
            data="not-json",
            content_type="text/plain",
            headers={"X-Internal-Token": webui_app.INTERNAL_API_TOKEN} if webui_app.INTERNAL_API_TOKEN else None,
        )

        self.assertEqual(response.status_code, 415)
        self.assertIn("json", response.get_json()["error"].lower())

    def test_evidence_sanitizes_artifacts_before_persisting(self):
        response = self.client.post(
            "/evidence/job-1",
            headers={"X-Internal-Token": webui_app.INTERNAL_API_TOKEN} if webui_app.INTERNAL_API_TOKEN else None,
            json={
                "artifacts": [
                    {
                        "type": "network\x00",
                        "highlights": ["connects\x07 to example.com", " "],
                        "metadata": {"host\x00": "example.com\x07"},
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = self.client.get("/evidence/job-1").get_json()
        artifact = payload["artifacts"][0]
        self.assertEqual(artifact["type"], "network")
        self.assertEqual(artifact["highlights"], ["connects to example.com"])
        self.assertEqual(artifact["metadata"], {"host": "example.com"})

    def test_evidence_requires_internal_token_when_configured(self):
        webui_app.INTERNAL_API_TOKEN = "shared-secret"

        response = self.client.post(
            "/evidence/job-1",
            json={"artifacts": [{"type": "network"}]},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "unauthorized")

    def test_evidence_accepts_internal_token_when_configured(self):
        webui_app.INTERNAL_API_TOKEN = "shared-secret"

        response = self.client.post(
            "/evidence/job-1",
            headers={"X-Internal-Token": "shared-secret"},
            json={"artifacts": [{"type": "network"}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "recorded")

    def test_x64dbg_request_rejects_missing_action(self):
        response = self.client.post(
            "/debug/x64dbg/job-1/requests",
            json={"params": {"depth": "5"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("action", response.get_json()["error"].lower())

    def test_x64dbg_findings_require_findings_array(self):
        response = self.client.post(
            "/debug/x64dbg/job-1/findings",
            json={"summary": "Breakpoint hit"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("findings", response.get_json()["error"].lower())

    def test_x64dbg_state_requires_json_payload(self):
        response = self.client.post(
            "/debug/x64dbg/job-1",
            data="not-json",
            content_type="text/plain",
        )

        self.assertEqual(response.status_code, 415)
        self.assertIn("json", response.get_json()["error"].lower())

    def test_triage_export_returns_409_when_report_not_ready(self):
        response = self.client.get("/triage/job-1/export?format=md")

        self.assertEqual(response.status_code, 409)
        self.assertIn("not ready", response.get_json()["error"].lower())

    def test_x64dbg_state_returns_503_when_sandbox_not_configured(self):
        webui_app.sandbox_client = UnconfiguredSandboxClient()

        response = self.client.get("/debug/x64dbg/job-1")

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.get_json()["error"].lower())

    def test_delete_job_removes_metadata_and_uploaded_sample(self):
        webui_app.job_store.record_job_filename("job-1", "sample.exe")
        webui_app.job_store.save_dynamic_evidence("job-1", {"job_id": "job-1", "artifacts": []})
        webui_app.job_store.uploads_dir.mkdir(parents=True, exist_ok=True)
        (webui_app.job_store.uploads_dir / "job-1.bin").write_bytes(b"sample")

        response = self.client.delete("/jobs/job-1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "deleted")
        self.assertNotIn("job-1", webui_app.job_store.load_job_metadata())
        self.assertFalse((webui_app.job_store.uploads_dir / "job-1.bin").exists())

    def test_assistant_next_steps_returns_guidance_structure(self):
        webui_app.job_store.record_job_filename("job-1", "sample.exe")
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {"capabilities": ["filesystem"]},
        }
        webui_app.sandbox_client.snapshot = {
            "state": {"status": "idle"},
            "findings": {"findings": []},
            "requests": {"requests": []},
        }

        response = self.client.get("/assistant/next_steps/job-1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["job_id"], "job-1")
        self.assertIn("stage", payload)
        self.assertIn("summary", payload)
        self.assertIn("suggestions", payload)

    def test_reconstruction_routes_store_and_load_bundle(self):
        target_response = self.client.post(
            "/reconstruction/job-1/targets",
            json={
                "target_id": "target-installer",
                "title": "Installer path",
                "scope": "subsystem",
                "rationale": "Imports and strings suggest update/install logic.",
                "priority": 10,
                "evidence_links": ["triage:capability:filesystem", "string:setup"],
            },
        )
        hypothesis_response = self.client.post(
            "/reconstruction/job-1/hypotheses",
            json={
                "hypothesis_id": "hyp-installer-writes",
                "target_id": "target-installer",
                "title": "Writes deployment files",
                "claim": "The installer path likely writes files before launching a child process.",
                "confidence": "medium",
                "supporting_evidence": ["import:CreateFileW", "import:CreateProcessW"],
                "missing_evidence": ["dynamic:file-write-trace"],
                "next_step": "Trace API activity around process creation.",
            },
        )
        artifact_response = self.client.post(
            "/reconstruction/job-1/drafts",
            json={
                "artifact_id": "draft-installer-plan",
                "target_id": "target-installer",
                "title": "Installer reconstruction draft",
                "artifact_type": "implementation_plan",
                "summary": "Readable first-pass reconstruction of the installer path.",
                "body": "1. Stage files. 2. Spawn child process.",
                "evidence_links": ["hypothesis:hyp-installer-writes"],
                "assumptions": ["File writes happen before child launch."],
            },
        )
        plan_response = self.client.post(
            "/reconstruction/job-1/validation_plans",
            json={
                "plan_id": "plan-installer-checks",
                "target_id": "target-installer",
                "title": "Installer validation plan",
                "checks": [
                    {
                        "label": "Compare file writes",
                        "expected": "Installer path writes at least one staged payload",
                        "method": "sandbox trace",
                    }
                ],
                "open_risks": ["Write location may depend on runtime env"],
            },
        )
        bundle_response = self.client.get("/reconstruction/job-1")

        self.assertEqual(target_response.status_code, 201)
        self.assertEqual(hypothesis_response.status_code, 201)
        self.assertEqual(artifact_response.status_code, 201)
        self.assertEqual(plan_response.status_code, 201)
        self.assertEqual(bundle_response.status_code, 200)
        bundle = bundle_response.get_json()
        self.assertEqual(bundle["targets"][0]["target_id"], "target-installer")
        self.assertEqual(bundle["hypotheses"][0]["hypothesis_id"], "hyp-installer-writes")
        self.assertEqual(bundle["draft_artifacts"][0]["artifact_id"], "draft-installer-plan")
        self.assertEqual(bundle["validation_plans"][0]["plan_id"], "plan-installer-checks")

    def test_reconstruction_target_rejects_invalid_payload(self):
        response = self.client.post(
            "/reconstruction/job-1/targets",
            json={"title": "Missing required fields"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("target_id", response.get_json()["error"])

    def test_reconstruction_target_generation_requires_completed_triage(self):
        response = self.client.post("/reconstruction/job-1/targets/generate")

        self.assertEqual(response.status_code, 409)
        self.assertIn("triage", response.get_json()["error"].lower())

    def test_reconstruction_target_generation_builds_targets_from_triage(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {
                "capabilities": ["filesystem", "networking", "process_execution"],
                "strings_summary": {
                    "interesting_strings": {
                        "urls": ["https://example.com/update"],
                    }
                },
                "functions_summary": {
                    "priority_functions": [
                        {"name": "InstallAndLaunch", "address": "0x401000"},
                    ]
                },
                "dynamic_summary": {
                    "artifact_count": 0,
                    "artifact_types": {},
                },
            },
        }

        response = self.client.post("/reconstruction/job-1/targets/generate")

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        targets = payload["targets"]
        target_ids = {target["target_id"] for target in targets}
        self.assertIn("target-filesystem", target_ids)
        self.assertIn("target-networking", target_ids)
        self.assertIn("target-process-execution", target_ids)
        self.assertIn("target-network-endpoints", target_ids)
        self.assertIn("target-function-installandlaunch", target_ids)

    def test_reconstruction_hypothesis_generation_requires_completed_triage(self):
        response = self.client.post("/reconstruction/job-1/hypotheses/generate")

        self.assertEqual(response.status_code, 409)
        self.assertIn("triage", response.get_json()["error"].lower())

    def test_reconstruction_hypothesis_generation_requires_targets(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {},
        }

        response = self.client.post("/reconstruction/job-1/hypotheses/generate")

        self.assertEqual(response.status_code, 409)
        self.assertIn("target", response.get_json()["error"].lower())

    def test_reconstruction_hypothesis_generation_builds_hypotheses_from_targets(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {
                "capabilities": ["filesystem", "networking", "process_execution"],
                "strings_summary": {
                    "interesting_strings": {
                        "urls": ["https://example.com/update"],
                    }
                },
                "functions_summary": {
                    "priority_functions": [
                        {"name": "InstallAndLaunch", "address": "0x401000"},
                    ]
                },
                "dynamic_summary": {
                    "artifact_count": 1,
                    "artifact_types": {"network": 1},
                },
            },
        }
        self.client.post("/reconstruction/job-1/targets/generate")

        response = self.client.post("/reconstruction/job-1/hypotheses/generate")

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        hypotheses = payload["hypotheses"]
        hypothesis_ids = {record["hypothesis_id"] for record in hypotheses}
        self.assertIn("hyp-filesystem-staging", hypothesis_ids)
        self.assertIn("hyp-networking-telemetry", hypothesis_ids)
        self.assertIn("hyp-process-execution-launch-chain", hypothesis_ids)
        self.assertIn("hyp-network-endpoints-url-map", hypothesis_ids)
        self.assertIn("hyp-target-function-installandlaunch-control-flow", hypothesis_ids)

    def test_reconstruction_draft_generation_requires_hypotheses(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {"capabilities": ["filesystem"]},
        }
        self.client.post("/reconstruction/job-1/targets/generate")

        response = self.client.post("/reconstruction/job-1/drafts/generate")

        self.assertEqual(response.status_code, 409)
        self.assertIn("hypothesis", response.get_json()["error"].lower())

    def test_reconstruction_draft_generation_builds_package_from_target_and_hypotheses(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {
                "capabilities": ["filesystem", "process_execution"],
                "strings_summary": {"interesting_strings": {}},
                "functions_summary": {
                    "priority_functions": [
                        {"name": "InstallAndLaunch", "address": "0x401000"},
                    ]
                },
                "dynamic_summary": {
                    "artifact_count": 1,
                    "artifact_types": {"file_write": 1},
                },
            },
        }
        self.client.post("/reconstruction/job-1/targets/generate")
        self.client.post("/reconstruction/job-1/hypotheses/generate")

        response = self.client.post(
            "/reconstruction/job-1/drafts/generate",
            json={"target_id": "target-filesystem"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        artifacts = payload["draft_artifacts"]
        draft = next(artifact for artifact in artifacts if artifact["target_id"] == "target-filesystem")
        self.assertEqual(draft["artifact_type"], "implementation_plan")
        self.assertEqual(draft["validation_status"], "needs_validation")
        self.assertIn("creates or updates files", draft["summary"].lower())
        self.assertIn("Reconstruction Package", draft["body"])

    def test_reconstruction_draft_export_returns_markdown_bundle(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {
                "capabilities": ["networking"],
                "strings_summary": {
                    "interesting_strings": {"urls": ["https://example.com/update"]},
                },
                "functions_summary": {},
                "dynamic_summary": {"artifact_count": 0, "artifact_types": {}},
            },
        }
        self.client.post("/reconstruction/job-1/targets/generate")
        self.client.post("/reconstruction/job-1/hypotheses/generate")
        self.client.post("/reconstruction/job-1/drafts/generate")
        self.client.post("/reconstruction/job-1/validation_plans/generate")

        response = self.client.get("/reconstruction/job-1/drafts/draft-target-network-endpoints-package/export?format=md")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        body = response.get_data(as_text=True)
        self.assertIn("# Endpoint and protocol surface reconstruction package", body)
        self.assertIn("## Validation Plans", body)

    def test_reconstruction_validation_plan_generation_requires_hypotheses(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {"capabilities": ["networking"]},
        }
        self.client.post("/reconstruction/job-1/targets/generate")

        response = self.client.post("/reconstruction/job-1/validation_plans/generate")

        self.assertEqual(response.status_code, 409)
        self.assertIn("hypothesis", response.get_json()["error"].lower())

    def test_reconstruction_validation_plan_generation_builds_checks(self):
        webui_app.get_cached_triage_report = lambda job_id: {
            "status": "completed",
            "summary": {
                "capabilities": ["networking"],
                "strings_summary": {
                    "interesting_strings": {"urls": ["https://example.com/update"]},
                },
                "functions_summary": {},
                "dynamic_summary": {"artifact_count": 0, "artifact_types": {}},
            },
        }
        self.client.post("/reconstruction/job-1/targets/generate")
        self.client.post("/reconstruction/job-1/hypotheses/generate")

        response = self.client.post(
            "/reconstruction/job-1/validation_plans/generate",
            json={"target_id": "target-network-endpoints"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        plans = payload["validation_plans"]
        plan = next(plan for plan in plans if plan["target_id"] == "target-network-endpoints")
        self.assertEqual(plan["status"], "draft")
        labels = [check["label"] for check in plan["checks"]]
        self.assertIn("Compare outbound hosts or protocol fields", labels)
        self.assertTrue(plan["open_risks"])

    def test_status_returns_502_when_remote_lookup_fails_without_local_job(self):
        import requests

        webui_app.ghidra_client.list_projects_error = requests.exceptions.RequestException("ghidra down")

        response = self.client.get("/status/job-missing")

        self.assertEqual(response.status_code, 502)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertIn("ghidra down", payload["error"])

    def test_status_returns_analyzing_when_local_job_exists_and_ghidra_is_unavailable(self):
        import requests

        webui_app.job_store.record_job_filename("job-1", "sample.exe")
        webui_app.ghidra_client.list_projects_error = requests.exceptions.RequestException("ghidra down")

        response = self.client.get("/status/job-1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "analyzing")
        self.assertEqual(payload["phase"], "ghidra_processing")
        self.assertIn("ghidra down", payload["warning"])

    def test_windows_lab_credentials_endpoint_returns_generated_credentials(self):
        response = self.client.get("/sandbox/windows_lab_credentials")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["username"], "Docker")
        self.assertTrue(payload["password_available"])
        self.assertEqual(payload["ssh_host"], "127.0.0.1:2222")

    def test_windows_lab_credentials_reveal_returns_password_on_demand(self):
        response = self.client.post("/sandbox/windows_lab_credentials/reveal", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["username"], "Docker")
        self.assertTrue(len(payload["password"]) >= 20)

    def test_operator_auth_is_required_when_configured(self):
        webui_app.app.config["OPERATOR_USERNAME"] = "operator"
        webui_app.app.config["OPERATOR_PASSWORD"] = "secret-pass"

        response = self.client.get("/")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["WWW-Authenticate"])

    def test_operator_auth_accepts_valid_basic_auth(self):
        webui_app.app.config["OPERATOR_USERNAME"] = "operator"
        webui_app.app.config["OPERATOR_PASSWORD"] = "secret-pass"

        response = self.client.get("/", headers=self._basic_auth_headers())

        self.assertEqual(response.status_code, 200)
        self.assertIn("GhostTrace", response.get_data(as_text=True))

    def test_internal_evidence_route_stays_exempt_from_operator_auth(self):
        webui_app.app.config["OPERATOR_USERNAME"] = "operator"
        webui_app.app.config["OPERATOR_PASSWORD"] = "secret-pass"
        webui_app.INTERNAL_API_TOKEN = "shared-secret"

        response = self.client.post(
            "/evidence/job-1",
            headers={"X-Internal-Token": "shared-secret"},
            json={"artifacts": [{"type": "network"}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "recorded")

    def test_windows_lab_reveal_rate_limit_returns_429(self):
        webui_app.app.config["RATE_LIMIT_REVEAL"] = webui_app.RateLimitRule(limit=1, window_seconds=60)
        environ = {"REMOTE_ADDR": "10.10.10.10"}

        first = self.client.post("/sandbox/windows_lab_credentials/reveal", json={}, environ_overrides=environ)
        second = self.client.post("/sandbox/windows_lab_credentials/reveal", json={}, environ_overrides=environ)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json()["bucket"], "windows_lab_reveal")
        self.assertIn("Retry-After", second.headers)

    def test_responses_include_security_headers(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_responses_include_request_id_header(self):
        response = self.client.get("/", headers={"X-Request-ID": "req-123"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "req-123")

    def test_health_reports_observability_payload(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["service"], "webui")
        self.assertEqual(payload["status"], "ok")
        self.assertIn("checks", payload)
        self.assertTrue(payload["checks"]["sqlite_db_present"])

    def test_metrics_summary_reports_job_and_service_counts(self):
        webui_app.job_store.update_job_metadata("job-1", filename="sample.exe", archived=False)
        webui_app.job_store.update_job_metadata("job-2", filename="archived.exe", archived=True)
        webui_app.job_store.save_dynamic_evidence("job-1", {"job_id": "job-1", "artifacts": [{"type": "network"}]})
        webui_app.TRIAGE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (webui_app.TRIAGE_REPORT_DIR / "job-1.json").write_text('{"status":"completed"}', encoding="utf-8")

        response = self.client.get("/metrics/summary")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["jobs"]["total"], 2)
        self.assertEqual(payload["jobs"]["archived"], 1)
        self.assertEqual(payload["jobs"]["with_dynamic_evidence"], 1)
        self.assertEqual(payload["triage"]["completed"], 1)
        self.assertIn("ghidraaas", payload["services"])
        self.assertIn("triage", payload["queues"])
        self.assertIn("sandbox_run", payload["queues"])
        self.assertIn("x64dbg_requests", payload["queues"])

    def test_metrics_text_exposes_prometheus_gauges(self):
        webui_app.job_store.update_job_metadata("job-1", filename="sample.exe", archived=False)

        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("ghosttrace_jobs_total", body)
        self.assertIn("ghosttrace_service_up", body)
        self.assertIn("ghosttrace_queue_messages", body)
        self.assertIn("ghosttrace_queue_consumers", body)

    def test_fixture_mode_returns_seeded_jobs_and_metrics(self):
        fixture = E2EFixture(
            webui_app.job_store,
            webui_app.TRIAGE_REPORT_DIR,
            webui_app.WINDOWS_SANDBOX_CREDENTIALS_PATH,
        )
        fixture.seed()
        webui_app.e2e_fixture = fixture

        jobs_response = self.client.get("/jobs")
        metrics_response = self.client.get("/metrics/summary")
        status_response = self.client.get(f"/status/{fixture.job_id}")

        self.assertEqual(jobs_response.status_code, 200)
        jobs = jobs_response.get_json()["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], fixture.job_id)
        self.assertEqual(jobs[0]["display_name"], fixture.job_label)

        self.assertEqual(metrics_response.status_code, 200)
        metrics_payload = metrics_response.get_json()
        self.assertEqual(metrics_payload["services"]["ghidraaas"]["status"], "ok")
        self.assertEqual(metrics_payload["queues"]["triage"]["messages"], 0)
        self.assertEqual(metrics_payload["jobs"]["total"], 1)

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.get_json()["status"], "done")

    def test_fixture_mode_returns_seeded_debugger_payloads(self):
        fixture = E2EFixture(
            webui_app.job_store,
            webui_app.TRIAGE_REPORT_DIR,
            webui_app.WINDOWS_SANDBOX_CREDENTIALS_PATH,
        )
        fixture.seed()
        webui_app.e2e_fixture = fixture

        state_response = self.client.get(f"/debug/x64dbg/{fixture.job_id}")
        findings_response = self.client.get(f"/debug/x64dbg/{fixture.job_id}/findings")
        requests_response = self.client.get(f"/debug/x64dbg/{fixture.job_id}/requests")
        creds_response = self.client.get("/sandbox/windows_lab_credentials")
        reveal_response = self.client.post("/sandbox/windows_lab_credentials/reveal", json={})

        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(state_response.get_json()["status"], "bridge-online")
        self.assertEqual(findings_response.status_code, 200)
        self.assertEqual(findings_response.get_json()["findings"], [])
        self.assertEqual(requests_response.status_code, 200)
        self.assertEqual(requests_response.get_json()["requests"], [])
        self.assertEqual(creds_response.status_code, 200)
        self.assertEqual(creds_response.get_json()["username"], "Docker")
        self.assertEqual(reveal_response.status_code, 200)
        self.assertEqual(reveal_response.get_json()["password"], "fixture-pass-12345")

if __name__ == "__main__":
    unittest.main()
