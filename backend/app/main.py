"""ClashDoctor API — FastAPI backend.

All Qloo requests happen here; the API key never reaches the frontend.
Demo data (demo: entity ids) works fully offline.
"""
import asyncio
import logging
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import config, demo_data, importer, models, planner
from . import similarity as similarity_engine
from . import optimizer as optimizer_mod
from .cache import TTLCache
from .qloo import (
    QlooClient,
    QlooError,
    QlooNotConfigured,
    QlooUpstreamError,
    canonical_genre_tag,
    fetch_profile,
    score_candidate,
    select_best_match,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("clashdoctor")

app = FastAPI(title="ClashDoctor API", version=config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


qloo_client = QlooClient()
search_record_cache = TTLCache(ttl_seconds=config.PROFILE_CACHE_TTL_SECONDS)
profile_cache = TTLCache(ttl_seconds=config.PROFILE_CACHE_TTL_SECONDS)
resolve_cache = TTLCache(ttl_seconds=config.PROFILE_CACHE_TTL_SECONDS)

# Bound concurrent Qloo calls during batch artist resolution.
RESOLVE_CONCURRENCY = 4
# Cap the excluded-pair list so a large unmatched lineup stays readable.
MAX_EXCLUDED_PAIRS = 25


def get_qloo() -> QlooClient:
    return qloo_client


planner_llm = planner.PlannerLLM()


def get_planner_llm() -> planner.PlannerLLM:
    return planner_llm


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "qloo_configured": qloo_client.configured,
        "data_mode": "live + demo" if qloo_client.configured else "demo only (QLOO_API_KEY not set)",
        "planner_configured": planner_llm.configured,
        "planner_mode": (
            f"phrase rules + {planner_llm.model}"
            if planner_llm.configured
            else "phrase rules only (no PLANNER_API_KEY/PLANNER_MODEL)"
        ),
    }


@app.get("/api/demo/festival")
def demo_festival() -> dict:
    return demo_data.DEMO_FESTIVAL


@app.get("/api/festival/template")
def festival_template() -> dict:
    """Empty grid template for building a live user lineup."""
    return demo_data.FESTIVAL_TEMPLATE


def _candidate_from_item(item: dict) -> models.SearchCandidate:
    properties = item.get("properties") or {}
    image = (properties.get("image") or {}).get("url")
    return models.SearchCandidate(
        name=item.get("name") or "Unknown",
        entity_id=item.get("entity_id") or "",
        types=item.get("types") or [],
        short_description=properties.get("short_description"),
        popularity=item.get("popularity"),
        disambiguation=item.get("disambiguation"),
        image_url=image,
    )


@app.post("/api/artists/search", response_model=models.ArtistSearchResponse)
async def search_artists(
    body: models.ArtistSearchRequest,
    qloo: QlooClient = Depends(get_qloo),
) -> models.ArtistSearchResponse:
    try:
        results = await qloo.search_artists(body.query, record_cache=search_record_cache)
    except QlooNotConfigured as exc:
        raise _api_error(503, "QLOO_NOT_CONFIGURED", str(exc)) from exc
    except QlooUpstreamError as exc:
        raise _api_error(502, "QLOO_UPSTREAM_ERROR", str(exc)) from exc

    candidates = [_candidate_from_item(item) for item in results]
    best, ambiguous = select_best_match(results, body.query)
    best_candidate = None
    if not ambiguous:
        best_candidate = next(
            (c for c in candidates if best and c.entity_id == best.get("entity_id")), None
        )
    return models.ArtistSearchResponse(
        query=body.query,
        candidates=candidates[:10],
        # An ambiguous result has no confirmed match. The client must ask the
        # user to pick a candidate; no entity is auto-selected for scoring.
        best_match=best_candidate,
        ambiguous=ambiguous,
    )


@app.post("/api/import/parse", response_model=models.ImportParseResponse)
def parse_import(body: models.ImportParseRequest) -> models.ImportParseResponse:
    """Parse pasted schedule text or CSV into a validated festival structure.

    Offline and deterministic: no Qloo calls, no invented artists. Acts come
    back with an empty entity_id until the user confirms a match.
    """
    try:
        parsed = importer.parse_lineup(body.text)
    except importer.ImportParseError as exc:
        raise _api_error(422, "IMPORT_UNPARSEABLE", str(exc)) from exc
    return models.ImportParseResponse(**parsed)


async def _resolve_one(qloo: QlooClient, name: str, semaphore: asyncio.Semaphore) -> dict:
    """Resolve a single artist name; failures stay per-name (partial results)."""
    key = name.strip().casefold()
    cached = resolve_cache.get(key)
    if cached is not None:
        return {**cached, "cached": True}

    async with semaphore:
        try:
            results = await qloo.search_artists(name, record_cache=search_record_cache)
        except QlooNotConfigured as exc:
            raise _api_error(503, "QLOO_NOT_CONFIGURED", str(exc)) from exc
        except QlooError as exc:
            return {"query": name, "status": "error", "match": None, "candidates": [],
                    "note": str(exc), "cached": False}

    candidates = [_candidate_from_item(item) for item in results][:10]
    if not candidates:
        payload = {
            "query": name,
            "status": "not_found",
            "match": None,
            "candidates": [],
            "note": "Qloo returned no artist for this name.",
            "cached": False,
        }
        resolve_cache.set(key, payload)
        return payload

    best, ambiguous = select_best_match(results, name)
    match = (
        None
        if ambiguous
        else next((c for c in candidates if best and c.entity_id == best.get("entity_id")), None)
    )
    payload = {
        "query": name,
        "status": "ambiguous" if ambiguous else "matched",
        # Ambiguous names expose candidates but never a confirmed match: the
        # caller must confirm one before the artist can be scored.
        "match": match,
        "candidates": candidates,
        "note": (
            "Several plausible matches — confirm which artist this is. "
            "No candidate is selected until you choose one."
            if ambiguous
            else None
        ),
        "cached": False,
    }
    resolve_cache.set(key, payload)
    return payload


@app.post("/api/import/resolve", response_model=models.ImportResolveResponse)
async def resolve_import(
    body: models.ImportResolveRequest,
    qloo: QlooClient = Depends(get_qloo),
) -> models.ImportResolveResponse:
    """Resolve imported artist names to Qloo entities.

    Ambiguous names are returned with their candidates and must be confirmed by
    the user; nothing is guessed silently and nothing is fabricated.
    """
    if not qloo.configured:
        raise _api_error(
            503,
            "QLOO_NOT_CONFIGURED",
            "QLOO_API_KEY is not set, so imported artists cannot be matched to Qloo "
            "entities. Set it in backend/.env and restart, or keep using demo data.",
        )

    # Case-insensitive dedupe: one Qloo lookup per distinct spelling, and counts
    # in the response reflect distinct artists rather than repeated rows.
    unique_names: list[str] = []
    seen: set[str] = set()
    for name in body.names:
        cleaned = name.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        unique_names.append(cleaned)

    semaphore = asyncio.Semaphore(RESOLVE_CONCURRENCY)
    results = await asyncio.gather(*(_resolve_one(qloo, name, semaphore) for name in unique_names))

    matches = [models.ImportMatch(**result) for result in results]
    resolved = sum(1 for m in matches if m.status == "matched")
    needs_confirmation = sum(1 for m in matches if m.status == "ambiguous")
    unresolved = sum(1 for m in matches if m.status == "not_found")
    failed = sum(1 for m in matches if m.status == "error")

    notes = []
    if needs_confirmation:
        notes.append(f"{needs_confirmation} name(s) need confirmation before they can be added.")
    if unresolved:
        notes.append(f"{unresolved} name(s) were not found on Qloo.")
    if failed:
        notes.append(f"{failed} lookup(s) failed — they can be retried; nothing was guessed.")

    return models.ImportResolveResponse(
        matches=matches,
        resolved=resolved,
        needs_confirmation=needs_confirmation,
        unresolved=unresolved,
        failed=failed,
        note=" ".join(notes),
    )


def _demo_profile(entity_id: str, name: str | None = None) -> models.ArtistProfile:
    profile = demo_data.DEMO_PROFILES.get(entity_id)
    if profile is None:
        return models.ArtistProfile(
            entity_id=entity_id,
            name=name,
            source="demo",
            missing=True,
            note="No demo profile for this entity — treated as missing data.",
        )
    return models.ArtistProfile(
        entity_id=entity_id,
        name=name or profile.get("name"),
        source="demo",
        missing=profile.get("missing", False),
        note=profile.get("note"),
        genre_tags=profile.get("genre_tags", []),
        canonical_genre_tags=sorted(
            {canonical_genre_tag(tag) for tag in profile.get("genre_tags", [])}
        ),
        audience_tags=profile.get("audience_tags", []),
        style_tags=profile.get("style_tags", []),
        music_tags=profile.get("music_tags", []),
    )


def _unmatched_profile(entity_id: str, name: str | None) -> models.ArtistProfile:
    """An imported artist the user has not matched to a Qloo entity."""
    return models.ArtistProfile(
        entity_id=entity_id,
        name=name,
        source="unmatched",
        missing=True,
        note=(
            "Not matched to a Qloo entity — no taste data. "
            "Resolve the artist name on Qloo to include it in similarity scoring."
        ),
    )


async def _resolve_profiles(
    entity_ids: list[str], names: dict[str, str]
) -> list[models.ArtistProfile]:
    """Resolve profiles in request order, fetching each entity id at most once."""
    by_id: dict[str, models.ArtistProfile] = {}
    live_ids: list[str] = []
    for entity_id in entity_ids:
        if entity_id in by_id:
            continue
        cleaned = entity_id.strip()
        if not cleaned or cleaned.startswith(config.UNMATCHED_ENTITY_PREFIX):
            by_id[entity_id] = _unmatched_profile(entity_id, names.get(entity_id))
        elif cleaned.startswith(config.DEMO_ENTITY_PREFIX):
            by_id[entity_id] = _demo_profile(entity_id, names.get(entity_id))
        else:
            live_ids.append(entity_id)

    if live_ids and not qloo_client.configured:
        raise _api_error(
            503,
            "QLOO_NOT_CONFIGURED",
            "QLOO_API_KEY is not set, so live Qloo profiles are unavailable. "
            "Set QLOO_API_KEY in backend/.env, or use demo data.",
        )

    for entity_id in dict.fromkeys(live_ids):
        cached = profile_cache.get(entity_id)
        if cached is None:
            failed = False
            try:
                cached = await fetch_profile(qloo_client, search_record_cache, entity_id)
            except QlooNotConfigured as exc:
                raise _api_error(503, "QLOO_NOT_CONFIGURED", str(exc)) from exc
            except QlooError as exc:
                failed = True
                cached = {
                    "entity_id": entity_id,
                    "source": "qloo-insights",
                    "missing": True,
                    "note": f"Qloo unavailable: {exc}",
                    "genre_tags": [],
                    "canonical_genre_tags": [],
                    "audience_tags": [],
                    "style_tags": [],
                    "music_tags": [],
                }
            # A timeout or a 5xx that left us with no tags says nothing about the
            # artist, so it must not be remembered: caching it would report the act
            # as profile-less for a whole TTL even after Qloo recovers.
            if not failed and not cached.get("provider_failed"):
                profile_cache.set(entity_id, cached)
        by_id[entity_id] = models.ArtistProfile(
            entity_id=entity_id,
            name=names.get(entity_id),
            source=cached["source"],
            missing=cached["missing"],
            note=cached.get("note"),
            genre_tags=cached.get("genre_tags", []),
            canonical_genre_tags=cached.get("canonical_genre_tags", []),
            audience_tags=cached.get("audience_tags", []),
            style_tags=cached.get("style_tags", []),
            music_tags=cached.get("music_tags", []),
        )
    return [by_id[entity_id] for entity_id in dict.fromkeys(entity_ids)]


@app.post("/api/profiles", response_model=list[models.ArtistProfile])
async def get_profiles(body: models.ProfileRequest) -> list[models.ArtistProfile]:
    return await _resolve_profiles(body.entity_ids, body.names)


@app.post("/api/similarity", response_model=models.SimilarityResponse)
async def similarity(body: models.SimilarityRequest) -> models.SimilarityResponse:
    profiles = await _resolve_profiles(body.entity_ids, body.names)
    profile_dicts = [p.model_dump() for p in profiles]
    pairs = similarity_engine.similarity_matrix(profile_dicts)

    # "unmatched" is an absence of data, not a source: a live lineup with one
    # unresolved name is still a live analysis (and carries a missing-data warning).
    data_sources = {p.source for p in profiles} - {"unmatched"}
    live_sources = {"qloo-insights", "qloo-search"}
    if not data_sources:
        mode = "unmatched"
    elif data_sources <= {"demo"}:
        mode = "demo"
    elif data_sources <= live_sources:
        mode = "live"
    else:
        mode = "mixed"

    warnings = [
        f"{p.name or p.entity_id or 'Unnamed act'}: {p.note}"
        for p in profiles
        if p.missing and p.note
    ]

    return models.SimilarityResponse(
        mode=mode,
        profiles=profiles,
        pairs=[models.SimilarityPair(**pair) for pair in pairs],
        methods=similarity_engine.METHODS,
        coverage=similarity_engine.coverage(profile_dicts, pairs),
        warnings=warnings,
    )


@app.post("/api/optimize", response_model=models.OptimizeResponse)
async def optimize(body: models.OptimizeRequest) -> models.OptimizeResponse:
    try:
        schedule = optimizer_mod.Schedule.from_payload(body.stages, body.slots, body.acts)
    except optimizer_mod.ScheduleError as exc:
        raise _api_error(422, "INVALID_SCHEDULE", str(exc)) from exc

    entity_ids = list({act.entity_id for act in body.acts})
    names = {act.entity_id: act.name for act in body.acts}
    profiles = await _resolve_profiles(entity_ids, names)
    profile_map = {p.entity_id: p.model_dump() for p in profiles}

    similarities = {}
    for pair in similarity_engine.similarity_matrix(list(profile_map.values())):
        similarities[tuple(sorted((pair["a"], pair["b"])))] = pair

    prefs = optimizer_mod.Preferences(**body.preferences.model_dump())
    result = optimizer_mod.optimize_schedule(schedule, similarities, prefs)

    def clash_to_model(clash) -> models.ClashInfo:
        act_a, act_b, value, method = clash
        pair = similarities.get(
            optimizer_mod.Schedule.pair_key(act_a.entity_id, act_b.entity_id)
        )
        return models.ClashInfo(
            a_id=act_a.id,
            a_name=act_a.name,
            b_id=act_b.id,
            b_name=act_b.name,
            stage_a=act_a.stage_id,
            stage_b=act_b.stage_id,
            slot_a=act_a.slot_id,
            slot_b=act_b.slot_id,
            similarity=round(value, 4),
            method=method,
            signals=[
                models.SimilaritySignal(**signal) for signal in (pair or {}).get("signals", [])
            ],
            low_confidence=bool((pair or {}).get("low_confidence", False)),
            confidence_note=(pair or {}).get("confidence_note"),
            genre_backed=bool((pair or {}).get("genre_backed", False)),
            shared_tag_count=int((pair or {}).get("shared_tag_count", 0)),
            shared_generic_tag_count=int(
                (pair or {}).get("shared_generic_tag_count", 0)
            ),
            generic_share=float((pair or {}).get("generic_share", 0.0)),
            shared_specific_tag_count=int(
                (pair or {}).get("shared_specific_tag_count", 0)
            ),
            broad_share=float((pair or {}).get("broad_share", 0.0)),
            profile_sources=(pair or {}).get("profile_sources", {}),
            evidence_limitations=(pair or {}).get("evidence_limitations", []),
        )

    fixed_clashes = [
        clash_to_model((entry["a"], entry["b"], entry["value"], entry["method"]))
        for entry in result["fixed_clashes"]
    ]
    # Locked headliners are their own category (`fixed_clashes`). They are not
    # missing data, so they must never be folded into the coverage exclusions.

    percent = None
    initial_objective = result["before"]["objective"]
    if initial_objective > 0 and result["improvement"] > 0:
        percent = round(result["improvement"] / initial_objective * 100, 1)

    excluded_entries = result["excluded_pairs"]
    if len(excluded_entries) > MAX_EXCLUDED_PAIRS:
        hidden = len(excluded_entries) - MAX_EXCLUDED_PAIRS
        excluded_entries = excluded_entries[:MAX_EXCLUDED_PAIRS] + [
            {
                "a_name": f"+{hidden} more pair(s)",
                "b_name": "",
                "reason": "Excluded from the objective — missing taste data.",
            }
        ]

    # The proposal is validated as a schedule before anyone can apply it.
    proposed = [models.Act(**act.__dict__) for act in result["optimized_acts"]]
    check = optimizer_mod.validate_schedule(body.stages, body.slots, proposed)
    if not check["valid"]:
        logger.error("optimizer produced an invalid schedule: %s", check["issues"])

    return models.OptimizeResponse(
        objective_description=optimizer_mod.OBJECTIVE_DESCRIPTION,
        preferences=body.preferences,
        preferences_description=result["preferences_description"],
        before=result["before"],
        after=result["after"],
        initial_cost=result["initial_cost"],
        optimized_cost=result["optimized_cost"],
        improvement=result["improvement"],
        improved=result["improved"],
        percent_improvement=percent,
        limit_reached=result["limit_reached"],
        valid=check["valid"],
        validation_issues=check["issues"],
        initial_clashes=[clash_to_model(c) for c in result["initial_clashes"]],
        optimized_clashes=[clash_to_model(c) for c in result["optimized_clashes"]],
        moves=[models.MoveInfo(**move) for move in result["moves"]],
        moved_acts=[models.MovedAct(**entry) for entry in result["moved_acts"]],
        unresolved=[models.UnresolvedClash(**entry) for entry in result["unresolved"]],
        excluded_pairs=[models.ExcludedPair(**entry) for entry in excluded_entries],
        fixed_clashes=fixed_clashes,
        optimized_acts=proposed,
    )


@app.post("/api/schedule/validate", response_model=models.ScheduleValidateResponse)
async def validate_schedule(body: models.ScheduleValidateRequest) -> models.ScheduleValidateResponse:
    """Check a schedule against every hard constraint. Offline, no Qloo calls."""
    result = optimizer_mod.validate_schedule(body.stages, body.slots, body.acts)
    return models.ScheduleValidateResponse(**result)


@app.post("/api/schedule/assign", response_model=models.ScheduleAssignResponse)
async def assign_schedule(body: models.ScheduleAssignRequest) -> models.ScheduleAssignResponse:
    """Place acts without a valid cell into free cells (greedy, valid-only)."""
    try:
        result = optimizer_mod.assign_schedule(body.stages, body.slots, body.acts)
    except optimizer_mod.ScheduleError as exc:
        raise _api_error(422, "INVALID_SCHEDULE", str(exc)) from exc
    return models.ScheduleAssignResponse(
        acts=[models.Act(**act.__dict__) for act in result["acts"]],
        note=result["note"],
    )


@app.post("/api/plan/interpret", response_model=models.PlanInterpretResponse)
async def interpret_plan(
    body: models.PlanInterpretRequest,
    llm: planner.PlannerLLM = Depends(get_planner_llm),
) -> models.PlanInterpretResponse:
    """Turn one plain-English scheduling request into validated optimizer priorities.

    Offline and non-mutating: no Qloo call, and no act is moved or locked here. The
    plan says what the next /api/optimize run should value; the user runs it, and the
    existing Apply gate still decides whether the proposal reaches the schedule.
    """
    instruction = body.instruction.strip()
    if not instruction:
        raise _api_error(422, "EMPTY_INSTRUCTION", "The planning instruction is empty.")
    try:
        schedule = optimizer_mod.Schedule.from_payload(body.stages, body.slots, body.acts)
    except optimizer_mod.ScheduleError as exc:
        raise _api_error(422, "INVALID_SCHEDULE", " ".join(exc.issues)) from exc

    plan = await planner.interpret_plan(schedule, instruction, llm=llm)
    return models.PlanInterpretResponse(instruction=instruction, **plan)
