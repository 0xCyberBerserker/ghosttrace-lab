import requests


class SandboxClient:
    def __init__(self, base_url: str | None, response_error_details, auth_token: str | None = None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.response_error_details = response_error_details
        self.auth_token = auth_token

    def _headers(self, extra_headers=None):
        headers = {}
        if self.auth_token:
            headers["X-Internal-Token"] = self.auth_token
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @property
    def configured(self):
        return bool(self.base_url)

    def request(self, method: str, path: str, **kwargs):
        if not self.base_url:
            raise RuntimeError("SANDBOX_RUNNER_URL is not configured.")

        response = requests.request(
            method=method,
            url=self.base_url + path,
            timeout=kwargs.pop("timeout", 30),
            headers=self._headers(kwargs.pop("headers", None)),
            **kwargs,
        )
        if not response.ok:
            raise requests.HTTPError(self.response_error_details(response), response=response)
        return response.json() if response.content else {}

    def trigger_run(self, job_id: str, filename: str, timeout=10):
        if not self.base_url:
            return
        payload = {
            "job_id": job_id,
            "filename": filename,
        }
        try:
            requests.post(
                self.base_url + "/run",
                json=payload,
                timeout=timeout,
                headers=self._headers(),
            )
        except requests.exceptions.RequestException:
            return

    def safe_x64dbg_snapshot(self, job_id):
        if not self.base_url:
            return {
                "state": {"status": "unavailable"},
                "findings": {"findings": []},
                "requests": {"requests": []},
            }

        snapshot = {
            "state": {"status": "idle"},
            "findings": {"findings": []},
            "requests": {"requests": []},
        }
        try:
            snapshot["state"] = self.request("GET", f"/jobs/{job_id}/x64dbg", timeout=10)
        except Exception:
            pass
        try:
            snapshot["findings"] = self.request("GET", f"/jobs/{job_id}/x64dbg/findings", timeout=10)
        except Exception:
            pass
        try:
            snapshot["requests"] = self.request("GET", f"/jobs/{job_id}/x64dbg/requests", timeout=10)
        except Exception:
            pass
        return snapshot
