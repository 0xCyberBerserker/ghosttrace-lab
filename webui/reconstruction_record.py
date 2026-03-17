from dataclasses import dataclass, field


@dataclass
class ReconstructionTarget:
    target_id: str
    job_id: str
    title: str
    scope: str
    status: str = "proposed"
    rationale: str = ""
    priority: int = 50
    evidence_links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "job_id": self.job_id,
            "title": self.title,
            "scope": self.scope,
            "status": self.status,
            "rationale": self.rationale,
            "priority": self.priority,
            "evidence_links": list(self.evidence_links),
        }


@dataclass
class HypothesisRecord:
    hypothesis_id: str
    job_id: str
    target_id: str | None
    title: str
    claim: str
    confidence: str = "medium"
    supporting_evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    next_step: str = ""

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "job_id": self.job_id,
            "target_id": self.target_id,
            "title": self.title,
            "claim": self.claim,
            "confidence": self.confidence,
            "supporting_evidence": list(self.supporting_evidence),
            "missing_evidence": list(self.missing_evidence),
            "next_step": self.next_step,
        }


@dataclass
class DraftArtifact:
    artifact_id: str
    job_id: str
    target_id: str | None
    title: str
    artifact_type: str
    summary: str = ""
    body: str = ""
    evidence_links: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    validation_status: str = "draft"

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "job_id": self.job_id,
            "target_id": self.target_id,
            "title": self.title,
            "artifact_type": self.artifact_type,
            "summary": self.summary,
            "body": self.body,
            "evidence_links": list(self.evidence_links),
            "assumptions": list(self.assumptions),
            "validation_status": self.validation_status,
        }


@dataclass
class ValidationPlan:
    plan_id: str
    job_id: str
    target_id: str | None
    title: str
    checks: list[dict] = field(default_factory=list)
    open_risks: list[str] = field(default_factory=list)
    status: str = "draft"

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "job_id": self.job_id,
            "target_id": self.target_id,
            "title": self.title,
            "checks": list(self.checks),
            "open_risks": list(self.open_risks),
            "status": self.status,
        }
