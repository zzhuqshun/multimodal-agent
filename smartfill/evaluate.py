"""Independent field-position evaluation; never imported by the rule baseline."""
from __future__ import annotations

from collections import Counter
from math import ceil
from statistics import median

from .contracts import FillingResult, GroundTruth


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def overlap(a, b):
    if a.kind != b.kind:
        return False
    if a.kind != "page":
        return a == b
    if (a.page, a.source_rotation_degrees, a.source_to_canonical) != (
            b.page, b.source_rotation_degrees, b.source_to_canonical):
        return False
    x0, y0 = max(a.bbox[0], b.bbox[0]), max(a.bbox[1], b.bbox[1])
    x1, y1 = min(a.bbox[2], b.bbox[2]), min(a.bbox[3], b.bbox[3])
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    area = lambda box: (box[2] - box[0]) * (box[3] - box[1])
    union = area(a.bbox) + area(b.bbox) - intersection
    return union > 0 and intersection / union >= 0.8


def align_fields(predicted, expected):
    """Mutually unique geometric matches. Ambiguous duplicates remain unmatched."""
    options = {g.field_id: [p.field_id for p in predicted if overlap(p.target_locator, g.target_locator)]
               for g in expected}
    reverse = Counter(pid for choices in options.values() for pid in choices)
    return {gid: choices[0] for gid, choices in options.items()
            if len(choices) == 1 and reverse[choices[0]] == 1}


def anchor_key(anchor):
    return (anchor.document_id, anchor.locator.model_dump_json(), anchor.quote, anchor.start, anchor.end)


def candidate_matches(prediction, expected, evidence):
    anchors = {anchor_key(evidence[e]) for e in prediction.evidence_ids}
    return prediction.value == expected.value and {anchor_key(e) for e in expected.evidence} <= anchors


def match_candidates(predicted, expected, evidence):
    """Count each candidate once, including distinct sources with the same value."""
    available = list(predicted)
    matched = 0
    for gold in expected:
        for index, candidate in enumerate(available):
            if candidate_matches(candidate, gold, evidence):
                matched += 1
                available.pop(index)
                break
    return matched


