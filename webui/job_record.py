from dataclasses import dataclass, field


@dataclass
class JobRecord:
    job_id: str
    status: str | None = None
    filename: str | None = None
    label: str | None = None
    archived: bool = False
    extra_fields: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.label or self.filename or f"{self.job_id[:8]}.bin"

    def to_dict(self) -> dict:
        payload = {
            **self.extra_fields,
            "job_id": self.job_id,
            "filename": self.filename,
            "label": self.label,
            "archived": self.archived,
            "display_name": self.display_name,
        }
        if self.status is not None:
            payload["status"] = self.status
        return payload
