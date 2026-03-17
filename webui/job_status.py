import requests


def resolve_job_status(job_id, metadata, cached_triage, fetch_projects, ghidra_base, response_error_details):
    if cached_triage:
        triage_status = cached_triage.get("status")
        if triage_status == "completed":
            return {
                "job_id": job_id,
                "status": "done",
                "phase": "triage_ready",
            }
        if triage_status in {"queued", "processing"}:
            return {
                "job_id": job_id,
                "status": "analyzing",
                "phase": "triage_building",
            }

    try:
        projects = fetch_projects(timeout=10)
        project_exists = any(project.get("job_id") == job_id for project in projects)

        if project_exists:
            try:
                functions_response = requests.get(
                    f"{ghidra_base}/get_functions_list/{job_id}",
                    timeout=15,
                )
                if functions_response.status_code == 200:
                    return {
                        "job_id": job_id,
                        "status": "done",
                        "phase": "function_index_ready",
                    }
                if functions_response.status_code == 202:
                    return {
                        "job_id": job_id,
                        "status": "analyzing",
                        "phase": "function_indexing",
                    }
                if functions_response.status_code == 400:
                    return {
                        "job_id": job_id,
                        "status": "analyzing",
                        "phase": "ghidra_processing",
                    }
                return {
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                    "warning": response_error_details(functions_response),
                }
            except requests.Timeout:
                return {
                    "job_id": job_id,
                    "status": "analyzing",
                    "phase": "ghidra_processing",
                    "warning": "Ghidraaas is still processing this sample.",
                }

        if job_id in metadata:
            return {
                "job_id": job_id,
                "status": "analyzing",
                "phase": "uploaded",
            }

        return {"job_id": job_id, "status": "pending"}
    except requests.Timeout:
        if job_id in metadata:
            return {
                "job_id": job_id,
                "status": "analyzing",
                "phase": "ghidra_processing",
                "warning": "Ghidraaas is still busy processing this sample.",
            }
        return {"job_id": job_id, "status": "pending"}
    except requests.HTTPError as error:
        response = getattr(error, "response", None)
        if response is not None and response.status_code == 400:
            response_text = response.text.strip()
            if "Sample has not been analyzed" in response_text:
                return {"job_id": job_id, "status": "pending"}

        if job_id in metadata:
            return {
                "job_id": job_id,
                "status": "analyzing",
                "phase": "ghidra_processing",
            }
        raise
    except requests.exceptions.RequestException:
        raise
