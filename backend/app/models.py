"""Pydantic request/response models for the ClashDoctor API."""
from pydantic import BaseModel, Field


# --- Artist search ---

class SearchCandidate(BaseModel):
    name: str
    entity_id: str
    types: list[str] = []
    short_description: str | None = None
    popularity: float | None = None
    disambiguation: str | None = None
    image_url: str | None = None


class ArtistSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ArtistSearchResponse(BaseModel):
    query: str
    candidates: list[SearchCandidate] = []
    best_match: SearchCandidate | None = None
    ambiguous: bool = False


# --- Lineup import ---

class ImportParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    filename: str | None = None


class ImportIssue(BaseModel):
    severity: str  # "error" | "warning" | "info"
    row: int | None = None
    field: str | None = None
    message: str


class ImportStage(BaseModel):
    id: str
    name: str


class ImportSlot(BaseModel):
    id: str
    label: str = ""
    start: str
    end: str
    duration_min: int = 60


class ImportAct(BaseModel):
    id: str
    row: int | None = None
    name: str
    entity_id: str = ""  # empty until the user confirms a Qloo match
    stage_id: str
    stage_name: str = ""
    slot_id: str
    start: str = ""
    end: str = ""
    duration_min: int = 60
    fixed: bool = False


class ImportParseResponse(BaseModel):
    source_format: str  # "csv" | "text"
    festival_name: str | None = None
    stages: list[ImportStage] = []
    slots: list[ImportSlot] = []
    acts: list[ImportAct] = []
    issues: list[ImportIssue] = []
    valid: bool = False
    summary: str = ""


class ImportResolveRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=100)


class ImportMatch(BaseModel):
    query: str
    status: str  # "matched" | "ambiguous" | "not_found" | "error"
    match: SearchCandidate | None = None
    candidates: list[SearchCandidate] = []
    note: str | None = None
    cached: bool = False


class ImportResolveResponse(BaseModel):
    matches: list[ImportMatch] = []
    resolved: int = 0
    needs_confirmation: int = 0
    unresolved: int = 0
    failed: int = 0
    note: str = ""


# --- Profiles ---

class ProfileRequest(BaseModel):
    entity_ids: list[str] = Field(min_length=1, max_length=500)
    names: dict[str, str] = {}


class ArtistProfile(BaseModel):
    entity_id: str
    name: str | None = None
    source: str  # "qloo-insights" | "qloo-search" | "demo" | "unmatched"
    missing: bool = False
    note: str | None = None
    genre_tags: list[str] = []  # original ids, exactly as returned by the provider
    canonical_genre_tags: list[str] = []  # namespace-normalized music genres
    audience_tags: list[str] = []
    style_tags: list[str] = []
    music_tags: list[str] = []


# --- Similarity ---

class SimilarityRequest(BaseModel):
    entity_ids: list[str] = Field(min_length=1, max_length=500)
    names: dict[str, str] = {}


class SimilaritySignal(BaseModel):
    """One tag category both artists actually have, and what it contributed."""

    category: str  # "genre" | "audience" | "style" | "music"
    label: str
    weight: float
    normalized_weight: float
    jaccard: float
    shared_count: int
    union_count: int
    contribution: float
    shared_tags: list[str] = []


class SkippedCategory(BaseModel):
    category: str
    label: str
    reason: str


class SimilarityPair(BaseModel):
    a: str
    b: str
    taste_similarity: float | None = None
    genre_similarity: float | None = None
    combined_similarity: float | None = None
    signals: list[SimilaritySignal] = []
    skipped_categories: list[SkippedCategory] = []
    categories_compared: list[str] = []
    low_confidence: bool = False
    confidence_note: str | None = None
    shared_genre_tags: list[str] = []
    shared_tags: list[str] = []  # every shared tag across compared categories
    shared_tag_count: int = 0
    shared_generic_tags: list[str] = []  # shared tags that are generic in this lineup
    shared_generic_tag_count: int = 0
    generic_share: float = 0.0  # share of shared tags that are generic in this lineup
    shared_specific_tags: list[str] = []  # shared tags that are not generic in this lineup
    shared_specific_tag_count: int = 0
    shared_broad_tags: list[str] = []  # stricter: at least half the tagged acts
    broad_share: float = 0.0  # share of shared tags that are broad in this lineup
    genre_backed: bool = False
    profile_sources: dict[str, str | None] = {}
    evidence_limitations: list[str] = []
    missing: bool = False
    missing_kind: str | None = None  # "profile_data" | "disjoint_categories"
    missing_reason: str | None = None


class SimilarityResponse(BaseModel):
    mode: str  # "demo" | "live" | "mixed" | "unmatched"
    profiles: list[ArtistProfile] = []
    pairs: list[SimilarityPair] = []
    methods: dict[str, str] = {}
    coverage: dict = {}
    warnings: list[str] = []  # partial-failure notes for live data only


# --- Schedule / optimization ---

class Stage(BaseModel):
    id: str
    name: str


class Slot(BaseModel):
    id: str
    label: str = ""
    start: str  # "HH:MM" 24h
    end: str


class Act(BaseModel):
    id: str
    name: str
    entity_id: str
    stage_id: str = ""
    slot_id: str = ""
    duration_min: int = Field(default=60, ge=1, le=480)
    fixed: bool = False
    allowed_stages: list[str] | None = None
    allowed_slots: list[str] | None = None


class OptimizePreferences(BaseModel):
    """User-set priorities for the optimizer. Defaults reproduce a plain
    similarity sum with no weighting, so an untouched request behaves like before."""

    high_affinity_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    high_affinity_weight: float = Field(default=1.0, ge=1.0, le=10.0)
    move_penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    max_moves: int = Field(default=200, ge=0, le=200)


