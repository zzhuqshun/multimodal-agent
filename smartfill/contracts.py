"""Versioned JSON contracts independent of OCR, LLM and transport libraries."""

from __future__ import annotations

import ntpath
from datetime import date
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, pattern=r"\S")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
ValueKind = Literal["text", "date", "integer", "decimal", "boolean", "text_list"]
FieldStatus = Literal[
    "verified", "conflict", "missing", "review_required", "needs_calculation", "not_applicable"
]
Action = Literal["fill", "request_documents", "request_confirmation", "calculate", "leave_blank"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True, allow_inf_nan=False)
    schema_version: Literal["0.1.0"] = "0.1.0"


class TextValue(Contract):
    kind: Literal["text"] = "text"
    value: Name


class DateValue(Contract):
    kind: Literal["date"] = "date"
    value: date


class IntegerValue(Contract):
    kind: Literal["integer"] = "integer"
    value: int


class DecimalValue(Contract):
    kind: Literal["decimal"] = "decimal"
    value: Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")]
    unit: Name


class BooleanValue(Contract):
    kind: Literal["boolean"] = "boolean"
    value: bool


class TextListValue(Contract):
    kind: Literal["text_list"] = "text_list"
    value: Annotated[list[Name], Field(min_length=1)]


Value = Annotated[
    TextValue | DateValue | IntegerValue | DecimalValue | BooleanValue | TextListValue,
    Field(discriminator="kind"),
]


class TextLocator(Contract):
    kind: Literal["text"] = "text"
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered_lines(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("line_end must not precede line_start")
        return self


Coordinate = Annotated[float, Field(ge=0, le=1)]


class PageLocator(Contract):
    kind: Literal["page"] = "page"
    page: int = Field(ge=1)
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]
    coordinate_frame: Literal["normalized_top_left_rotation_corrected"] = (
        "normalized_top_left_rotation_corrected"
    )
    source_rotation_degrees: Literal[0, 90, 180, 270] = 0
    source_to_canonical: tuple[float, float, float, float, float, float] | None = None

    @model_validator(mode="after")
    def valid_box(self) -> Self:
        x0, y0, x1, y1 = self.bbox
        if x0 >= x1 or y0 >= y1:
            raise ValueError("bbox must have positive width and height")
        if self.source_rotation_degrees and self.source_to_canonical is None:
            raise ValueError("rotated source needs source_to_canonical transform")
        return self


def cell_position(cell: str) -> tuple[int, int]:
    """Return one-based Excel row/column; reject addresses outside worksheet limits."""
    import re

    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", cell)
    if match is None:
        raise ValueError("cell must be an uppercase A1 address")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord("A") + 1
    row = int(match[2])
    if column > 16384 or row > 1048576:
        raise ValueError("cell exceeds Excel worksheet bounds")
    return row, column


class CellLocator(Contract):
    kind: Literal["cell"] = "cell"
    sheet: Name
    cell_range: Name

    @field_validator("cell_range")
    @classmethod
    def valid_range(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) not in (1, 2):
            raise ValueError("expected A1 or A1:B2")
        first, last = cell_position(parts[0]), cell_position(parts[-1])
        if first[0] > last[0] or first[1] > last[1]:
            raise ValueError("cell range must be ordered")
        return value


class WordParagraphLocator(Contract):
    kind: Literal["word_paragraph"] = "word_paragraph"
    paragraph: int = Field(ge=1)


class WordCellLocator(Contract):
    kind: Literal["word_cell"] = "word_cell"
    table: int = Field(ge=1)
    row: int = Field(ge=1)
    column: int = Field(ge=1)


Locator = Annotated[
    TextLocator | PageLocator | CellLocator | WordParagraphLocator | WordCellLocator,
    Field(discriminator="kind"),
]


class Document(Contract):
    document_id: Identifier
    role: Literal["target_form", "reference"]
    media_type: Name
    relative_path: Name
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    synthetic: bool
    document_type: Name | None = None

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute() or ntpath.splitdrive(value)[0] or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))
        ):
            raise ValueError("relative_path must be a safe relative POSIX file path")
        return value


class BusinessRule(Contract):
    rule_id: Identifier
    version: Name
    kind: Literal["format", "consistency", "date_days_inclusive"]
    description: Name