def evaluate_task(result: FillingResult, truth: GroundTruth) -> dict:
    if result.task_id != truth.task_id:
        raise ValueError("prediction and ground truth task IDs differ")
    gold_form = truth.expected_form
    predicted = result.form_schema.fields if result.form_schema is not None else []
    expected = {f.gold_field_id: f for f in truth.expected_fields}
    pred_forms = {f.field_id: f for f in predicted}
    gold_forms = {f.field_id: f for f in gold_form.fields}
    fields = {f.field_id: f for f in result.fields}
    groups = {g.group_id: g for g in result.form_schema.groups} if result.form_schema else {}
    gold_groups = {g.group_id: g for g in gold_form.groups}
    alignment = align_fields(predicted, gold_form.fields)
    evidence = {e.evidence_id: e for e in result.evidence}
    facts = {f.fact_id: f for f in result.facts}
    candidates = {c.candidate_id: c for c in result.candidates}
    issues = {i.issue_id: i for i in result.issues}
    requests = {}
    for request in result.review_requests:
        requests.setdefault(request.field_id, set()).add(request.action)

    # Group and row names are arbitrary IDs; check consistent one-to-one structure.
    group_pairs, row_pairs = set(), set()
    for gid, pid in alignment.items():
        a, b = gold_forms[gid], pred_forms[pid]
        if a.group_id is not None and b.group_id is not None:
            group_pairs.add((a.group_id, b.group_id))
        if a.row_id is not None and b.row_id is not None:
            row_pairs.add(((a.group_id, a.row_id), (b.group_id, b.row_id)))

    def bijective(pair, pairs):
        return sum(p[0] == pair[0] for p in pairs) == sum(p[1] == pair[1] for p in pairs) == 1

    def structure(gid, pid):
        a, b = gold_forms[gid], pred_forms[pid]
        normalize = lambda label: "".join(label.split())
        if normalize(a.label) != normalize(b.label) or a.value_type != b.value_type or a.required != b.required:
            return False
        if (a.group_id is None) != (b.group_id is None) or (a.row_id is None) != (b.row_id is None):
            return False
        if a.group_id is not None:
            ga, gb = gold_groups[a.group_id], groups[b.group_id]
            if ga.repeatable != gb.repeatable or not bijective((a.group_id, b.group_id), group_pairs):
                return False
        if a.row_id is not None and not bijective(((a.group_id, a.row_id), (b.group_id, b.row_id)), row_pairs):
            return False
        if (a.required_when is None) != (b.required_when is None):
            return False
        if a.required_when is not None:
            return (alignment.get(a.required_when.field_id) == b.required_when.field_id
                    and a.required_when.value == b.required_when.value
                    and a.required_when.operator == b.required_when.operator)
        return True

    counters = Counter(
        gold_fields=len(expected), predicted_fields=len(predicted),
        fillable_gold=sum(f.expected_status == "verified" for f in expected.values()),
        refusal_gold=sum(f.expected_status not in ("verified", "not_applicable") for f in expected.values()),
        gold_conflicts=sum(f.expected_status == "conflict" for f in expected.values()),
        predicted_conflicts=sum(f.status == "conflict" for f in result.fields),
        predicted_nonempty=sum(f.suggested_value is not None for f in result.fields),
        gold_candidates=sum(len(f.expected_candidates) for f in expected.values()),
        predicted_candidates=len(result.candidates),
        evidence_gold=sum(f.expected_status == "verified" and bool(f.evidence_alternatives) for f in expected.values()),
        calculation_gold=sum(f.expected_status == "verified" and f.expected_calculation is not None for f in expected.values()),
    )
    details = []
    for gid, gold in expected.items():
        pid = alignment.get(gid)
        prediction = fields.get(pid)
        good_structure = pid is not None and structure(gid, pid)
        counters["identified"] += good_structure
        checks = {"structure": good_structure, "status": False, "action": False,
                  "value": False, "issues": False, "candidates": False,
                  "evidence": gold.expected_status != "verified", "calculation": gold.expected_calculation is None}
        if prediction is not None and good_structure:
            if prediction.status == "verified":
                action = "fill" if not requests.get(pid) else None
            elif prediction.status == "not_applicable":
                action = "leave_blank" if not requests.get(pid) else None
            else:
                actions = requests.get(pid, set())
                action = next(iter(actions)) if len(actions) == 1 else None
            checks.update(status=prediction.status == gold.expected_status,
                          action=action == gold.expected_action,
                          value=prediction.suggested_value in gold.accepted_values,
                          issues={issues[i].code for i in prediction.issue_ids} == set(gold.expected_issue_codes))
            supplied = [candidates[c] for c in prediction.candidate_ids]
            matches = match_candidates(supplied, gold.expected_candidates, evidence)
            counters["matched_candidates"] += matches
            checks["candidates"] = matches == len(supplied) == len(gold.expected_candidates)
            if gold.expected_status == "verified":
                counters["aligned_fillable"] += 1
                counters["aligned_correct_values"] += checks["value"] and prediction.status == "verified"
                supplied_anchors = {anchor_key(evidence[e]) for e in prediction.evidence_ids}
                checks["evidence"] = any({anchor_key(a) for a in combination} <= supplied_anchors
                                         for combination in gold.evidence_alternatives)
                counters["correct_evidence"] += checks["evidence"]
                if gold.expected_calculation is not None:
                    calc, derivation = gold.expected_calculation, prediction.derivation
                    checks["calculation"] = bool(derivation and derivation.rule_id == calc.rule_id
                        and derivation.rule_version == calc.rule_version and derivation.output == calc.expected_value
                        and derivation.unit == calc.unit and len(derivation.input_fact_ids) == len(calc.inputs))
                    if checks["calculation"]:
                        for fid, annotated in zip(derivation.input_fact_ids, calc.inputs):
                            fact = facts[fid]
                            checks["calculation"] &= fact.normalized_value == annotated.value and {
                                anchor_key(e) for e in annotated.evidence} <= {
                                anchor_key(evidence[e]) for e in fact.evidence_ids}
                    counters["correct_calculations"] += checks["calculation"]
            elif gold.expected_status != "not_applicable":
                counters["correct_refusals"] += (checks["status"] and checks["action"]
                                                 and checks["value"] and checks["issues"])
            counters["correct_states_actions"] += checks["status"] and checks["action"]
            counters["conflict_tp"] += gold.expected_status == prediction.status == "conflict"
            if prediction.suggested_value is not None and not (
                    gold.expected_status == prediction.status == "verified" and checks["value"]):
                counters["wrong_fills"] += 1
        elif prediction is not None:
            counters["wrong_fills"] += prediction.suggested_value is not None
        checks["passed"] = bool(all(checks.values()))
        counters["fully_correct_fields"] += checks["passed"]
        details.append({"gold_field_id": gid, "predicted_field_id": pid, "checks": checks})
    aligned_predictions = set(alignment.values())
    counters["wrong_fills"] += sum(f.suggested_value is not None for f in result.fields if f.field_id not in aligned_predictions)
    expected_status = "needs_review" if counters["refusal_gold"] else "completed"
    task_pass = (counters["fully_correct_fields"] == len(expected)
                 and len(predicted) == len(expected) and not result.errors and result.task_status == expected_status)
    return {"task_id": result.task_id, "task_status": result.task_status, "task_pass": bool(task_pass),
            "counts": dict(counters), "fields": details, "pending_requests": len(result.review_requests),
            "timing": result.timing.model_dump(mode="json"), "failure_stages": [e.stage for e in result.errors]}