class OptimizeRequest(BaseModel):
    stages: list[Stage] = Field(min_length=1)
    slots: list[Slot] = Field(min_length=1)
    acts: list[Act] = Field(min_length=1, max_length=500)
    preferences: OptimizePreferences = Field(default_factory=OptimizePreferences)


class ScheduleAssignRequest(BaseModel):
    """Acts may carry empty stage_id/slot_id; the backend places them."""

    stages: list[Stage] = Field(min_length=1)
    slots: list[Slot] = Field(min_length=1)
    acts: list[Act] = Field(max_length=500)


class ScheduleAssignResponse(BaseModel):
    acts: list[Act] = []
    note: str = ""


class ClashInfo(BaseModel):
    a_id: str
    a_name: str
    b_id: str
    b_name: str
    stage_a: str
    stage_b: str
    slot_a: str
    slot_b: str
    similarity: float
    method: str  # "taste_blend"
    signals: list[SimilaritySignal] = []  # what each tag category contributed
    low_confidence: bool = False
    confidence_note: str | None = None
    genre_backed: bool = False
    shared_tag_count: int = 0
    shared_generic_tag_count: int = 0
    generic_share: float = 0.0
    shared_specific_tag_count: int = 0
    broad_share: float = 0.0
    profile_sources: dict[str, str | None] = {}
    evidence_limitations: list[str] = []


class MoveInfo(BaseModel):
    act_id: str
    act_name: str
    moved_act_ids: list[str] = []
    kind: str = "relocate"  # "relocate" | "swap"
    from_stage: str
    from_slot: str
    to_stage: str
    to_slot: str
    raw_cost_saved: float
    objective_delta: float
    explanation: str


class MovedAct(BaseModel):
    """One act whose cell changed between the draft and the proposal."""

    act_id: str
    act_name: str
    from_stage: str
    from_slot: str
    to_stage: str
    to_slot: str


class ObjectiveMeasure(BaseModel):
    """The same numbers the search optimized, before and after."""

    raw_cost: float
    weighted_cost: float
    penalty: float
    objective: float
    clashes: int
    high_affinity_clashes: int
    churn: int
    excluded: int


class UnresolvedClash(BaseModel):
    a_id: str
    b_id: str
    similarity: float
    high_affinity: bool
    kind: str  # both_fixed | no_legal_cell | worse_objective | move_limit | local_optimum
    reason: str
    fixed_act: str | None = None
    movable_act: str | None = None


class ExcludedPair(BaseModel):
    a_name: str
    b_name: str
    reason: str


class ScheduleValidateRequest(BaseModel):
    stages: list[Stage] = Field(min_length=1)
    slots: list[Slot] = Field(min_length=1)
    acts: list[Act] = Field(min_length=1, max_length=500)


class ScheduleValidateResponse(BaseModel):
    valid: bool
    issues: list[str] = []
    acts: int
    constraints_checked: list[str] = []
    fixed_acts: list[str] = []
    overlapping_pairs: int = 0


class OptimizeResponse(BaseModel):
    objective_description: str
    preferences: OptimizePreferences
    preferences_description: str
    before: ObjectiveMeasure
    after: ObjectiveMeasure
    initial_cost: float
    optimized_cost: float
    improvement: float
    improved: bool
    percent_improvement: float | None = None
    limit_reached: bool = False
    valid: bool = True
    validation_issues: list[str] = []
    initial_clashes: list[ClashInfo] = []
    optimized_clashes: list[ClashInfo] = []
    moves: list[MoveInfo] = []
    moved_acts: list[MovedAct] = []
    unresolved: list[UnresolvedClash] = []
    excluded_pairs: list[ExcludedPair] = []
    fixed_clashes: list[ClashInfo] = []
    optimized_acts: list[Act] = []


# --- natural-language planning ---


class PlanInterpretRequest(BaseModel):
    """The schedule the instruction applies to, plus the instruction itself."""

    stages: list[Stage] = Field(min_length=1)
    slots: list[Slot] = Field(min_length=1)
    acts: list[Act] = Field(min_length=1, max_length=500)
    instruction: str = Field(min_length=1, max_length=2000)


class PlanEvidence(BaseModel):
    """One interpreted priority, the words that produced it, and what it does."""

    field: str
    label: str
    value: float | int
    unit: str
    phrase: str
    rule: str  # rule id, or "llm"
    source: str  # "rules" | "llm"
    note: str


class PlanLock(BaseModel):
    """An act the instruction wants kept in place, checked against the real lineup."""

    act_id: str
    act_name: str
    phrase: str
    already_locked: bool
    via_role: bool = False  # named as "the headliners", not by artist name
    source: str = "rules"


class PlanUnsupported(BaseModel):
    phrase: str
    reason: str
    alternative: str
    source: str = "rules"


class PlanClarification(BaseModel):
    kind: str  # out_of_range | conflict | count_unclear | act_not_found | nothing_matched | llm_rejected | llm_question
    phrase: str
    question: str
    candidates: list[str] = []


class PlanInterpretResponse(BaseModel):
    """A validated plan, not a schedule: nothing here has been run or applied."""

    instruction: str
    interpreted: bool
    preferences: OptimizePreferences
    preferences_description: str
    evidence: list[PlanEvidence] = []
    enforced_constraints: list[str] = []
    locked_acts: list[str] = []
    requested_locks: list[PlanLock] = []
    unsupported: list[PlanUnsupported] = []
    clarifications: list[PlanClarification] = []
    requires_confirmation: bool = False
    source: str  # "rules" | "rules+llm"
    llm_configured: bool
    llm_model: str | None = None
    llm_ok: bool | None = None
    llm_note: str = ""
    summary: str
