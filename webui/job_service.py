import requests
from dataclasses import replace

from job_record import JobRecord
from job_status import resolve_job_status


class JobService:
    def __init__(self, job_store, ghidra_client=None, sandbox_client=None, ghidra_base=None, response_error_details=None):
        self.job_store = job_store
        self.ghidra_client = ghidra_client
        self.sandbox_client = sandbox_client
        self.ghidra_base = ghidra_base
        self.response_error_details = response_error_details

    def list_jobs(self, remote_projects):
        metadata = self.job_store.load_job_metadata()
        jobs = []
        for project in remote_projects:
            jobs.append(self.build_job_record(project.get("job_id"), remote_job=project, metadata=metadata))
        return jobs

    def update_job(self, job_id, **updates):
        entry = self.job_store.update_job_metadata(job_id, **updates)
        return self.build_job_record(job_id, metadata={job_id: entry})

    def record_uploaded_job(self, job_id, filename):
        self.job_store.record_job_filename(job_id, filename)
        return self.build_job_record(job_id)

    def delete_local_job(self, job_id):
        return self.job_store.delete_local_job_artifacts(job_id)

    def triage_filename_hint(self, job_id):
        return self.build_job_record(job_id).filename

    def export_filename_root(self, job_id):
        base_name = self.build_job_record(job_id).display_name or job_id[:12]
        return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in base_name).strip("._") or job_id[:12]

    def delete_job(self, job_id):
        summary = {
            "job_id": job_id,
            "ghidraaas": {"status": "skipped"},
            "sandbox_runner": {"status": "skipped"},
            "local": {},
        }

        if self.ghidra_client is not None:
            try:
                response = self.ghidra_client.terminate_analysis(job_id, timeout=60)
                if response.ok:
                    summary["ghidraaas"] = {"status": "deleted"}
                else:
                    detail = str(response.status_code)
                    if self.response_error_details is not None:
                        detail = self.response_error_details(response)
                    summary["ghidraaas"] = {"status": "error", "detail": detail}
            except requests.exceptions.RequestException as error:
                summary["ghidraaas"] = {"status": "error", "detail": str(error)}

        if self.sandbox_client is not None and self.sandbox_client.configured:
            try:
                runner_payload = self.sandbox_client.request("DELETE", f"/jobs/{job_id}", timeout=20)
                summary["sandbox_runner"] = {"status": "deleted", **runner_payload}
            except Exception as error:
                summary["sandbox_runner"] = {"status": "error", "detail": str(error)}

        summary["local"] = self.delete_local_job(job_id)
        return summary

    def get_status(self, job_id, cached_triage):
        metadata = self.job_store.load_job_metadata()
        try:
            return resolve_job_status(
                job_id=job_id,
                metadata=metadata,
                cached_triage=cached_triage,
                fetch_projects=self.ghidra_client.list_projects,
                ghidra_base=self.ghidra_base,
                response_error_details=self.response_error_details,
            ), 200
        except requests.Timeout:
            if job_id in metadata:
                return {
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                    "warning": "Ghidraaas is still busy processing this sample.",
                }, 200
            return {"job_id": job_id, "status": "pending"}, 200
        except requests.HTTPError as error:
            if job_id in metadata:
                return {
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                }, 200
            return {"job_id": job_id, "status": "error", "error": str(error)}, 502
        except requests.exceptions.RequestException as error:
            if job_id in metadata:
                return {
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                    "warning": f"Ghidraaas is temporarily unavailable: {error}",
                }, 200
            return {"job_id": job_id, "status": "error", "error": str(error)}, 502

    def build_job_record(self, job_id, remote_job=None, metadata=None):
        metadata = metadata if metadata is not None else self.job_store.load_job_metadata()
        entry = metadata.get(job_id, {})
        if not isinstance(entry, dict):
            entry = {"filename": str(entry)}

        record = JobRecord(
            job_id=job_id,
            filename=entry.get("filename"),
            label=entry.get("label"),
            archived=bool(entry.get("archived", False)),
        )
        if remote_job:
            record = replace(
                record,
                status=remote_job.get("status"),
                extra_fields={
                    key: value
                    for key, value in remote_job.items()
                    if key not in {"job_id", "status"}
                },
            )
        return record
