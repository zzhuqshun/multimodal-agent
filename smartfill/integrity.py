"""Deterministic cross-reference checks; these do not prove semantic correctness."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, TypeVar

if TYPE_CHECKING:
    from .contracts import FillingResult, GroundTruth, ParsedDocument, TaskInput

T = TypeVar("T")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_index(items: Iterable[T], attribute: str) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        key = getattr(item, attribute)
        require(key not in result, f"duplicate {attribute}: {key}")
        result[key] = item
    return result


def references(ids: list[str], index: dict, label: str) -> None:
    require(len(ids) == len(set(ids)), f"duplicate references in {label}")
    require(all(key in index for key in ids), f"unknown reference in {label}")


def locator_matches_media(locator, document) -> None:
    allowed = {
        "text": {"text/plain"},
        "cell": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        "word_paragraph": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "word_cell": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    }
    if locator.kind == "page":
        valid = document.media_type == "application/pdf" or document.media_type.startswith("image/")
    else:
        valid = document.media_type in allowed[locator.kind]
    require(valid, f"locator kind incompatible with document {document.document_id}")


def locator_contains(outer, inner) -> bool:
    if outer.kind != inner.kind:
        return False
    if outer.kind == "text":
        return outer.line_start <= inner.line_start <= inner.line_end <= outer.line_end
    if outer.kind == "page":
        return (outer.page == inner.page and outer.coordinate_frame == inner.coordinate_frame
                and outer.source_rotation_degrees == inner.source_rotation_degrees
                and outer.source_to_canonical == inner.source_to_canonical
                and outer.bbox[0] <= inner.bbox[0] < inner.bbox[2] <= outer.bbox[2]
                and outer.bbox[1] <= inner.bbox[1] < inner.bbox[3] <= outer.bbox[3])
    if outer.kind == "cell":
        from .contracts import cell_position

        first, last = outer.cell_range.split(":")[0], outer.cell_range.split(":")[-1]
        start, end = inner.cell_range.split(":")[0], inner.cell_range.split(":")[-1]
        a, b, c, d = map(cell_position, (first, last, start, end))
        return outer.sheet == inner.sheet and a[0] <= c[0] <= d[0] <= b[0] and a[1] <= c[1] <= d[1] <= b[1]
    return outer == inner


def validate_result(result: FillingResult) -> None:
    task = result.task_input
    require(result.task_id == task.task_id, "result task_id does not match input")
    documents = unique_index(task.documents, "document_id")
    rules = unique_index(task.rules, "rule_id")
    parsed = unique_index(result.parsed_documents, "document_id")
    for document_id, document in parsed.items():
        require(document_id in documents, "unknown parsed document")
        for segment in document.segments:
            locator_matches_media(segment.locator, documents[document_id])

    form = result.form_schema
    if form is None:
        require(result.task_status == "failed", "only failed tasks may omit FormSchema")
        require(not (result.fields or result.candidates or result.issues or result.review_requests),
                "schema-less failure cannot contain field-level output")
        form_fields = {}
    else:
        require(form.target_document_id == task.target_document_id, "wrong target document")
        form_fields = unique_index(form.fields, "field_id")
        for field in form.fields:
            locator_matches_media(field.target_locator, documents[task.target_document_id])
            references(field.rule_ids, rules, "form field rules")
            if result.task_status != "failed":
                target = parsed.get(task.target_document_id)
                require(target is not None and any(locator_contains(segment.locator, field.target_locator)
                                                   for segment in target.segments),
                        "target field locator has no supporting parsed region")
    evidence = unique_index(result.evidence, "evidence_id")
    facts = unique_index(result.facts, "fact_id")
    candidates = unique_index(result.candidates, "candidate_id")
    fields = unique_index(result.fields, "field_id")
    issues = unique_index(result.issues, "issue_id")

    for source in evidence.values():
        require(source.document_id in parsed, "evidence document has no parsed content")
        require(documents[source.document_id].role == "reference", "value evidence must use reference material")
        segments = unique_index(parsed[source.document_id].segments, "segment_id")
        require(source.segment_id in segments, "unknown evidence segment")
        segment = segments[source.segment_id]
        require(source.locator == segment.locator, "evidence locator differs from source segment")
        require(source.end <= len(segment.text), "evidence span is out of bounds")
        require(segment.text[source.start:source.end] == source.quote, "evidence quote does not match source text")
    for fact in facts.values():
        references(fact.evidence_ids, evidence, "fact evidence")
        require(any(fact.raw_value in evidence[key].quote for key in fact.evidence_ids),
                "fact raw_value is not present in its evidence")
    for candidate in candidates.values():
        require(candidate.field_id in form_fields, "candidate references unknown field")
        references(candidate.fact_ids, facts, "candidate facts")
        references(candidate.evidence_ids, evidence, "candidate evidence")
        expected_sources = {key for fact_id in candidate.fact_ids for key in facts[fact_id].evidence_ids}
        require(set(candidate.evidence_ids) == expected_sources, "candidate evidence does not match fact provenance")
        require(any(candidate.value == facts[key].normalized_value for key in candidate.fact_ids),
                "candidate value differs from all normalized source facts")
        require(candidate.value.kind == form_fields[candidate.field_id].value_type,
                "candidate value type does not match form field")
    for issue in issues.values():
        references(issue.field_ids, form_fields, "issue fields")
        references(issue.document_ids, documents, "issue documents")
        if issue.rule_id is not None:
            require(issue.rule_id in rules, "issue references unknown rule")

    requests: dict[str, list] = {}
    for request in result.review_requests:
        require(request.field_id in fields, "review request references unknown field result")
        requests.setdefault(request.field_id, []).append(request)

    for field_id, field in fields.items():
        require(field_id in form_fields, "result references unknown field")
        references(field.candidate_ids, candidates, "result candidates")
        references(field.evidence_ids, evidence, "result evidence")
        references(field.issue_ids, issues, "result issues")
        expected_candidates = {key for key, c in candidates.items() if c.field_id == field_id}
        require(set(field.candidate_ids) == expected_candidates, "field must retain all and only its own candidates")
        scoped_issues = {key for key, issue in issues.items() if field_id in issue.field_ids}
        require(set(field.issue_ids) == scoped_issues, "field issue references do not match issue scope")
        source_ids = {key for candidate_id in field.candidate_ids for key in candidates[candidate_id].evidence_ids}
        if field.derivation is not None:
            derivation = field.derivation
            require(derivation.rule_id in rules, "unknown derivation rule")
            require(derivation.rule_id in form_fields[field_id].rule_ids, "calculation rule not assigned to field")
            rule = rules[derivation.rule_id]
            require(derivation.rule_version == rule.version, "derivation rule version mismatch")
            references(derivation.input_fact_ids, facts, "derivation inputs")
            source_ids.update(key for fact_id in derivation.input_fact_ids for key in facts[fact_id].evidence_ids)
            require(derivation.output.kind == form_fields[field_id].value_type, "wrong calculation output type")
            # v0.1 supports one explicitly declared simulated calculation, not arbitrary code.
            require(rule.kind == "date_days_inclusive", "unsupported calculation rule")
            inputs = [facts[key].normalized_value for key in derivation.input_fact_ids]
            require(len(inputs) == 2 and all(v.kind == "date" for v in inputs),
                    "inclusive date calculation requires ordered start/end date facts")
            days = (inputs[1].value - inputs[0].value).days + 1
            require(days > 0, "calculation end date precedes start date")
            require(derivation.output.kind == "integer" and derivation.output.value == days,
                    "calculation output does not match declared date rule")
            require(derivation.unit == "days", "inclusive date calculation unit must be days")
        require(set(field.evidence_ids) == source_ids, "field evidence must retain candidate/calculation provenance")
        if field.status == "verified":
            require(bool(field.evidence_ids), "verified field needs evidence")
            require(not any(issues[key].severity == "error" for key in field.issue_ids),
                    "verified field has unresolved error issue")
            if field.selected_candidate_id is not None:
                require(field.selected_candidate_id in field.candidate_ids, "selected candidate does not belong to field")
                require(field.suggested_value == candidates[field.selected_candidate_id].value,
                        "suggested value differs from selected candidate")
                require(all(candidates[key].value == field.suggested_value for key in field.candidate_ids),
                        "differing candidates require conflict handling")
            else:
                require(field.suggested_value == field.derivation.output,
                        "suggested value differs from calculation output")
                require(not field.candidate_ids, "calculated result must not silently override direct candidates")
            require(field.suggested_value.kind == form_fields[field_id].value_type, "wrong result value type")
        elif field.status != "not_applicable":
            require(bool(field.issue_ids), "unverified field needs an issue")
            actions = {"missing": "request_documents", "conflict": "request_confirmation",
                       "review_required": "request_confirmation", "needs_calculation": "calculate"}
            require(any(r.action == actions[field.status] for r in requests.get(field_id, [])),
                    "unverified field needs matching next action")
            require(all(r.action == actions[field.status] for r in requests.get(field_id, [])),
                    "review action contradicts field status")
            if field.status == "needs_calculation":
                require(field.derivation is not None, "needs_calculation requires a complete calculation plan")
            if field.status == "missing":
                require(not field.candidate_ids, "missing field cannot retain usable candidates")
            if field.status == "conflict":
                require(bool(field.candidate_ids), "conflict requires retained candidates")
                if any(issues[key].code == "source_conflict" for key in field.issue_ids):
                    values = {candidates[key].value.model_dump_json() for key in field.candidate_ids}
                    require(len(values) >= 2, "source_conflict requires differing candidates")
        if field.status in ("verified", "not_applicable"):
            require(not requests.get(field_id), "resolved fields cannot have pending requests")

        condition = form_fields[field_id].required_when
        if condition is not None:
            dependency = fields.get(condition.field_id)
            known = dependency is not None and dependency.status == "verified"
            if known and dependency.suggested_value != condition.value:
                require(field.status == "not_applicable", "false field condition requires not_applicable")
            elif not known:
                require(field.status == "review_required", "unknown field condition requires review")
            else:
                require(field.status != "not_applicable", "true condition cannot be not_applicable")
        else:
            require(field.status != "not_applicable", "not_applicable requires a declared false condition")

    if result.task_status == "failed":
        require(bool(result.errors), "failed task needs execution errors")
    else:
        require(not result.errors, "execution errors require failed task status")
        require(set(fields) == set(form_fields), "successful processing must report every discovered field")
        pending = any(f.status not in ("verified", "not_applicable") for f in fields.values())
        pending = pending or any(issue.severity == "error" for issue in issues.values())
        expected = "needs_review" if pending else "completed"
        require(result.task_status == expected, "task status contradicts field/issue states")


def validate_ground_truth_structure(truth: GroundTruth) -> None:
    fields = unique_index(truth.expected_form.fields, "field_id")
    expected = unique_index(truth.expected_fields, "gold_field_id")
    require(set(expected) == set(fields), "ground truth must cover every gold form field")
    for field_id, field in expected.items():
        for value in field.accepted_values:
            require(value is None or value.kind == fields[field_id].value_type, "wrong gold value type")
        for candidate in field.expected_candidates:
            require(candidate.value.kind == fields[field_id].value_type, "wrong gold candidate type")
        if field.expected_calculation is not None:
            require(field.expected_calculation.expected_value.kind == fields[field_id].value_type,
                    "wrong gold calculation output type")
        if field.expected_status == "verified" and field.expected_calculation is None:
            require(bool(field.expected_candidates), "verified gold needs expected source candidates")
            require(all(value in [c.value for c in field.expected_candidates] for value in field.accepted_values),
                    "gold accepted value has no matching expected candidate")
        if "source_conflict" in field.expected_issue_codes:
            require(field.expected_status == "conflict", "source_conflict gold must have conflict status")
            require(len({c.value.model_dump_json() for c in field.expected_candidates}) >= 2,
                    "source_conflict gold needs differing candidates")


def gold_anchors(truth: GroundTruth):
    for field in truth.expected_fields:
        for group in field.evidence_alternatives:
            yield from group
        for candidate in field.expected_candidates:
            yield from candidate.evidence
        if field.expected_calculation is not None:
            for source in field.expected_calculation.inputs:
                yield from source.evidence


def validate_ground_truth(task: TaskInput, truth: GroundTruth) -> None:
    """Validate annotations against task metadata, never against predicted fields."""
    require(truth.task_id == task.task_id, "ground truth task_id mismatch")
    require(truth.expected_form.target_document_id == task.target_document_id, "gold target mismatch")
    documents = unique_index(task.documents, "document_id")
    rules = unique_index(task.rules, "rule_id")
    for field in truth.expected_form.fields:
        locator_matches_media(field.target_locator, documents[task.target_document_id])
        references(field.rule_ids, rules, "gold form rules")
    for anchor in gold_anchors(truth):
        require(anchor.document_id in documents, "unknown gold source document")
        require(documents[anchor.document_id].role == "reference", "gold value source must be reference material")
        locator_matches_media(anchor.locator, documents[anchor.document_id])
    for field in truth.expected_fields:
        calculation = field.expected_calculation
        if calculation is not None:
            require(calculation.rule_id in rules, "unknown gold calculation rule")
            rule = rules[calculation.rule_id]
            require(calculation.rule_version == rule.version, "gold calculation rule version mismatch")
            require(rule.kind == "date_days_inclusive", "unsupported gold calculation")
            values = [source.value for source in calculation.inputs]
            require(len(values) == 2 and all(v.kind == "date" for v in values), "wrong gold date inputs")
            days = (values[1].value - values[0].value).days + 1
            require(days > 0 and calculation.expected_value.kind == "integer"
                    and calculation.expected_value.value == days and calculation.unit == "days",
                    "gold calculation does not match rule")
            if field.expected_status == "verified":
                require(calculation.expected_value in field.accepted_values, "gold accepted value differs from calculation")


def verify_artifacts(
    task: TaskInput, root: Path, parsed: Iterable[ParsedDocument] = (), truth: GroundTruth | None = None
) -> None:
    """Check file hashes and text anchors. PDF/Office/OCR physical checks come later."""
    root = root.resolve(strict=True)
    documents = unique_index(task.documents, "document_id")
    content: dict[str, bytes] = {}
    for document in task.documents:
        path = (root / document.relative_path).resolve(strict=True)
        require(path.is_relative_to(root), "document resolves outside task directory")
        require(path.is_file(), "document path must resolve to a file")
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == document.sha256, f"file hash mismatch: {document.document_id}")
        content[document.document_id] = data

    def source_text(document_id, locator):
        require(document_id in documents, "unknown artifact source document")
        require(locator.kind == "text" and documents[document_id].media_type == "text/plain",
                "physical anchor verification currently supports text/plain only")
        lines = content[document_id].decode("utf-8").splitlines()
        require(locator.line_end <= len(lines), "text locator exceeds physical document")
        return "\n".join(lines[locator.line_start - 1:locator.line_end])

    for document in parsed:
        for segment in document.segments:
            require(source_text(document.document_id, segment.locator) == segment.text,
                    "parsed segment does not match physical source document")
    if truth is not None:
        validate_ground_truth(task, truth)
        for anchor in gold_anchors(truth):
            text = source_text(anchor.document_id, anchor.locator)
            require(anchor.end <= len(text) and text[anchor.start:anchor.end] == anchor.quote,
                    "gold quote does not match physical source document")