class TaskInput(Contract):
    task_id: Identifier
    description: Name
    target_document_id: Identifier
    documents: Annotated[list[Document], Field(min_length=1)]
    ruleset_id: Identifier
    ruleset_version: Name
    rules: list[BusinessRule] = Field(default_factory=list)
    as_of_date: date

    @model_validator(mode="after")
    def references(self) -> Self:
        from .integrity import unique_index

        documents = unique_index(self.documents, "document_id")
        unique_index(self.rules, "rule_id")
        targets = [d.document_id for d in self.documents if d.role == "target_form"]
        if targets != [self.target_document_id] or self.target_document_id not in documents:
            raise ValueError("task needs exactly one matching target_form document")
        return self


class ParsedSegment(Contract):
    segment_id: Identifier
    text: Name
    locator: Locator


class ParsedDocument(Contract):
    document_id: Identifier
    parser_name: Name
    parser_version: Name
    segments: list[ParsedSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_segments(self) -> Self:
        from .integrity import unique_index

        unique_index(self.segments, "segment_id")
        return self


class FieldCondition(Contract):
    field_id: Identifier
    operator: Literal["equals"] = "equals"
    value: Value


class FormGroup(Contract):
    group_id: Identifier
    label: Name
    repeatable: bool = False


class FormField(Contract):
    field_id: Identifier
    label: Name
    value_type: ValueKind
    required: bool
    target_locator: Locator
    semantic_key: Name | None = None
    group_id: Identifier | None = None
    row_id: Identifier | None = None
    required_when: FieldCondition | None = None
    rule_ids: list[Identifier] = Field(default_factory=list)


class FormSchema(Contract):
    form_id: Identifier
    target_document_id: Identifier
    fields: Annotated[list[FormField], Field(min_length=1)]
    groups: list[FormGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self) -> Self:
        from .integrity import unique_index

        fields = unique_index(self.fields, "field_id")
        groups = unique_index(self.groups, "group_id")
        for field in self.fields:
            if field.group_id is not None and field.group_id not in groups:
                raise ValueError("unknown group_id")
            if field.row_id is not None and (
                field.group_id is None or not groups[field.group_id].repeatable
            ):
                raise ValueError("row_id requires a repeatable group")
            if field.required_when is not None:
                dependency = field.required_when.field_id
                if dependency not in fields or dependency == field.field_id:
                    raise ValueError("condition must reference another form field")
                if field.required_when.value.kind != fields[dependency].value_type:
                    raise ValueError("condition value type does not match dependency")
        # Cyclic conditions cannot be evaluated reliably.
        for field in self.fields:
            seen: set[str] = set()
            current = field
            while current.required_when is not None:
                if current.field_id in seen:
                    raise ValueError("cyclic field conditions")
                seen.add(current.field_id)
                current = fields[current.required_when.field_id]
        return self


class Evidence(Contract):
    evidence_id: Identifier
    document_id: Identifier
    segment_id: Identifier
    locator: Locator
    quote: Name
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    origin: Literal["parser", "ocr", "vlm", "manual"]

    @model_validator(mode="after")
    def ordered_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("evidence end must be greater than start")
        return self


class ExtractedFact(Contract):
    fact_id: Identifier
    entity_id: Identifier | None = None
    predicate: Name
    raw_value: Name
    normalized_value: Value
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class FieldCandidate(Contract):
    candidate_id: Identifier
    field_id: Identifier
    fact_ids: Annotated[list[Identifier], Field(min_length=1)]
    value: Value
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    method: Literal["rule", "llm", "manual"]
    score: float | None = Field(default=None, ge=0, le=1)


class ValidationIssue(Contract):
    issue_id: Identifier
    code: Identifier
    severity: Literal["info", "warning", "error"]
    message: Name
    field_ids: list[Identifier] = Field(default_factory=list)
    document_ids: list[Identifier] = Field(default_factory=list)
    rule_id: Identifier | None = None


class Derivation(Contract):
    rule_id: Identifier
    rule_version: Name
    input_fact_ids: Annotated[list[Identifier], Field(min_length=1)]
    output: Value
    unit: Name


class FieldResult(Contract):
    field_id: Identifier
    candidate_ids: list[Identifier] = Field(default_factory=list)
    selected_candidate_id: Identifier | None = None
    suggested_value: Value | None = None
    status: FieldStatus
    evidence_ids: list[Identifier] = Field(default_factory=list)
    issue_ids: list[Identifier] = Field(default_factory=list)
    derivation: Derivation | None = None

    @model_validator(mode="after")
    def status_value(self) -> Self:
        if self.status == "verified":
            if self.suggested_value is None:
                raise ValueError("verified requires a non-null value")
            if (self.selected_candidate_id is None) == (self.derivation is None):
                raise ValueError("verified requires either a selected candidate or derivation")
        elif self.suggested_value is not None or self.selected_candidate_id is not None:
            raise ValueError("unverified fields must have null value and no selected candidate")
        if self.derivation is not None and self.status not in ("verified", "needs_calculation"):
            raise ValueError("derivation is only valid for calculation fields")
        return self


class ReviewRequest(Contract):
    field_id: Identifier
    action: Literal["request_documents", "request_confirmation", "calculate"]
    message: Name


class ExecutionError(Contract):
    stage: Literal["input", "parse", "form_understanding", "extraction", "mapping", "validation"]
    code: Identifier
    message: Name


class Timing(Contract):
    total_ms: float = Field(ge=0)
    stages_ms: dict[str, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def stage_bounds(self) -> Self:
        if any(value > self.total_ms for value in self.stages_ms.values()):
            raise ValueError("individual stage cannot exceed total elapsed time")
        return self


class RunMetadata(Contract):
    implementation_version: Name
    mode: Literal["handcrafted_fixture", "rule_baseline", "model_baseline"]
    model_id: Name | None = None
    prompt_version: Name | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class FillingResult(Contract):
    task_id: Identifier
    run_id: Identifier
    task_input: TaskInput
    form_schema: FormSchema | None
    parsed_documents: list[ParsedDocument] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    candidates: list[FieldCandidate] = Field(default_factory=list)
    fields: list[FieldResult] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    review_requests: list[ReviewRequest] = Field(default_factory=list)
    task_status: Literal["completed", "needs_review", "failed"]
    errors: list[ExecutionError] = Field(default_factory=list)
    timing: Timing
    run_metadata: RunMetadata

    @model_validator(mode="after")
    def integrity(self) -> Self:
        from .integrity import validate_result

        validate_result(self)
        return self


class GoldEvidence(Contract):
    """Independent source anchor; never references prediction-generated IDs."""

    document_id: Identifier
    locator: Locator
    quote: Name
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def quote_length(self) -> Self:
        if self.end - self.start != len(self.quote):
            raise ValueError("gold span length must equal quote length")
        return self


class ExpectedCandidate(Contract):
    value: Value
    evidence: Annotated[list[GoldEvidence], Field(min_length=1)]


class ExpectedCalculation(Contract):
    rule_id: Identifier
    rule_version: Name
    inputs: Annotated[list[ExpectedCandidate], Field(min_length=1)]
    expected_value: Value
    unit: Name


class ExpectedField(Contract):
    gold_field_id: Identifier
    accepted_values: Annotated[list[Value | None], Field(min_length=1)]
    expected_status: FieldStatus
    expected_action: Action
    expected_candidates: list[ExpectedCandidate] = Field(default_factory=list)
    evidence_alternatives: list[Annotated[list[GoldEvidence], Field(min_length=1)]] = Field(
        default_factory=list
    )
    expected_issue_codes: list[Identifier] = Field(default_factory=list)
    expected_calculation: ExpectedCalculation | None = None

    @model_validator(mode="after")
    def status_contract(self) -> Self:
        actions = {
            "verified": "fill", "conflict": "request_confirmation",
            "missing": "request_documents", "review_required": "request_confirmation",
            "needs_calculation": "calculate", "not_applicable": "leave_blank",
        }
        if self.expected_action != actions[self.expected_status]:
            raise ValueError("ground truth action does not match status")
        if self.expected_status == "verified":
            if any(value is None for value in self.accepted_values):
                raise ValueError("verified gold values cannot contain null")
            if not self.evidence_alternatives:
                raise ValueError("verified ground truth requires supporting source anchors")
        elif self.accepted_values != [None]:
            raise ValueError("unverified gold accepted_values must be [null]")
        if self.expected_status not in ("verified", "not_applicable") and not self.expected_issue_codes:
            raise ValueError("unverified ground truth requires expected issue codes")
        if self.expected_status == "conflict" and not self.expected_candidates:
            raise ValueError("conflict ground truth requires candidates")
        if self.expected_status == "needs_calculation" and self.expected_calculation is None:
            raise ValueError("calculation ground truth requires calculation specification")
        return self


class AnnotationProvenance(Contract):
    method: Literal["handcrafted", "synthetic_generator", "human"]
    version: Name
    independently_reviewed: bool


class GroundTruth(Contract):
    task_id: Identifier
    dataset_version: Name
    expected_form: FormSchema
    expected_fields: Annotated[list[ExpectedField], Field(min_length=1)]
    annotation_provenance: AnnotationProvenance

    @model_validator(mode="after")
    def integrity(self) -> Self:
        from .integrity import validate_ground_truth_structure

        validate_ground_truth_structure(self)
        return self
