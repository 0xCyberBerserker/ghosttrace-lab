import json
from pathlib import Path

from reconstruction_record import (
    DraftArtifact,
    HypothesisRecord,
    ReconstructionTarget,
    ValidationPlan,
)


class E2EFixture:
    job_id = "fixture-job-1"

    def __init__(self, job_store, triage_report_dir: Path, sandbox_credentials_path: Path):
        self.job_store = job_store
        self.triage_report_dir = triage_report_dir
        self.sandbox_credentials_path = sandbox_credentials_path
        self.job_filename = "fixture-sample.exe"
        self.job_label = "BiosSupportCheckerSetup.exe"

    def seed(self):
        self.job_store.update_job_metadata(
            self.job_id,
            filename=self.job_filename,
            label=self.job_label,
            archived=False,
        )
        self.job_store.save_dynamic_evidence(
            self.job_id,
            {
                "job_id": self.job_id,
                "artifacts": [
                    {
                        "type": "sandbox_trace",
                        "source": "ci-fixture",
                        "summary": "Observed process launch chain and staged payload drop.",
                        "highlights": [
                            "spawned helper process",
                            "wrote staged payload to temp path",
                        ],
                    }
                ],
            },
        )

        target = ReconstructionTarget(
            target_id="target-process-launch-chain",
            job_id=self.job_id,
            title="Process launch chain",
            scope="runtime",
            status="active",
            rationale="The sample appears to stage and launch a helper process after setup initialization.",
            priority=1,
            evidence_links=["triage:function-cluster:launcher", "dynamic:process-tree"],
        )
        hypothesis = HypothesisRecord(
            hypothesis_id="hypothesis-launch-chain",
            job_id=self.job_id,
            target_id=target.target_id,
            title="Installer launches a helper chain",
            claim="The binary stages an auxiliary component and launches it to continue the install workflow.",
            confidence="medium",
            supporting_evidence=["CreateProcess import usage", "dynamic process tree"],
            missing_evidence=["command line arguments", "persistence side effects"],
            next_step="Confirm the first spawned process and its command line with x64dbg.",
        )
        draft = DraftArtifact(
            artifact_id="draft-launch-chain",
            job_id=self.job_id,
            target_id=target.target_id,
            title="Process launch reconstruction package",
            artifact_type="reconstruction_package",
            summary="Bounded package covering how the installer stages and launches the helper path.",
            body="The sample initializes the installer workflow, stages a secondary payload, then launches a helper process to continue execution.",
            evidence_links=["triage:function-cluster:launcher", "dynamic:process-tree"],
            assumptions=["The helper process continues the install chain.", "The temp path is not random noise."],
            validation_status="draft",
        )
        plan = ValidationPlan(
            plan_id="validation-launch-chain",
            job_id=self.job_id,
            target_id=target.target_id,
            title="Launch chain validation plan",
            checks=[
                {
                    "label": "Capture first spawned process",
                    "method": "x64dbg request",
                    "expected": "One helper process appears with a stable command line",
                    "status": "pending",
                }
            ],
            open_risks=["The helper process may only appear under installer-specific conditions."],
            status="draft",
        )

        self.job_store.save_reconstruction_target(target)
        self.job_store.save_hypothesis(hypothesis)
        self.job_store.save_draft_artifact(draft)
        self.job_store.save_validation_plan(plan)

        self.triage_report_dir.mkdir(parents=True, exist_ok=True)
        triage_payload = {
            "job_id": self.job_id,
            "status": "completed",
            "summary": "Installer-like workflow with helper process staging and runtime launch behavior.",
            "markdown": "# Fixture Triage Report\n\nThis fixture simulates a completed triage report for CI smoke runs.\n",
            "findings": {
                "priority_functions": ["FUN_launch_helper", "FUN_stage_payload"],
                "network_indicators": [],
            },
        }
        (self.triage_report_dir / f"{self.job_id}.json").write_text(json.dumps(triage_payload, indent=2), encoding="utf-8")
        (self.triage_report_dir / f"{self.job_id}.md").write_text(triage_payload["markdown"], encoding="utf-8")

        self.sandbox_credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.sandbox_credentials_path.write_text(
            "USERNAME=Docker\nPASSWORD=fixture-pass-12345\n",
            encoding="utf-8",
        )

    def list_jobs(self):
        return [
            {
                "job_id": self.job_id,
                "filename": self.job_filename,
                "status": "done",
                "phase": "ready",
                "created_at": "2026-03-17T00:00:00Z",
            }
        ]

    def metrics_summary(self):
        return {
            "jobs": {
                "total": 1,
                "archived": 0,
                "active": 1,
                "with_dynamic_evidence": 1,
            },
            "triage": {
                "completed": 1,
                "processing": 0,
                "other": 0,
            },
            "queues": {
                "triage": {"name": "ghosttrace.triage", "status": "ok", "messages": 0, "consumers": 1},
                "sandbox_run": {"name": "ghosttrace.sandbox.run", "status": "ok", "messages": 0, "consumers": 1},
                "x64dbg_requests": {"name": "ghosttrace.x64dbg.requests", "status": "ok", "messages": 0, "consumers": 1},
            },
            "runtime": {
                "rabbitmq_enabled": True,
                "sandbox_configured": True,
                "operator_auth_enabled": False,
            },
            "services": {
                "ghidraaas": {"name": "ghidraaas", "status": "ok", "http_status": 200, "details": {"fixture": True}},
                "sandbox_runner": {"name": "sandbox_runner", "status": "ok", "http_status": 200, "details": {"fixture": True}},
                "ollama": {"name": "ollama", "status": "ok", "http_status": 200, "details": {"fixture": True}},
            },
        }

    def x64dbg_state(self, job_id):
        return {
            "job_id": job_id,
            "status": "bridge-online",
            "target_module": self.job_label,
            "pid": 4242,
        }

    def x64dbg_findings(self, job_id):
        return {
            "job_id": job_id,
            "findings": [],
        }

    def x64dbg_requests(self, job_id):
        return {
            "job_id": job_id,
            "requests": [],
        }

    def status(self, job_id):
        return {
            "job_id": job_id,
            "status": "done",
            "phase": "ready",
        }, 200
