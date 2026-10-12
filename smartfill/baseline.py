"""Rule baseline: only TaskInput and its declared physical materials are read."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter

from .contracts import FillingResult, TaskInput
from .integrity import require, verify_artifacts
from .parsing import LABELS, discover_form, parse_references

VERSION = "rule-baseline-0.1.0"


def extract_sources(parsed):
    evidence, facts, blocked = [], [], defaultdict(set)
    for document in parsed:
        project = None
        for segment in document["segments"]:
            match = re.search(r"访问项目编号[:：]\s*(\d+)", segment["text"])
            if match:
                project = match[1]
        for segment in document["segments"]:
            line = segment["text"]
            match = re.fullmatch(r"([^:：]+)[:：]\s*(.+)", line)
            if not match or match[1].strip() not in LABELS:
                continue
            key, kind = LABELS[match[1].strip()]
            if key.startswith("visit."):
                require(project is not None, "visit material has no explicit project number")
                key = "visit." + project + "." + key.split(".")[1]
            raw = match[2]
            start = match.start(2)
            eid = f"evidence-{len(evidence) + 1:04d}"
            evidence.append({"evidence_id": eid, "document_id": document["document_id"],
                             "segment_id": segment["segment_id"], "locator": segment["locator"],
                             "quote": raw, "start": start, "end": start + len(raw), "origin": "parser"})
            value = raw
            if kind == "date":
                value = None
                for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        value = datetime.strptime(raw, fmt).date().isoformat()
                        break
                    except ValueError:
                        pass
                if value is None:
                    blocked[key].add(document["document_id"])
                    continue
            facts.append({"fact_id": f"fact-{len(facts) + 1:04d}", "entity_id": "task-person",
                          "predicate": key, "raw_value": raw, "normalized_value": {"kind": kind, "value": value},
                          "evidence_ids": [eid]})
    # Bilingual normalization requires one unambiguous, explicit mapping in visible material.
    aliases = defaultdict(list)
    for fact in facts:
        if fact["predicate"] in ("alias_zh", "alias_en"):
            aliases[fact["predicate"]].append(fact)
    if aliases:
        require(len(aliases["alias_zh"]) == len(aliases["alias_en"]) == 1, "ambiguous visible name aliases")
        zh, en = aliases["alias_zh"][0], aliases["alias_en"][0]
        by_id = {e["evidence_id"]: e for e in evidence}
        mapping_docs = {by_id[e]["document_id"] for f in (zh, en) for e in f["evidence_ids"]}
        require(len(mapping_docs) == 1 and any(
            d["document_id"] in mapping_docs and any("统一采用英文姓名" in s["text"] for s in d["segments"])
            for d in parsed), "visible alias output convention is missing")
        for fact in facts:
            if fact["predicate"] == "name" and fact["raw_value"] == zh["raw_value"]:
                fact["normalized_value"] = en["normalized_value"].copy()
                fact["evidence_ids"] = list(dict.fromkeys(fact["evidence_ids"] + zh["evidence_ids"] + en["evidence_ids"]))
    return evidence, facts, blocked


def fill_task(directory: Path, run_id: str = "rule-baseline") -> FillingResult:
    root = directory.resolve(strict=True)
    task = TaskInput.model_validate_json((root / "input.json").read_bytes())
    started = perf_counter()
    timings = {}
    stage = "input"

    def elapsed():
        return (perf_counter() - started) * 1000

    def finish(payload):
        payload.update({"task_id": task.task_id, "run_id": run_id, "task_input": task.model_dump(mode="json"),
                        "timing": {"total_ms": elapsed(), "stages_ms": timings},
                        "run_metadata": {"implementation_version": VERSION, "mode": "rule_baseline"}})
        return FillingResult.model_validate_json(json.dumps(payload))

    try:
        require(all(d.relative_path.startswith("documents/") for d in task.documents),
                "baseline reads only declared documents/ materials")
        verify_artifacts(task, root)
        timings["input"] = elapsed()
        stage, previous = "parse", perf_counter()
        target = next(d for d in task.documents if d.document_id == task.target_document_id)
        form, parsed_target = discover_form(target, root / target.relative_path)
        references = parse_references(task, root)
        parsed = [parsed_target] + references
        timings["parse"] = (perf_counter() - previous) * 1000
        stage, previous = "extraction", perf_counter()
        require("同一出访人员" in task.description, "single-person scope must be explicitly declared")
        evidence, facts, blocked = extract_sources(references)
        timings["extraction"] = (perf_counter() - previous) * 1000
        stage, previous = "validation", perf_counter()
        declared = {r.rule_id: (r.kind, r.version) for r in task.rules}
        require(task.ruleset_id == "sim-travel" and task.ruleset_version == "1" and declared == {
            "sim-days": ("date_days_inclusive", "1"), "sim-consistency": ("consistency", "1"),
            "sim-visa-coverage": ("consistency", "1")}, "unsupported rule profile")
        by_key = defaultdict(list)
        for fact in facts:
            by_key[fact["predicate"]].append(fact)
        candidate_list, results, issues, requests = [], [], [], []
        evidence_index = {e["evidence_id"]: e for e in evidence}

        def issue(field, code, status, docs=()):
            iid = f"issue-{len(issues) + 1:04d}"
            issues.append({"issue_id": iid, "code": code, "severity": "error",
                           "message": f'{field["label"]}: {code}', "field_ids": [field["field_id"]],
                           "document_ids": sorted(set(docs)),
                           "rule_id": "sim-visa-coverage" if code in ("visa_range_mismatch", "upstream_conflict") else
                                      "sim-days" if code.startswith("missing_calculation") else "sim-consistency"})
            requests.append({"field_id": field["field_id"], "action": "request_documents" if status == "missing"
                             else "request_confirmation", "message": f'{field["label"]}: {code}'})
            return [iid]

        for field in form["fields"]:
            key = field["semantic_key"]
            if key and key.startswith("visit.") and field["row_id"]:
                key = "visit." + field["row_id"].removeprefix("project-") + "." + key.split(".")[1]
            source = by_key[key] if key else []
            candidates = []
            if key != "days":
                for fact in source:
                    candidate = {"candidate_id": f"candidate-{len(candidate_list) + 1:04d}",
                                 "field_id": field["field_id"], "fact_ids": [fact["fact_id"]],
                                 "value": fact["normalized_value"], "evidence_ids": fact["evidence_ids"], "method": "rule"}
                    candidate_list.append(candidate)
                    candidates.append(candidate)
            distinct = {json.dumps(c["value"], sort_keys=True) for c in candidates}
            status = "missing" if not candidates else ("conflict" if len(distinct) > 1 else "verified")
            code = "missing_source" if status == "missing" else "source_conflict"
            if key is None or (key.startswith("visit.") and not field["row_id"]):
                status, code = "review_required", "unmapped_field"
            if blocked.get(key):
                status, code = "review_required", "invalid_source_format"
            derivation = None
            if key == "days":
                inputs = [by_key[k][0] for k in ("departure", "return") if by_key[k]]
                if blocked.get("departure") or blocked.get("return"):
                    status, code = "review_required", "upstream_conflict"
                elif len(inputs) < 2:
                    status, code = "missing", "missing_calculation_input"
                elif any(len({json.dumps(f["normalized_value"], sort_keys=True) for f in by_key[k]}) != 1
                         for k in ("departure", "return")) or blocked.get("departure") or blocked.get("return"):
                    status, code = "review_required", "upstream_conflict"
                else:
                    a, b = [datetime.fromisoformat(f["normalized_value"]["value"]).date() for f in inputs]
                    days = (b - a).days + 1
                    if days <= 0:
                        status, code = "review_required", "invalid_date_order"
                    else:
                        status = "verified"
                        # Consolidate equal normalized inputs while retaining every source.
                        # Original source facts/candidates remain independent.
                        inputs = []
                        for semantic in ("departure", "return"):
                            copies = by_key[semantic]
                            combined = dict(copies[0], fact_id=f"fact-{len(facts) + 1:04d}",
                                            evidence_ids=list(dict.fromkeys(
                                                e for f in copies for e in f["evidence_ids"])))
                            facts.append(combined)
                            inputs.append(combined)
                        derivation = {"rule_id": "sim-days", "rule_version": "1",
                                      "input_fact_ids": [f["fact_id"] for f in inputs],
                                      "output": {"kind": "integer", "value": days}, "unit": "days"}
            coverage = []
            for semantic in ("departure", "return", "visa_start", "visa_end"):
                values = by_key[semantic]
                if not values or blocked.get(semantic) or len({json.dumps(f["normalized_value"], sort_keys=True) for f in values}) != 1:
                    break
                coverage.append(values[0])
            if len(coverage) == 4 and key in ("return", "days"):
                a, b, c, d = [datetime.fromisoformat(f["normalized_value"]["value"]).date() for f in coverage]
                if not (c <= a <= b <= d):
                    status, code = ("conflict", "visa_range_mismatch") if key == "return" else ("review_required", "upstream_conflict")
                    derivation = None
            source_ids = {e for c in candidates for e in c["evidence_ids"]}
            if derivation:
                source_ids.update(e for f in inputs for e in f["evidence_ids"])
            documents = {evidence_index[e]["document_id"] for e in source_ids}
            documents.update(blocked.get(key, ()))
            if code in ("visa_range_mismatch", "upstream_conflict"):
                documents.update(evidence_index[e]["document_id"] for f in coverage for e in f["evidence_ids"])
            results.append({"field_id": field["field_id"], "candidate_ids": [c["candidate_id"] for c in candidates],
                            "selected_candidate_id": candidates[0]["candidate_id"] if status == "verified" and candidates else None,
                            "suggested_value": (derivation["output"] if derivation else candidates[0]["value"])
                            if status == "verified" else None, "status": status,
                            "evidence_ids": sorted(source_ids),
                            "issue_ids": [] if status == "verified" else issue(field, code, status, documents),
                            "derivation": derivation})
        timings["validation"] = (perf_counter() - previous) * 1000
        result = finish({"form_schema": form, "parsed_documents": parsed, "facts": facts, "evidence": evidence,
                        "candidates": candidate_list, "fields": results, "issues": issues,
                        "review_requests": requests, "task_status": "needs_review" if requests else "completed"})
        # Check parsed regions against actual files; no annotation is involved.
        verify_artifacts(task, root, result.parsed_documents)
        timings["validation"] = (perf_counter() - previous) * 1000
        return result.model_copy(update={"timing": result.timing.model_copy(
            update={"total_ms": elapsed(), "stages_ms": dict(timings)})})
    except (OSError, ValueError):
        return finish({"form_schema": None, "task_status": "failed",
                       "errors": [{"stage": stage, "code": "baseline_input_or_profile_error",
                                   "message": "unsupported or invalid material/profile; no filling suggestions emitted"}]})
