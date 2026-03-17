import requests


class GhidraClient:
    def __init__(self, base_url: str, response_error_details):
        self.base_url = base_url.rstrip("/")
        self.response_error_details = response_error_details

    def list_projects(self, timeout=30):
        response = requests.get(f"{self.base_url}/list_projects/", timeout=timeout)
        if not response.ok:
            raise requests.HTTPError(self.response_error_details(response), response=response)
        payload = response.json() if response.content else {}
        return payload.get("projects", [])

    def analyze_sample(self, filename, file_stream, timeout=600):
        files = {"sample": (filename, file_stream, "application/octet-stream")}
        return requests.post(f"{self.base_url}/analyze_sample/", files=files, timeout=timeout)

    def terminate_analysis(self, job_id, timeout=60):
        return requests.get(f"{self.base_url}/analysis_terminated/{job_id}", timeout=timeout)

    def get_functions_list(self, job_id, timeout=15):
        return requests.get(f"{self.base_url}/get_functions_list/{job_id}", timeout=timeout)
