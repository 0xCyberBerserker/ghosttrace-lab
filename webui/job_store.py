import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from reconstruction_record import (
    DraftArtifact,
    HypothesisRecord,
    ReconstructionTarget,
    ValidationPlan,
)


@dataclass
class JobStore:
    metadata_path: Path
    uploads_dir: Path
    dynamic_evidence_dir: Path
    triage_report_dir: Path
    db_path: Path

    def __post_init__(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_metadata()
        self._migrate_legacy_evidence()

    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_db(self):
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_metadata (
                    job_id TEXT PRIMARY KEY,
                    filename TEXT,
                    label TEXT,
                    archived INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dynamic_evidence (
                    job_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reconstruction_targets (
                    target_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    evidence_links_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hypothesis_records (
                    hypothesis_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    target_id TEXT,
                    title TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    supporting_evidence_json TEXT NOT NULL,
                    missing_evidence_json TEXT NOT NULL,
                    next_step TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS draft_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    target_id TEXT,
                    title TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    evidence_links_json TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    validation_status TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_plans (
                    plan_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    target_id TEXT,
                    title TEXT NOT NULL,
                    checks_json TEXT NOT NULL,
                    open_risks_json TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )

    def _legacy_metadata_payload(self):
        if not self.metadata_path.exists():
            return {}
        try:
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(raw, dict):
            return {}

        normalized = {}
        for job_id, value in raw.items():
            if isinstance(value, str):
                normalized[job_id] = {"filename": value}
            elif isinstance(value, dict):
                normalized[job_id] = value
        return normalized

    def _migrate_legacy_metadata(self):
        legacy = self._legacy_metadata_payload()
        if not legacy:
            return

        with self._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM job_metadata").fetchone()[0]
            if count:
                return

            for job_id, entry in legacy.items():
                connection.execute(
                    """
                    INSERT OR REPLACE INTO job_metadata(job_id, filename, label, archived)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        entry.get("filename"),
                        entry.get("label"),
                        1 if entry.get("archived") else 0,
                    ),
                )

    def _migrate_legacy_evidence(self):
        self.dynamic_evidence_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM dynamic_evidence").fetchone()[0]
            if count:
                return

            for path in self.dynamic_evidence_dir.glob("*.json"):
                job_id = path.stem
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                payload.setdefault("job_id", job_id)
                payload.setdefault("artifacts", [])
                connection.execute(
                    "INSERT OR REPLACE INTO dynamic_evidence(job_id, payload_json) VALUES (?, ?)",
                    (job_id, json.dumps(payload)),
                )

    def load_job_metadata(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT job_id, filename, label, archived FROM job_metadata"
            ).fetchall()

        metadata = {}
        for row in rows:
            entry = {}
            if row["filename"]:
                entry["filename"] = row["filename"]
            if row["label"]:
                entry["label"] = row["label"]
            if row["archived"]:
                entry["archived"] = bool(row["archived"])
            metadata[row["job_id"]] = entry
        return metadata

    def save_job_metadata(self, metadata):
        with self._connection() as connection:
            connection.execute("DELETE FROM job_metadata")
            for job_id, entry in metadata.items():
                if not isinstance(entry, dict):
                    entry = {"filename": str(entry)}
                connection.execute(
                    """
                    INSERT OR REPLACE INTO job_metadata(job_id, filename, label, archived)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        entry.get("filename"),
                        entry.get("label"),
                        1 if entry.get("archived") else 0,
                    ),
                )

    def record_job_filename(self, job_id, filename):
        self.update_job_metadata(job_id, filename=filename)

    def update_job_metadata(self, job_id, **updates):
        metadata = self.load_job_metadata()
        entry = metadata.get(job_id, {})
        if not isinstance(entry, dict):
            entry = {"filename": str(entry)}

        allowed = {"filename", "label", "archived"}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if value is None or value == "":
                entry.pop(key, None)
            else:
                entry[key] = value

        with self._connection() as connection:
            if entry:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO job_metadata(job_id, filename, label, archived)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        entry.get("filename"),
                        entry.get("label"),
                        1 if entry.get("archived") else 0,
                    ),
                )
            else:
                connection.execute("DELETE FROM job_metadata WHERE job_id = ?", (job_id,))
        return entry

    def delete_job_metadata(self, job_id):
        with self._connection() as connection:
            connection.execute("DELETE FROM job_metadata WHERE job_id = ?", (job_id,))

    def job_display_name(self, job):
        return job.get("label") or job.get("filename") or f"{job.get('job_id', '')[:8]}.bin"

    def save_uploaded_sample(self, job_id: str, file_storage) -> Path:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        sample_path = self.uploads_dir / f"{job_id}.bin"

        file_storage.stream.seek(0)
        with sample_path.open("wb") as f_out:
            for chunk in iter(lambda: file_storage.stream.read(4096), b""):
                if not chunk:
                    break
                f_out.write(chunk)

        return sample_path

    def evidence_path(self, job_id):
        return self.dynamic_evidence_dir / f"{job_id}.json"

    def load_dynamic_evidence(self, job_id):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM dynamic_evidence WHERE job_id = ?",
                (job_id,),
            ).fetchone()

        if row is None:
            return {"job_id": job_id, "artifacts": []}

        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {"job_id": job_id, "artifacts": []}
        payload.setdefault("job_id", job_id)
        payload.setdefault("artifacts", [])
        return payload

    def save_dynamic_evidence(self, job_id, payload):
        self.dynamic_evidence_dir.mkdir(parents=True, exist_ok=True)
        normalized = dict(payload)
        normalized.setdefault("job_id", job_id)
        normalized.setdefault("artifacts", [])
        payload_json = json.dumps(normalized, indent=2)

        with self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO dynamic_evidence(job_id, payload_json) VALUES (?, ?)",
                (job_id, payload_json),
            )

        self.evidence_path(job_id).write_text(payload_json, encoding="utf-8")

    def summarize_evidence(self, payload):
        artifacts = payload.get("artifacts", [])
        artifact_types = {}
        suspicious_hits = []
        for artifact in artifacts:
            artifact_type = artifact.get("type", "unknown")
            artifact_types[artifact_type] = artifact_types.get(artifact_type, 0) + 1
            for hit in artifact.get("highlights", []):
                suspicious_hits.append(hit)

        return {
            "artifact_count": len(artifacts),
            "artifact_types": artifact_types,
            "highlight_count": len(suspicious_hits),
            "highlights": suspicious_hits[:30],
        }

    def delete_local_job_artifacts(self, job_id):
        removed = {}
        paths = {
            "dynamic_evidence": self.evidence_path(job_id),
            "uploaded_sample": self.uploads_dir / f"{job_id}.bin",
            "triage_json": self.triage_report_dir / f"{job_id}.json",
            "triage_markdown": self.triage_report_dir / f"{job_id}.md",
        }

        for label, path in paths.items():
            try:
                if path.exists():
                    path.unlink()
                    removed[label] = True
                else:
                    removed[label] = False
            except OSError:
                removed[label] = False

        with self._connection() as connection:
            connection.execute("DELETE FROM dynamic_evidence WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM reconstruction_targets WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM hypothesis_records WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM draft_artifacts WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM validation_plans WHERE job_id = ?", (job_id,))
        self.delete_job_metadata(job_id)
        removed["job_metadata"] = True
        removed["dynamic_evidence_db"] = True
        removed["reconstruction_db"] = True
        return removed

    def reset_local_job_runtime_artifacts(self, job_id):
        removed = {}
        paths = {
            "dynamic_evidence": self.evidence_path(job_id),
            "triage_json": self.triage_report_dir / f"{job_id}.json",
            "triage_markdown": self.triage_report_dir / f"{job_id}.md",
        }
        for label, path in paths.items():
            try:
                if path.exists():
                    path.unlink()
                    removed[label] = True
                else:
                    removed[label] = False
            except OSError:
                removed[label] = False

        with self._connection() as connection:
            connection.execute("DELETE FROM dynamic_evidence WHERE job_id = ?", (job_id,))
        removed["dynamic_evidence_db"] = True
        return removed

    def save_reconstruction_target(self, target: ReconstructionTarget):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO reconstruction_targets(
                    target_id, job_id, title, scope, status, rationale, priority, evidence_links_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target.target_id,
                    target.job_id,
                    target.title,
                    target.scope,
                    target.status,
                    target.rationale,
                    target.priority,
                    json.dumps(target.evidence_links),
                ),
            )

    def list_reconstruction_targets(self, job_id):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT target_id, job_id, title, scope, status, rationale, priority, evidence_links_json
                FROM reconstruction_targets
                WHERE job_id = ?
                ORDER BY priority ASC, title ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            ReconstructionTarget(
                target_id=row["target_id"],
                job_id=row["job_id"],
                title=row["title"],
                scope=row["scope"],
                status=row["status"],
                rationale=row["rationale"],
                priority=row["priority"],
                evidence_links=json.loads(row["evidence_links_json"] or "[]"),
            )
            for row in rows
        ]

    def save_hypothesis(self, record: HypothesisRecord):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO hypothesis_records(
                    hypothesis_id, job_id, target_id, title, claim, confidence,
                    supporting_evidence_json, missing_evidence_json, next_step
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.hypothesis_id,
                    record.job_id,
                    record.target_id,
                    record.title,
                    record.claim,
                    record.confidence,
                    json.dumps(record.supporting_evidence),
                    json.dumps(record.missing_evidence),
                    record.next_step,
                ),
            )

    def list_hypotheses(self, job_id):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT hypothesis_id, job_id, target_id, title, claim, confidence,
                       supporting_evidence_json, missing_evidence_json, next_step
                FROM hypothesis_records
                WHERE job_id = ?
                ORDER BY title ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            HypothesisRecord(
                hypothesis_id=row["hypothesis_id"],
                job_id=row["job_id"],
                target_id=row["target_id"],
                title=row["title"],
                claim=row["claim"],
                confidence=row["confidence"],
                supporting_evidence=json.loads(row["supporting_evidence_json"] or "[]"),
                missing_evidence=json.loads(row["missing_evidence_json"] or "[]"),
                next_step=row["next_step"],
            )
            for row in rows
        ]

    def save_draft_artifact(self, artifact: DraftArtifact):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO draft_artifacts(
                    artifact_id, job_id, target_id, title, artifact_type, summary, body,
                    evidence_links_json, assumptions_json, validation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.job_id,
                    artifact.target_id,
                    artifact.title,
                    artifact.artifact_type,
                    artifact.summary,
                    artifact.body,
                    json.dumps(artifact.evidence_links),
                    json.dumps(artifact.assumptions),
                    artifact.validation_status,
                ),
            )

    def list_draft_artifacts(self, job_id):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT artifact_id, job_id, target_id, title, artifact_type, summary, body,
                       evidence_links_json, assumptions_json, validation_status
                FROM draft_artifacts
                WHERE job_id = ?
                ORDER BY title ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            DraftArtifact(
                artifact_id=row["artifact_id"],
                job_id=row["job_id"],
                target_id=row["target_id"],
                title=row["title"],
                artifact_type=row["artifact_type"],
                summary=row["summary"],
                body=row["body"],
                evidence_links=json.loads(row["evidence_links_json"] or "[]"),
                assumptions=json.loads(row["assumptions_json"] or "[]"),
                validation_status=row["validation_status"],
            )
            for row in rows
        ]

    def save_validation_plan(self, plan: ValidationPlan):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO validation_plans(
                    plan_id, job_id, target_id, title, checks_json, open_risks_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.job_id,
                    plan.target_id,
                    plan.title,
                    json.dumps(plan.checks),
                    json.dumps(plan.open_risks),
                    plan.status,
                ),
            )

    def list_validation_plans(self, job_id):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT plan_id, job_id, target_id, title, checks_json, open_risks_json, status
                FROM validation_plans
                WHERE job_id = ?
                ORDER BY title ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            ValidationPlan(
                plan_id=row["plan_id"],
                job_id=row["job_id"],
                target_id=row["target_id"],
                title=row["title"],
                checks=json.loads(row["checks_json"] or "[]"),
                open_risks=json.loads(row["open_risks_json"] or "[]"),
                status=row["status"],
            )
            for row in rows
        ]
