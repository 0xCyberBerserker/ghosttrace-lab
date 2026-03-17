import hashlib

from werkzeug.utils import secure_filename


class JobWorkflow:
    def __init__(self, job_store, job_service, ghidra_client, sandbox_client, queue_triage_report):
        self.job_store = job_store
        self.job_service = job_service
        self.ghidra_client = ghidra_client
        self.sandbox_client = sandbox_client
        self.queue_triage_report = queue_triage_report

    def compute_job_id(self, file_storage):
        file_storage.stream.seek(0)
        sha256_hash = hashlib.sha256()
        for chunk in iter(lambda: file_storage.stream.read(4096), b""):
            sha256_hash.update(chunk)
        file_storage.stream.seek(0)
        return sha256_hash.hexdigest()

    def sanitize_filename(self, filename, job_id):
        safe_name = secure_filename(filename or "")
        return safe_name or f"{job_id[:8]}.bin"

    def reset_job_runtime(self, job_id):
        self.job_store.reset_local_job_runtime_artifacts(job_id)
        if self.sandbox_client.configured:
            try:
                self.sandbox_client.request("DELETE", f"/jobs/{job_id}", timeout=15)
            except Exception:
                pass

    def queue_follow_up_tasks(self, job_id, filename):
        self.sandbox_client.trigger_run(job_id, filename, timeout=10)
        self.queue_triage_report(job_id, filename)

    def upload_and_analyze(self, file_storage):
        job_id = self.compute_job_id(file_storage)
        filename = self.sanitize_filename(file_storage.filename, job_id)

        self.reset_job_runtime(job_id)
        self.job_store.save_uploaded_sample(job_id, file_storage)

        file_storage.stream.seek(0)
        response = self.ghidra_client.analyze_sample(filename, file_storage.stream, timeout=600)
        if not response.ok:
            return response, job_id, filename

        self.job_service.record_uploaded_job(job_id, filename)
        self.queue_follow_up_tasks(job_id, filename)
        return response, job_id, filename
