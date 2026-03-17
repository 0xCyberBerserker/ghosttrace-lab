import re

from reconstruction_record import (
    DraftArtifact,
    HypothesisRecord,
    ReconstructionTarget,
    ValidationPlan,
)


class ReconstructionService:
    def __init__(self, job_store):
        self.job_store = job_store
        self._capability_blueprints = {
            "installer_update": {
                "title": "Installer and update workflow",
                "scope": "subsystem",
                "priority": 10,
                "rationale": "Static evidence suggests installation or update behavior that can be reconstructed as a staged workflow.",
                "evidence_links": ["triage:capability:installer_update"],
            },
            "process_execution": {
                "title": "Process launch chain",
                "scope": "subsystem",
                "priority": 20,
                "rationale": "Execution APIs suggest a focused process-launch path worth reconstructing and validating.",
                "evidence_links": ["triage:capability:process_execution"],
            },
            "filesystem": {
                "title": "Filesystem staging path",
                "scope": "subsystem",
                "priority": 30,
                "rationale": "File APIs suggest a staging or deployment path with clear observable side effects.",
                "evidence_links": ["triage:capability:filesystem"],
            },
            "registry": {
                "title": "Registry and persistence behavior",
                "scope": "subsystem",
                "priority": 35,
                "rationale": "Registry-related behavior should be isolated so it can be explained and validated cleanly.",
                "evidence_links": ["triage:capability:registry"],
            },
            "networking": {
                "title": "Network communication path",
                "scope": "subsystem",
                "priority": 25,
                "rationale": "Network-related evidence suggests a protocol or telemetry path that can be reconstructed at subsystem scope.",
                "evidence_links": ["triage:capability:networking"],
            },
            "services": {
                "title": "Service control path",
                "scope": "subsystem",
                "priority": 40,
                "rationale": "Service-management APIs imply a focused lifecycle path suitable for reconstruction.",
                "evidence_links": ["triage:capability:services"],
            },
            "crypto": {
                "title": "Cryptographic handling path",
                "scope": "subsystem",
                "priority": 45,
                "rationale": "Cryptographic APIs suggest a transformation or protection layer that should be reconstructed separately.",
                "evidence_links": ["triage:capability:crypto"],
            },
            "anti_analysis": {
                "title": "Anti-analysis checks",
                "scope": "subsystem",
                "priority": 50,
                "rationale": "Debugger or anti-analysis checks should be isolated so assumptions remain explicit.",
                "evidence_links": ["triage:capability:anti_analysis"],
            },
        }

    def _slug(self, value):
        slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
        return slug or "target"

    def _dedupe(self, items):
        deduped = []
        seen = set()
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _target_artifact_type(self, target):
        if target.scope == "protocol":
            return "protocol_skeleton"
        if target.scope == "function_cluster":
            return "readable_pseudocode"
        if target.scope == "behavior_chain":
            return "behavior_summary"
        return "implementation_plan"

    def _target_summary_line(self, target, hypotheses):
        if hypotheses:
            lead = hypotheses[0]
            return f"{target.title} is currently modeled as: {lead.claim}"
        return f"{target.title} remains a scoped reconstruction candidate grounded in observed evidence."

    def _target_assumptions(self, target, hypotheses):
        assumptions = [
            "This package is a first-pass reconstruction artifact, not a verified behavioral equivalence claim.",
            "Any generated draft should be validated against runtime evidence before being treated as authoritative.",
        ]
        for hypothesis in hypotheses:
            for missing in hypothesis.missing_evidence:
                assumptions.append(f"Missing evidence still needs confirmation: {missing}.")
        if target.scope == "function_cluster":
            assumptions.append("The priority function cluster may still represent only part of the true control-flow path.")
        return self._dedupe(assumptions)[:12]

    def _draft_body(self, target, hypotheses, triage_report, evidence_payload):
        summary = (triage_report or {}).get("summary", {})
        dynamic_summary = summary.get("dynamic_summary", {}) or self.job_store.summarize_evidence(evidence_payload or {})
        lines = [
            f"# Reconstruction Package: {target.title}",
            "",
            "## Scope",
            f"- Target ID: `{target.target_id}`",
            f"- Scope: `{target.scope}`",
            f"- Status: `{target.status}`",
            "",
            "## Working Summary",
            self._target_summary_line(target, hypotheses),
            "",
            "## Evidence Anchors",
        ]
        for link in self._dedupe(list(target.evidence_links) + [item for record in hypotheses for item in record.supporting_evidence])[:12]:
            lines.append(f"- {link}")
        if len(lines) == 10:
            lines.append("- No explicit evidence links were available yet.")

        lines.extend([
            "",
            "## Reconstruction Notes",
            target.rationale or "This subsystem was selected because the current evidence suggests a bounded, reconstructable behavior path.",
            "",
            "## Draft Outline",
        ])

        if hypotheses:
            for hypothesis in hypotheses:
                lines.extend([
                    f"### {hypothesis.title}",
                    f"- Claim: {hypothesis.claim}",
                    f"- Confidence: {hypothesis.confidence}",
                    f"- Next validation step: {hypothesis.next_step or 'Review this claim manually.'}",
                ])
        else:
            lines.append("- No linked hypotheses were available yet; treat this package as a scaffolding artifact only.")

        lines.extend([
            "",
            "## Runtime Context",
            f"- Dynamic artifacts observed: {dynamic_summary.get('artifact_count', 0)}",
            f"- Artifact types: {', '.join(sorted((dynamic_summary.get('artifact_types') or {}).keys())) or 'none'}",
            "",
            "## Constraints",
            "- Do not label this reconstruction as verified until the validation checklist passes.",
            "- Keep the subsystem boundary narrow and observable.",
        ])
        return "\n".join(lines)

    def _validation_checks_for_target(self, target, hypotheses, triage_report, evidence_payload):
        checks = [
            {
                "label": "Reconfirm subsystem boundary",
                "expected": "The selected target still maps to a bounded behavior path rather than whole-program behavior.",
                "method": "triage review",
                "status": "pending",
            }
        ]
        target_id = target.target_id
        if target_id == "target-process-execution":
            checks.append({
                "label": "Compare child process chain",
                "expected": "Observed child processes match the hypothesized launch chain.",
                "method": "sandbox process trace",
                "status": "pending",
            })
        if target_id == "target-filesystem" or "installer" in target_id or "update" in target_id:
            checks.append({
                "label": "Compare file staging behavior",
                "expected": "Observed file paths and write ordering match the staged workflow.",
                "method": "sandbox file trace",
                "status": "pending",
            })
        if target_id == "target-registry":
            checks.append({
                "label": "Compare registry activity",
                "expected": "Registry keys and values line up with the persistence or configuration hypothesis.",
                "method": "sandbox registry trace",
                "status": "pending",
            })
        if target_id == "target-networking" or target_id == "target-network-endpoints":
            checks.append({
                "label": "Compare outbound hosts or protocol fields",
                "expected": "Observed network activity matches the reconstructed endpoint or protocol surface.",
                "method": "sandbox network trace",
                "status": "pending",
            })
        if target.scope == "function_cluster":
            checks.append({
                "label": "Correlate priority function with runtime behavior",
                "expected": "Breakpoint or trace evidence confirms the function cluster participates in the suspected control flow.",
                "method": "x64dbg breakpoint review",
                "status": "pending",
            })
        if target.scope == "behavior_chain":
            checks.append({
                "label": "Replay observed runtime sequence",
                "expected": "The observed runtime artifacts reproduce in the same order under controlled conditions.",
                "method": "sandbox rerun",
                "status": "pending",
            })

        for hypothesis in hypotheses:
            if hypothesis.next_step:
                checks.append({
                    "label": hypothesis.title,
                    "expected": hypothesis.claim,
                    "method": hypothesis.next_step,
                    "status": "pending",
                })
        return checks[:10]

    def _validation_risks_for_target(self, target, hypotheses):
        risks = [
            "This package is evidence-grounded but still incomplete until runtime comparison closes the remaining gaps.",
        ]
        for hypothesis in hypotheses:
            if hypothesis.confidence == "low":
                risks.append(f"Low-confidence hypothesis still present: {hypothesis.title}.")
            for missing in hypothesis.missing_evidence:
                risks.append(f"Missing evidence: {missing}.")
        if target.scope == "protocol":
            risks.append("Protocol assumptions may drift if string references are decoys rather than live endpoints.")
        return self._dedupe(risks)[:12]

    def _target_hypothesis_payloads(self, target, triage_report, evidence_payload):
        summary = (triage_report or {}).get("summary", {})
        dynamic_summary = summary.get("dynamic_summary", {}) or self.job_store.summarize_evidence(evidence_payload or {})
        priority_functions = (summary.get("functions_summary", {}) or {}).get("priority_functions", [])
        function_name = priority_functions[0].get("name") if priority_functions else "priority function cluster"

        target_id = target.target_id
        common = {
            "job_id": target.job_id,
            "target_id": target_id,
        }

        if target_id == "target-installer-update" or "installer" in target_id or "update" in target_id:
            return [
                {
                    **common,
                    "hypothesis_id": f"hyp-{self._slug(target_id)}-staging",
                    "title": "Stages assets before launch",
                    "claim": "The installer path likely stages files or prerequisites before invoking a second execution phase.",
                    "confidence": "medium",
                    "supporting_evidence": list(target.evidence_links) + ["triage:imports:filesystem", "triage:imports:process_execution"],
                    "missing_evidence": ["dynamic:file-write-trace", "dynamic:child-process-trace"],
                    "next_step": "Trace file writes and child-process creation during initial execution.",
                }
            ]

        if target_id == "target-process-execution":
            return [
                {
                    **common,
                    "hypothesis_id": "hyp-process-execution-launch-chain",
                    "title": "Launches a secondary process chain",
                    "claim": "The sample likely pivots into one or more child processes after initial setup or gating logic.",
                    "confidence": "medium",
                    "supporting_evidence": list(target.evidence_links) + ["triage:imports:CreateProcess", f"triage:function:{function_name}"],
                    "missing_evidence": ["dynamic:process-tree", "dynamic:command-line-capture"],
                    "next_step": "Capture process creation events and correlate them with the priority function cluster.",
                }
            ]

        if target_id == "target-filesystem":
            return [
                {
                    **common,
                    "hypothesis_id": "hyp-filesystem-staging",
                    "title": "Writes staged payloads or config",
                    "claim": "The filesystem path likely creates or updates files that support execution, installation, or persistence.",
                    "confidence": "medium",
                    "supporting_evidence": list(target.evidence_links) + ["triage:imports:CreateFile", "triage:imports:WriteFile"],
                    "missing_evidence": ["dynamic:file-write-trace"],
                    "next_step": "Collect runtime file activity and compare write destinations with interesting strings.",
                }
            ]

        if target_id == "target-registry":
            return [
                {
                    **common,
                    "hypothesis_id": "hyp-registry-persistence",
                    "title": "Touches persistence-oriented registry keys",
                    "claim": "The registry path likely reads or writes keys related to installation state, configuration, or persistence.",
                    "confidence": "medium",
                    "supporting_evidence": list(target.evidence_links) + ["triage:imports:registry"],
                    "missing_evidence": ["dynamic:registry-trace"],
                    "next_step": "Trace registry activity and compare affected paths against strings and triage capabilities.",
                }
            ]

        if target_id == "target-networking":
            return [
                {
                    **common,
                    "hypothesis_id": "hyp-networking-telemetry",
                    "title": "Implements a bounded network routine",
                    "claim": "The networking path likely performs telemetry, update checks, or remote communication through a small set of endpoints.",
                    "confidence": "medium",
                    "supporting_evidence": list(target.evidence_links) + ["triage:imports:networking"],
                    "missing_evidence": ["dynamic:network-trace", "dynamic:dns-trace"],
                    "next_step": "Capture network events and compare outbound hosts with interesting URL strings.",
                }
            ]

        if target_id == "target-network-endpoints":
            return [
                {
                    **common,
                    "hypothesis_id": "hyp-network-endpoints-url-map",
                    "title": "Interesting strings define the remote surface",
                    "claim": "The URL strings likely map directly to update, telemetry, or activation endpoints used by the binary.",
                    "confidence": "medium",
                    "supporting_evidence": list(target.evidence_links),
                    "missing_evidence": ["dynamic:http-trace"],
                    "next_step": "Validate which URL-like strings appear in actual runtime traffic or request construction code.",
                }
            ]

        if target_id.startswith("target-function-"):
            return [
                {
                    **common,
                    "hypothesis_id": f"hyp-{self._slug(target_id)}-control-flow",
                    "title": "Priority function anchors the main control flow",
                    "claim": "This priority function cluster likely orchestrates the most relevant behavior chain for first-pass reconstruction.",
                    "confidence": "low",
                    "supporting_evidence": list(target.evidence_links),
                    "missing_evidence": ["decompilation:manual-review", "dynamic:breakpoint-context"],
                    "next_step": "Decompile the function cluster and compare its control flow against runtime observations.",
                }
            ]

        if target_id == "target-dynamic-behavior-chain":
            artifact_types = ", ".join(sorted((dynamic_summary.get("artifact_types") or {}).keys())[:4]) or "runtime artifacts"
            return [
                {
                    **common,
                    "hypothesis_id": "hyp-dynamic-behavior-chain-runtime",
                    "title": "Dynamic artifacts reflect the core behavior chain",
                    "claim": f"The observed {artifact_types} likely describe the shortest path to a behavior-first reconstruction of the sample.",
                    "confidence": "high" if dynamic_summary.get("artifact_count", 0) > 1 else "medium",
                    "supporting_evidence": list(target.evidence_links),
                    "missing_evidence": ["triage:function-correlation"],
                    "next_step": "Map the observed runtime behavior back to the priority functions and imports.",
                }
            ]

        return [
            {
                **common,
                "hypothesis_id": f"hyp-{self._slug(target_id)}-baseline",
                "title": "Subsystem needs scoped reconstruction",
                "claim": "This target should be reconstructed as an isolated subsystem before broader behavioral claims are made.",
                "confidence": "low",
                "supporting_evidence": list(target.evidence_links),
                "missing_evidence": ["manual:subsystem-review"],
                "next_step": "Review linked evidence and define the narrowest observable behavior for this subsystem.",
            }
        ]

    def list_bundle(self, job_id):
        return {
            "job_id": job_id,
            "targets": [target.to_dict() for target in self.job_store.list_reconstruction_targets(job_id)],
            "hypotheses": [record.to_dict() for record in self.job_store.list_hypotheses(job_id)],
            "draft_artifacts": [artifact.to_dict() for artifact in self.job_store.list_draft_artifacts(job_id)],
            "validation_plans": [plan.to_dict() for plan in self.job_store.list_validation_plans(job_id)],
        }

    def save_target(self, job_id, payload):
        target = ReconstructionTarget(job_id=job_id, **payload)
        self.job_store.save_reconstruction_target(target)
        return target

    def save_hypothesis(self, job_id, payload):
        record = HypothesisRecord(job_id=job_id, **payload)
        self.job_store.save_hypothesis(record)
        return record

    def save_draft_artifact(self, job_id, payload):
        artifact = DraftArtifact(job_id=job_id, **payload)
        self.job_store.save_draft_artifact(artifact)
        return artifact

    def save_validation_plan(self, job_id, payload):
        plan = ValidationPlan(job_id=job_id, **payload)
        self.job_store.save_validation_plan(plan)
        return plan

    def get_target(self, job_id, target_id):
        for target in self.job_store.list_reconstruction_targets(job_id):
            if target.target_id == target_id:
                return target
        return None

    def get_draft_artifact(self, job_id, artifact_id):
        for artifact in self.job_store.list_draft_artifacts(job_id):
            if artifact.artifact_id == artifact_id:
                return artifact
        return None

    def export_draft_bundle(self, job_id, artifact_id):
        artifact = self.get_draft_artifact(job_id, artifact_id)
        if artifact is None:
            return None
        target = self.get_target(job_id, artifact.target_id) if artifact.target_id else None
        hypotheses = [
            record for record in self.job_store.list_hypotheses(job_id)
            if not artifact.target_id or record.target_id == artifact.target_id
        ]
        plans = [
            plan for plan in self.job_store.list_validation_plans(job_id)
            if not artifact.target_id or plan.target_id == artifact.target_id
        ]
        return {
            "artifact": artifact.to_dict(),
            "target": target.to_dict() if target else None,
            "hypotheses": [record.to_dict() for record in hypotheses],
            "validation_plans": [plan.to_dict() for plan in plans],
        }

    def generate_targets(self, job_id, triage_report, evidence_payload):
        summary = (triage_report or {}).get("summary", {})
        capabilities = summary.get("capabilities", []) or []
        strings_summary = summary.get("strings_summary", {}) or {}
        functions_summary = summary.get("functions_summary", {}) or {}
        dynamic_summary = summary.get("dynamic_summary", {}) or self.job_store.summarize_evidence(evidence_payload or {})

        generated_targets = []
        seen_ids = {target.target_id for target in self.job_store.list_reconstruction_targets(job_id)}

        for capability in capabilities:
            blueprint = self._capability_blueprints.get(capability)
            if not blueprint:
                continue
            target_id = f"target-{self._slug(capability)}"
            target = ReconstructionTarget(
                target_id=target_id,
                job_id=job_id,
                title=blueprint["title"],
                scope=blueprint["scope"],
                status="proposed",
                rationale=blueprint["rationale"],
                priority=blueprint["priority"],
                evidence_links=list(blueprint["evidence_links"]),
            )
            self.job_store.save_reconstruction_target(target)
            generated_targets.append(target)
            seen_ids.add(target_id)

        interesting_strings = strings_summary.get("interesting_strings", {})
        if interesting_strings.get("urls") and "target-network-endpoints" not in seen_ids:
            target = ReconstructionTarget(
                target_id="target-network-endpoints",
                job_id=job_id,
                title="Endpoint and protocol surface",
                scope="protocol",
                status="proposed",
                rationale="Interesting URL strings suggest a bounded network or telemetry surface that can be reconstructed separately.",
                priority=22,
                evidence_links=["triage:strings:urls"],
            )
            self.job_store.save_reconstruction_target(target)
            generated_targets.append(target)
            seen_ids.add(target.target_id)

        priority_functions = functions_summary.get("priority_functions", [])
        if priority_functions:
            top_function = priority_functions[0]
            function_name = top_function.get("name") or top_function.get("address") or "priority-function"
            target_id = f"target-function-{self._slug(function_name)}"
            if target_id not in seen_ids:
                target = ReconstructionTarget(
                    target_id=target_id,
                    job_id=job_id,
                    title=f"Priority function cluster: {function_name}",
                    scope="function_cluster",
                    status="proposed",
                    rationale="The triage report identified this function cluster as a high-signal place to anchor a first reconstruction pass.",
                    priority=55,
                    evidence_links=[f"triage:function:{function_name}"],
                )
                self.job_store.save_reconstruction_target(target)
                generated_targets.append(target)
                seen_ids.add(target_id)

        artifact_types = dynamic_summary.get("artifact_types", {})
        if artifact_types and "target-dynamic-behavior-chain" not in seen_ids:
            artifact_labels = ", ".join(sorted(artifact_types.keys())[:4])
            target = ReconstructionTarget(
                target_id="target-dynamic-behavior-chain",
                job_id=job_id,
                title="Observed runtime behavior chain",
                scope="behavior_chain",
                status="proposed",
                rationale=f"Dynamic evidence already exists ({artifact_labels}) and can anchor a behavior-first reconstruction target.",
                priority=18,
                evidence_links=["dynamic:artifacts"],
            )
            self.job_store.save_reconstruction_target(target)
            generated_targets.append(target)

        return [target.to_dict() for target in self.job_store.list_reconstruction_targets(job_id)]

    def generate_hypotheses(self, job_id, triage_report, evidence_payload):
        targets = self.job_store.list_reconstruction_targets(job_id)
        existing_ids = {record.hypothesis_id for record in self.job_store.list_hypotheses(job_id)}

        for target in targets:
            for payload in self._target_hypothesis_payloads(target, triage_report, evidence_payload):
                if payload["hypothesis_id"] in existing_ids:
                    continue
                record = HypothesisRecord(**payload)
                self.job_store.save_hypothesis(record)
                existing_ids.add(record.hypothesis_id)

        return [record.to_dict() for record in self.job_store.list_hypotheses(job_id)]

    def generate_drafts(self, job_id, triage_report, evidence_payload, target_id=None):
        targets = self.job_store.list_reconstruction_targets(job_id)
        if target_id:
            targets = [target for target in targets if target.target_id == target_id]
        hypothesis_records = self.job_store.list_hypotheses(job_id)
        existing_ids = {artifact.artifact_id for artifact in self.job_store.list_draft_artifacts(job_id)}

        for target in targets:
            related_hypotheses = [record for record in hypothesis_records if record.target_id == target.target_id]
            artifact_id = f"draft-{self._slug(target.target_id)}-package"
            if artifact_id in existing_ids:
                continue
            artifact = DraftArtifact(
                artifact_id=artifact_id,
                job_id=job_id,
                target_id=target.target_id,
                title=f"{target.title} reconstruction package",
                artifact_type=self._target_artifact_type(target),
                summary=self._target_summary_line(target, related_hypotheses),
                body=self._draft_body(target, related_hypotheses, triage_report, evidence_payload),
                evidence_links=self._dedupe(list(target.evidence_links) + [item for record in related_hypotheses for item in record.supporting_evidence])[:20],
                assumptions=self._target_assumptions(target, related_hypotheses),
                validation_status="needs_validation",
            )
            self.job_store.save_draft_artifact(artifact)
            existing_ids.add(artifact.artifact_id)

        return [artifact.to_dict() for artifact in self.job_store.list_draft_artifacts(job_id)]

    def generate_validation_plans(self, job_id, triage_report, evidence_payload, target_id=None):
        targets = self.job_store.list_reconstruction_targets(job_id)
        if target_id:
            targets = [target for target in targets if target.target_id == target_id]
        hypothesis_records = self.job_store.list_hypotheses(job_id)
        existing_ids = {plan.plan_id for plan in self.job_store.list_validation_plans(job_id)}

        for target in targets:
            related_hypotheses = [record for record in hypothesis_records if record.target_id == target.target_id]
            plan_id = f"plan-{self._slug(target.target_id)}-validation"
            if plan_id in existing_ids:
                continue
            plan = ValidationPlan(
                plan_id=plan_id,
                job_id=job_id,
                target_id=target.target_id,
                title=f"{target.title} validation plan",
                checks=self._validation_checks_for_target(target, related_hypotheses, triage_report, evidence_payload),
                open_risks=self._validation_risks_for_target(target, related_hypotheses),
                status="draft",
            )
            self.job_store.save_validation_plan(plan)
            existing_ids.add(plan.plan_id)

        return [plan.to_dict() for plan in self.job_store.list_validation_plans(job_id)]