def aggregate(reports: list[dict]) -> dict:
    total = Counter()
    for report in reports:
        total.update(report["counts"])
    precision = ratio(total["identified"], total["predicted_fields"])
    recall = ratio(total["identified"], total["gold_fields"])
    f1 = ratio(2 * total["identified"], total["predicted_fields"] + total["gold_fields"])
    times = sorted(r["timing"]["total_ms"] for r in reports)
    return {"tasks": len(reports), "counts": dict(total), "metrics": {
        "field_precision": precision, "field_recall": recall, "field_f1": f1,
        "aligned_value_accuracy": ratio(total["aligned_correct_values"], total["aligned_fillable"]),
        "end_to_end_value_recall": ratio(total["aligned_correct_values"], total["fillable_gold"]),
        "state_action_accuracy": ratio(total["correct_states_actions"], total["gold_fields"]),
        "wrong_fill_rate": ratio(total["wrong_fills"], total["predicted_nonempty"]),
        "conflict_precision": ratio(total["conflict_tp"], total["predicted_conflicts"]),
        "conflict_recall": ratio(total["conflict_tp"], total["gold_conflicts"]),
        "correct_refusal_rate": ratio(total["correct_refusals"], total["refusal_gold"]),
        "filled_field_evidence_accuracy": ratio(total["correct_evidence"], total["evidence_gold"]),
        "source_candidate_precision": ratio(total["matched_candidates"], total["predicted_candidates"]),
        "source_candidate_recall": ratio(total["matched_candidates"], total["gold_candidates"]),
        "calculation_chain_accuracy": ratio(total["correct_calculations"], total["calculation_gold"]),
        "full_field_pass_rate": ratio(total["fully_correct_fields"], total["gold_fields"]),
        "task_pass_rate": ratio(sum(r["task_pass"] for r in reports), len(reports)),
    }, "task_statuses": dict(Counter(r["task_status"] for r in reports)),
        "pending_requests": sum(r["pending_requests"] for r in reports),
        "timing_ms": {"sum": sum(times), "median": median(times) if times else None,
                      "p95": times[max(0, ceil(len(times) * .95) - 1)] if times else None},
        "failure_stages": dict(Counter(s for r in reports for s in r["failure_stages"])),
        "evaluation_scope": "controlled development tasks; evidence metric covers filled fields only; no generalization claim"}
