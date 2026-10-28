"""API-level tests via FastAPI TestClient. No network, no real key."""
import pytest
from fastapi.testclient import TestClient

from app import demo_data
from app import main as app_main
from app.qloo import QlooNotConfigured


@pytest.fixture()
def client():
    with TestClient(app_main.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.setattr(app_main.qloo_client, "api_key", "")
    app_main.profile_cache.clear()
    app_main.search_record_cache.clear()
    app_main.resolve_cache.clear()
    yield


def demo_payload():
    return {
        "stages": demo_data.DEMO_FESTIVAL["stages"],
        "slots": demo_data.DEMO_FESTIVAL["slots"],
        "acts": demo_data.DEMO_FESTIVAL["acts"],
    }


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["qloo_configured"] is False


def test_demo_festival(client):
    response = client.get("/api/demo/festival")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert len(body["acts"]) == 20
    assert all(act["entity_id"].startswith("demo:") for act in body["acts"])


def test_similarity_demo_works_offline(client):
    entity_ids = [act["entity_id"] for act in demo_data.DEMO_FESTIVAL["acts"]]
    names = {act["entity_id"]: act["name"] for act in demo_data.DEMO_FESTIVAL["acts"]}
    response = client.post("/api/similarity", json={"entity_ids": entity_ids, "names": names})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert len(body["pairs"]) == 190
    enigma = next(p for p in body["profiles"] if p["entity_id"] == "demo:enigma-collective")
    assert enigma["missing"] is True
    missing_pairs = [p for p in body["pairs"] if p["missing"]]
    assert missing_pairs, "enigma pairs should be flagged missing"
    assert all(p["genre_similarity"] is None for p in missing_pairs)


def test_similarity_exposes_signals_and_coverage(client):
    entity_ids = [act["entity_id"] for act in demo_data.DEMO_FESTIVAL["acts"]]
    names = {act["entity_id"]: act["name"] for act in demo_data.DEMO_FESTIVAL["acts"]}
    body = client.post(
        "/api/similarity", json={"entity_ids": entity_ids, "names": names}
    ).json()

    assert "taste_blend" in body["methods"]
    scored = [p for p in body["pairs"] if not p["missing"]]
    assert scored
    for pair in scored:
        assert pair["taste_similarity"] is not None
        assert pair["signals"], "a scored pair must name the signals behind it"
        assert sum(s["contribution"] for s in pair["signals"]) == pytest.approx(
            pair["taste_similarity"], abs=1e-3
        )
        assert pair["categories_compared"] == [s["category"] for s in pair["signals"]]

    stats = body["coverage"]
    assert stats["profiles_total"] == len(entity_ids)
    assert stats["profiles_missing"] == stats["profiles_total"] - stats["profiles_with_data"]
    assert stats["pairs_scored"] + stats["pairs_missing"] == stats["pairs_total"]
    assert stats["category_coverage"]["genre"]["weight"] == 0.55


def test_similarity_normalizes_genre_namespaces_across_sources(client, monkeypatch):
    """An insights profile and a search-fallback profile must be comparable."""
    from app.qloo import ArtistRecord, TagSet

    class FakeQloo:
        configured = True

        async def insights_tags(self, entity_id, take=None):
            if entity_id == "E-INSIGHTS":
                return [
                    {"tag_id": "urn:tag:genre:music:folk",
                     "subtype": "urn:tag:genre:music"},
                    {"tag_id": "urn:tag:genre:music:indie_folk",
                     "subtype": "urn:tag:genre:music"},
                    {"tag_id": "urn:tag:audience:qloo:students",
                     "subtype": "urn:tag:audience:qloo"},
                    {"tag_id": "urn:tag:audience:qloo:record_collectors",
                     "subtype": "urn:tag:audience:qloo"},
                    {"tag_id": "urn:tag:style:qloo:acoustic",
                     "subtype": "urn:tag:style:qloo"},
                    {"tag_id": "urn:tag:style:qloo:storytelling",
                     "subtype": "urn:tag:style:qloo"},
                ]
            return []  # forces the search fallback for E-SEARCH

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    app_main.profile_cache.clear()
    app_main.search_record_cache.clear()
    app_main.search_record_cache.set(
        "E-SEARCH",
        ArtistRecord(
            name="Fallback Artist",
            tags=TagSet(
                genre={
                    "urn:tag:genre:qloo:folk",
                    "urn:tag:genre:qloo:indie_folk",
                },
                audience={
                    "urn:tag:audience:qloo:students",
                    "urn:tag:audience:qloo:record_collectors",
                },
                style={
                    "urn:tag:style:qloo:acoustic",
                    "urn:tag:style:qloo:storytelling",
                },
            ),
        ),
    )
    body = client.post(
        "/api/similarity",
        json={
            "entity_ids": ["E-INSIGHTS", "E-SEARCH"],
            "names": {"E-INSIGHTS": "Insights Artist", "E-SEARCH": "Fallback Artist"},
        },
    ).json()

    profiles = {p["entity_id"]: p for p in body["profiles"]}
    fallback = profiles["E-SEARCH"]
    assert fallback["source"] == "qloo-search"
    assert set(fallback["genre_tags"]) == {
        "urn:tag:genre:qloo:folk",
        "urn:tag:genre:qloo:indie_folk",
    }
    assert set(fallback["canonical_genre_tags"]) == {
        "urn:tag:genre:music:folk",
        "urn:tag:genre:music:indie_folk",
    }

    pair = body["pairs"][0]
    assert pair["genre_similarity"] == 1.0
    assert pair["genre_backed"] is True
    assert pair["shared_tag_count"] == 6
    assert pair["shared_generic_tag_count"] == 0
    assert pair["generic_share"] == 0.0
    assert pair["shared_specific_tag_count"] == 6
    assert pair["broad_share"] == 0.0
    assert pair["profile_sources"] == {
        "a": "qloo-insights",
        "b": "qloo-search",
    }
    assert pair["low_confidence"] is False


def test_optimize_clashes_report_contributing_signals(client):
    body = client.post("/api/optimize", json=demo_payload()).json()
    clash = body["initial_clashes"][0]
    assert clash["method"] == "taste_blend"
    assert clash["signals"], "a clash must explain which tag categories produced it"
    assert {s["category"] for s in clash["signals"]} <= {"genre", "audience", "style", "music"}
    assert any(s["shared_tags"] for s in clash["signals"]), "clashes must name shared tags"
    assert sum(s["contribution"] for s in clash["signals"]) == pytest.approx(
        clash["similarity"], abs=1e-3
    )
    # the clash list carries the same confidence verdict as the matrix
    assert clash["low_confidence"] is False, "demo profiles compare on several categories"
    assert clash["confidence_note"] is None
    # and the evidence behind that verdict is exported, not hidden
    assert isinstance(clash["genre_backed"], bool)
    assert clash["shared_tag_count"] >= clash["shared_specific_tag_count"] >= 0
    assert clash["shared_tag_count"] >= clash["shared_generic_tag_count"] >= 0
    assert 0.0 <= clash["generic_share"] <= 1.0
    assert clash["profile_sources"] == {"a": "demo", "b": "demo"}
    assert isinstance(clash["evidence_limitations"], list)


def test_similarity_live_without_key_returns_503(client):
    response = client.post(
        "/api/similarity",
        json={"entity_ids": ["REAL-ENTITY-ID"], "names": {"REAL-ENTITY-ID": "Radiohead"}},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "QLOO_NOT_CONFIGURED"


def test_search_without_key_returns_clear_error(client):
    response = client.post("/api/artists/search", json={"query": "Radiohead"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "QLOO_NOT_CONFIGURED"
    assert "QLOO_API_KEY" in detail["message"]


def test_search_with_mocked_qloo(client, monkeypatch):
    class FakeQloo:
        configured = True

        async def search_artists(self, query, record_cache=None):
            return [
                {
                    "name": "Radiohead",
                    "entity_id": "ID-1",
                    "types": ["urn:entity:artist"],
                    "popularity": 0.99,
                    "properties": {"short_description": "English rock band"},
                },
                {
                    "name": "Radiohead Tribute",
                    "entity_id": "ID-2",
                    "types": ["urn:entity:artist"],
                    "popularity": 0.2,
                    "properties": {"short_description": "tribute act"},
                },
            ]

    app_main.app.dependency_overrides[app_main.get_qloo] = lambda: FakeQloo()
    try:
        response = client.post("/api/artists/search", json={"query": "Radiohead"})
    finally:
        app_main.app.dependency_overrides.pop(app_main.get_qloo, None)

    assert response.status_code == 200
    body = response.json()
    assert body["best_match"]["entity_id"] == "ID-1"
    assert len(body["candidates"]) == 2


def test_ambiguous_search_selects_no_entity(client, monkeypatch):
    """Two equally plausible artists must be confirmed, never auto-selected."""

    class FakeQloo:
        configured = True

        async def search_artists(self, query, record_cache=None):
            return [
                {"name": "Muse", "entity_id": "ID-M1", "types": ["urn:entity:artist"],
                 "popularity": 0.8, "disambiguation": "English rock band"},
                {"name": "Muse", "entity_id": "ID-M2", "types": ["urn:entity:artist"],
                 "popularity": 0.78, "disambiguation": "K-pop group"},
            ]

    app_main.app.dependency_overrides[app_main.get_qloo] = lambda: FakeQloo()
    try:
        body = client.post("/api/artists/search", json={"query": "Muse"}).json()
    finally:
        app_main.app.dependency_overrides.pop(app_main.get_qloo, None)

    assert body["ambiguous"] is True
    assert body["best_match"] is None, "an ambiguous name must not carry a confirmed match"
    assert [c["entity_id"] for c in body["candidates"]] == ["ID-M1", "ID-M2"]


def test_optimize_demo_improves(client):
    response = client.post("/api/optimize", json=demo_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["initial_cost"] > body["optimized_cost"]
    assert body["improvement"] > 0
    assert body["moves"]
    assert body["fixed_clashes"], "locked headliners should remain clashing"
    assert len(body["optimized_acts"]) == 20
    # optimized assignment is valid: no double booking
    cells = [(a["stage_id"], a["slot_id"]) for a in body["optimized_acts"]]
    assert len(cells) == len(set(cells))


def test_fixed_headliner_clashes_are_not_reported_as_missing_data(client):
    """Locked clashes have their own category; coverage exclusions stay about data."""
    payload = demo_payload()
    body = client.post("/api/optimize", json=payload).json()

    assert body["fixed_clashes"], "locked headliners should remain clashing"
    assert all(
        entry["a_name"] != "Fixed acts" for entry in body["excluded_pairs"]
    ), "the old pseudo-entry must be gone"
    # Every excluded name belongs to a real act, and every reason is about data.
    names = {act["name"] for act in payload["acts"]}
    for entry in body["excluded_pairs"]:
        assert entry["a_name"] in names and entry["b_name"] in names
        assert entry["reason"].startswith(("Missing taste profile", "Both artists have tags"))


def test_optimize_invalid_schedule_422(client):
    payload = demo_payload()
    # double-book main t1: Iron Howl already there, move Desert Winds onto it
    payload["acts"] = [dict(a) for a in payload["acts"]]
    for act in payload["acts"]:
        if act["id"] == "a18":
            act["stage_id"] = "main"
            act["slot_id"] = "t1"
    response = client.post("/api/optimize", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_SCHEDULE"


def test_optimize_live_acts_without_key_503(client):
    payload = demo_payload()
    payload["acts"] = [dict(a) for a in payload["acts"]]
    for act in payload["acts"]:
        act["entity_id"] = "REAL-" + act["entity_id"]
    response = client.post("/api/optimize", json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "QLOO_NOT_CONFIGURED"


def test_optimize_respects_missing_profiles(client):
    response = client.post("/api/optimize", json=demo_payload())
    body = response.json()
    assert any(
        "Enigma" in pair["a_name"] or "Enigma" in pair["b_name"]
        for pair in body["excluded_pairs"]
    )


def test_optimize_flags_thin_evidence_in_clashes(client, monkeypatch):
    """A clash scored on one category is still a clash — but the list must say it is thin."""

    class FakeQloo:
        configured = True

        async def insights_tags(self, entity_id, take=None):
            return [
                {"tag_id": "urn:tag:genre:music:shoegaze", "subtype": "urn:tag:genre:music"},
            ]

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    app_main.profile_cache.clear()
    body = client.post(
        "/api/optimize",
        json={
            "stages": [{"id": "main", "name": "Main"}, {"id": "tent", "name": "Tent"}],
            "slots": [{"id": "t1", "label": "20:00", "start": "20:00", "end": "21:00"}],
            "acts": [
                {"id": "a1", "name": "One", "entity_id": "E-1", "stage_id": "main",
                 "slot_id": "t1", "duration_min": 60},
                {"id": "a2", "name": "Two", "entity_id": "E-2", "stage_id": "tent",
                 "slot_id": "t1", "duration_min": 60},
            ],
        },
    ).json()
    clash = body["initial_clashes"][0]
    assert clash["similarity"] == 1.0
    assert len(clash["signals"]) == 1
    assert clash["low_confidence"] is True
    assert "1 signal only" in clash["confidence_note"]


# --- Optimization priorities and validation ---

UNRESOLVED_KINDS = {
    "both_fixed", "no_legal_cell", "worse_objective", "move_limit", "local_optimum"
}


def test_optimize_measures_the_objective_the_user_asked_for(client):
    payload = demo_payload()
    payload["preferences"] = {
        "high_affinity_threshold": 0.5,
        "high_affinity_weight": 3.0,
        "move_penalty": 0.1,
        "max_moves": 3,
    }
    body = client.post("/api/optimize", json=payload).json()

    assert body["preferences"] == payload["preferences"], "the report echoes the priorities used"
    assert "3.0x" in body["preferences_description"]
    assert "0.1" in body["preferences_description"]

    before, after = body["before"], body["after"]
    assert set(before) == set(after) == {
        "raw_cost", "weighted_cost", "penalty", "objective",
        "clashes", "high_affinity_clashes", "churn", "excluded",
    }
    assert body["initial_cost"] == before["raw_cost"]
    assert body["optimized_cost"] == after["raw_cost"]
    assert after["penalty"] == pytest.approx(0.1 * after["churn"])
    assert after["objective"] == pytest.approx(after["weighted_cost"] + after["penalty"], abs=1e-4)
    assert body["improvement"] == pytest.approx(
        before["objective"] - after["objective"], abs=1e-4
    )
    assert body["improved"] is (after["objective"] < before["objective"])
    assert len(body["moves"]) <= 3
    assert {entry["act_id"] for entry in body["moved_acts"]} <= {
        act_id for move in body["moves"] for act_id in move["moved_act_ids"]
    }
    assert body["valid"] is True
    assert body["validation_issues"] == []


def test_optimize_stops_at_the_move_limit_and_reports_what_is_left(client):
    payload = demo_payload()
    payload["preferences"] = {"max_moves": 1}
    body = client.post("/api/optimize", json=payload).json()

    assert len(body["moves"]) == 1
    assert body["limit_reached"] is True
    assert body["after"]["raw_cost"] > 0, "one move cannot clear a 20-act festival"
    unresolved = body["unresolved"]
    assert unresolved, "the remaining clashes must be reported, not hidden"
    assert {entry["kind"] for entry in unresolved} <= UNRESOLVED_KINDS
    assert all(entry["reason"].strip() for entry in unresolved)
    act_ids = {act["id"] for act in payload["acts"]}
    assert all({entry["a_id"], entry["b_id"]} <= act_ids for entry in unresolved)
    assert all(0.0 <= entry["similarity"] <= 1.0 for entry in unresolved)


def test_optimize_never_claims_improvement_without_a_measured_drop(client):
    payload = demo_payload()
    payload["preferences"] = {"max_moves": 0}
    body = client.post("/api/optimize", json=payload).json()

    assert body["moves"] == [] and body["moved_acts"] == []
    assert body["improved"] is False
    assert body["improvement"] == 0.0
    assert body["percent_improvement"] is None
    assert body["before"] == body["after"]
    assert body["optimized_cost"] == body["initial_cost"]


def test_optimize_rejects_out_of_range_preferences(client):
    payload = demo_payload()
    payload["preferences"] = {"high_affinity_weight": 50.0}
    response = client.post("/api/optimize", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list), "pydantic reports the offending field"


def test_schedule_validate_accepts_a_legal_lineup(client):
    response = client.post("/api/schedule/validate", json=demo_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["issues"] == []
    assert body["acts"] == 20
    assert body["fixed_acts"], "the demo festival locks headliners"
    assert body["overlapping_pairs"] > 0
    assert any("fixed acts" in constraint for constraint in body["constraints_checked"])


def test_schedule_validate_lists_every_problem_instead_of_failing(client):
    payload = demo_payload()
    payload["acts"] = [dict(act) for act in payload["acts"]]
    for act in payload["acts"]:
        if act["id"] == "a18":  # move onto an occupied cell
            act["stage_id"], act["slot_id"] = "main", "t1"
        if act["id"] == "a2":  # a set longer than its 60-minute slot
            act["duration_min"] = 120
    response = client.post("/api/schedule/validate", json=payload)
    assert response.status_code == 200, "an invalid schedule is a report, not a server error"
    body = response.json()
    assert body["valid"] is False
    assert len(body["issues"]) == 2
    assert any("double-booked" in issue for issue in body["issues"])
    assert any("does not fit" in issue for issue in body["issues"])
    assert body["acts"] == 20


def test_schedule_validate_rejects_overlapping_slots_on_one_stage(client):
    body = client.post(
        "/api/schedule/validate",
        json={
            "stages": [{"id": "main", "name": "Main"}],
            "slots": [
                {"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"},
                {"id": "t2", "label": "17:30", "start": "17:30", "end": "18:30"},
            ],
            "acts": [
                {"id": "a1", "name": "A", "entity_id": "E1", "stage_id": "main", "slot_id": "t1"},
                {"id": "a2", "name": "B", "entity_id": "E2", "stage_id": "main", "slot_id": "t2"},
            ],
        },
    ).json()
    assert body["valid"] is False
    assert any("overlapping sets" in issue for issue in body["issues"])
    assert not any("double-booked" in issue for issue in body["issues"])


def test_schedule_validate_rejects_unknown_references(client):
    payload = demo_payload()
    payload["acts"] = [dict(act) for act in payload["acts"]]
    payload["acts"][0]["stage_id"] = "ghost-stage"
    body = client.post("/api/schedule/validate", json=payload).json()
    assert body["valid"] is False
    assert any("ghost-stage" in issue for issue in body["issues"])


# --- Live-data endpoints ---

def test_festival_template(client):
    response = client.get("/api/festival/template")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "live"
    assert body["acts"] == []
    assert len(body["stages"]) >= 1
    assert len(body["slots"]) >= 1


def test_assign_places_unassigned_acts(client):
    stages = [{"id": "s1", "name": "Main"}, {"id": "s2", "name": "Second"}]
    slots = [
        {"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"},
        {"id": "t2", "label": "18:00", "start": "18:00", "end": "19:00"},
    ]
    acts = [
        {"id": "a1", "name": "Alpha", "entity_id": "E1", "stage_id": "s1", "slot_id": "t1"},
        {"id": "a2", "name": "Beta", "entity_id": "E2", "stage_id": "", "slot_id": ""},
        {"id": "a3", "name": "Gamma", "entity_id": "E3", "stage_id": "", "slot_id": ""},
    ]
    response = client.post("/api/schedule/assign", json={"stages": stages, "slots": slots, "acts": acts})
    assert response.status_code == 200
    body = response.json()
    placed = {a["name"]: (a["stage_id"], a["slot_id"]) for a in body["acts"]}
    assert placed["Alpha"] == ("s1", "t1"), "assigned acts keep their cell"
    cells = list(placed.values())
    assert len(cells) == len(set(cells)), "no double booking"
    assert placed["Beta"] != ("", "") and placed["Gamma"] != ("", "")


def test_assign_replaces_acts_on_removed_stage(client):
    stages = [
        {"id": "s1", "name": "Main"},
        {"id": "s2", "name": "Second"},
        {"id": "s3", "name": "Third"},
    ]
    slots = [
        {"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"},
        {"id": "t2", "label": "18:00", "start": "18:00", "end": "19:00"},
    ]
    acts = [
        {"id": "a1", "name": "Alpha", "entity_id": "E1", "stage_id": "s1", "slot_id": "t1"},
        {"id": "a2", "name": "Beta", "entity_id": "E2", "stage_id": "s2", "slot_id": "t1"},
        {"id": "a3", "name": "Gamma", "entity_id": "E3", "stage_id": "s2", "slot_id": "t2"},
    ]
    # remove s2 entirely; Beta and Gamma must be re-placed on the remaining stages
    response = client.post(
        "/api/schedule/assign",
        json={"stages": stages[:1] + stages[2:], "slots": slots, "acts": acts},
    )
    assert response.status_code == 200
    placed = {a["name"]: (a["stage_id"], a["slot_id"]) for a in response.json()["acts"]}
    assert placed["Alpha"] == ("s1", "t1"), "assigned acts keep their cell"
    assert placed["Beta"][0] != "s2" and placed["Gamma"][0] != "s2"
    cells = list(placed.values())
    assert len(cells) == len(set(cells)), "no double booking"


def test_assign_over_capacity_422(client):
    stages = [{"id": "s1", "name": "Main"}]
    slots = [{"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"}]
    acts = [
        {"id": f"a{i}", "name": f"Artist {i}", "entity_id": f"E{i}", "stage_id": "", "slot_id": ""}
        for i in range(3)
    ]
    response = client.post("/api/schedule/assign", json={"stages": stages, "slots": slots, "acts": acts})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_SCHEDULE"


def test_assign_fixed_act_on_removed_stage_422(client):
    stages = [{"id": "s1", "name": "Main"}]
    slots = [{"id": "t1", "label": "17:00", "start": "17:00", "end": "18:00"}]
    acts = [
        {"id": "a1", "name": "Headliner", "entity_id": "E1", "stage_id": "gone", "slot_id": "t1", "fixed": True},
    ]
    response = client.post("/api/schedule/assign", json={"stages": stages, "slots": slots, "acts": acts})
    assert response.status_code == 422
    assert "fixed" in response.json()["detail"]["message"].lower()


def test_similarity_live_partial_failure_reports_warnings(client, monkeypatch):
    from app.qloo import QlooUpstreamError

    class FakeQloo:
        configured = True

        async def insights_tags(self, entity_id, take=None):
            if entity_id == "E-BROKEN":
                raise QlooUpstreamError("Qloo request timed out: /v2/insights")
            return [
                {"tag_id": "urn:tag:genre:music:rock", "subtype": "urn:tag:genre:music"},
                {"tag_id": "urn:tag:genre:music:pop", "subtype": "urn:tag:genre:music"},
            ]

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    app_main.profile_cache.clear()
    response = client.post(
        "/api/similarity",
        json={
            "entity_ids": ["E-OK", "E-BROKEN"],
            "names": {"E-OK": "OK Artist", "E-BROKEN": "Broken Artist"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "live"
    broken = next(p for p in body["profiles"] if p["entity_id"] == "E-BROKEN")
    assert broken["missing"] is True
    assert any("Broken Artist" in w for w in body["warnings"])
    pairs = body["pairs"]
    assert pairs and pairs[0]["missing"] is True, "pairs with missing data are flagged, not scored zero"
    assert pairs[0]["missing_kind"] == "profile_data"


def test_similarity_cache_avoids_repeat_fetches(client, monkeypatch):
    calls = {"count": 0}

    class FakeQloo:
        configured = True

        async def insights_tags(self, entity_id, take=None):
            calls["count"] += 1
            return [
                {"tag_id": "urn:tag:genre:music:rock", "subtype": "urn:tag:genre:music"},
            ]

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    app_main.profile_cache.clear()
    payload = {
        "entity_ids": ["E-1", "E-2"],
        "names": {"E-1": "One", "E-2": "Two"},
    }
    assert client.post("/api/similarity", json=payload).status_code == 200
    assert client.post("/api/similarity", json=payload).status_code == 200
    assert calls["count"] == 2, "second request must be served from the profile cache"


def test_a_qloo_failure_is_not_cached_as_a_missing_profile(client, monkeypatch):
    """An outage says nothing about the artist, so the next request must retry."""
    from app.qloo import QlooUpstreamError

    calls = {"count": 0}

    class FlakyQloo:
        configured = True

        async def insights_tags(self, entity_id, take=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise QlooUpstreamError("Qloo request timed out: /v2/insights")
            return [
                {"tag_id": "urn:tag:genre:music:rock", "subtype": "urn:tag:genre:music"},
                {"tag_id": "urn:tag:genre:music:pop", "subtype": "urn:tag:genre:music"},
            ]

    monkeypatch.setattr(app_main, "qloo_client", FlakyQloo())
    app_main.profile_cache.clear()
    payload = {"entity_ids": ["E-FLAKY"], "names": {"E-FLAKY": "Flaky Act"}}

    first = client.post("/api/similarity", json=payload).json()
    assert first["profiles"][0]["missing"] is True
    assert "/v2/insights failed" in first["profiles"][0]["note"]

    second = client.post("/api/similarity", json=payload).json()
    assert calls["count"] == 2, "the failed lookup must not be remembered"
    assert second["profiles"][0]["missing"] is False
    assert second["profiles"][0]["genre_tags"], "a recovered provider returns real tags"


def test_live_lineup_with_one_unmatched_act_is_still_live_mode(client, monkeypatch):
    """An unresolved import name is missing data, not a different data source."""

    class FakeQloo:
        configured = True

        async def insights_tags(self, entity_id, take=None):
            return [
                {"tag_id": "urn:tag:genre:music:rock", "subtype": "urn:tag:genre:music"},
                {"tag_id": "urn:tag:genre:music:pop", "subtype": "urn:tag:genre:music"},
            ]

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    app_main.profile_cache.clear()
    response = client.post(
        "/api/similarity",
        json={
            "entity_ids": ["E-LIVE", "unmatched:a9"],
            "names": {"E-LIVE": "Live Act", "unmatched:a9": "Iron Lotus"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "live"
    assert [p["source"] for p in body["profiles"]] == ["qloo-insights", "unmatched"]
    assert body["pairs"][0]["missing"] is True
    assert any("Iron Lotus" in w for w in body["warnings"])


def test_search_upstream_failure_502(client, monkeypatch):
    from app.qloo import QlooUpstreamError

    class FakeQloo:
        configured = True

        async def search_artists(self, query, record_cache=None):
            raise QlooUpstreamError("Qloo returned HTTP 500 for /search.")

    app_main.app.dependency_overrides[app_main.get_qloo] = lambda: FakeQloo()
    try:
        response = client.post("/api/artists/search", json={"query": "Radiohead"})
    finally:
        app_main.app.dependency_overrides.pop(app_main.get_qloo, None)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "QLOO_UPSTREAM_ERROR"


# --- Lineup import ---

CSV_IMPORT = (
    "artist,stage,start,end,duration_min\n"
    "Radiohead,Main Stage,19:00,20:00,60\n"
    "Muse,Pulse Stage,19:00,20:00,60\n"
    "Daft Punk,Main Stage,21:00,22:15,75\n"
)


def test_import_parse_csv(client):
    response = client.post("/api/import/parse", json={"text": CSV_IMPORT})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["source_format"] == "csv"
    assert [s["name"] for s in body["stages"]] == ["Main Stage", "Pulse Stage"]
    assert [s["id"] for s in body["slots"]] == ["t1", "t2"]
    assert len(body["acts"]) == 3
    assert all(act["entity_id"] == "" for act in body["acts"])


def test_import_parse_pasted_text(client):
    response = client.post(
        "/api/import/parse",
        json={"text": "Radiohead - Main Stage - 19:00-20:00 (60 min)\nMuse - Pulse Stage - 21:00-22:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["source_format"] == "text"
    assert len(body["acts"]) == 2


def test_import_parse_reports_conflicts(client):
    response = client.post(
        "/api/import/parse",
        json={
            "text": "artist,stage,start,end\n"
            "Radiohead,Main Stage,19:00,20:00\n"
            "Muse,Main Stage,19:00,20:00\n"
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("Double booking" in issue["message"] for issue in body["issues"])


def test_import_parse_unparseable_422(client):
    response = client.post("/api/import/parse", json={"text": "   \n  "})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "IMPORT_UNPARSEABLE"


def test_import_resolve_without_key_503(client):
    response = client.post("/api/import/resolve", json={"names": ["Radiohead"]})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "QLOO_NOT_CONFIGURED"
    assert "QLOO_API_KEY" in detail["message"]


def test_import_resolve_statuses(client, monkeypatch):
    from app.qloo import QlooUpstreamError

    class FakeQloo:
        configured = True

        async def search_artists(self, query, record_cache=None):
            if query == "Radiohead":
                return [
                    {
                        "name": "Radiohead",
                        "entity_id": "ID-RH",
                        "types": ["urn:entity:artist"],
                        "popularity": 0.99,
                        "properties": {"short_description": "English rock band"},
                    }
                ]
            if query == "Muse":
                return [
                    {"name": "Muse", "entity_id": "ID-M1", "types": ["urn:entity:artist"],
                     "popularity": 0.8, "disambiguation": "English rock band"},
                    {"name": "Muse", "entity_id": "ID-M2", "types": ["urn:entity:artist"],
                     "popularity": 0.78, "disambiguation": "K-pop group"},
                ]
            if query == "NoSuchBand":
                return []
            raise QlooUpstreamError("Qloo request timed out: /search")

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    response = client.post(
        "/api/import/resolve",
        json={"names": ["Radiohead", "Muse", "NoSuchBand", "Broken"]},
    )
    assert response.status_code == 200
    body = response.json()
    by_query = {m["query"]: m for m in body["matches"]}
    assert by_query["Radiohead"]["status"] == "matched"
    assert by_query["Radiohead"]["match"]["entity_id"] == "ID-RH"
    assert by_query["Muse"]["status"] == "ambiguous"
    assert by_query["Muse"]["match"] is None, "ambiguous names must not auto-select an entity"
    assert "confirm" in by_query["Muse"]["note"].lower()
    assert len(by_query["Muse"]["candidates"]) == 2, "ambiguous names expose their candidates"
    assert by_query["NoSuchBand"]["status"] == "not_found"
    assert by_query["NoSuchBand"]["match"] is None
    assert by_query["Broken"]["status"] == "error"
    assert "timed out" in by_query["Broken"]["note"]
    assert body["resolved"] == 1
    assert body["needs_confirmation"] == 1
    assert body["unresolved"] == 1
    assert body["failed"] == 1


def test_import_resolve_caches_and_dedupes(client, monkeypatch):
    calls = []

    class FakeQloo:
        configured = True

        async def search_artists(self, query, record_cache=None):
            calls.append(query)
            return [
                {"name": "Radiohead", "entity_id": "ID-RH", "types": ["urn:entity:artist"],
                 "popularity": 0.99}
            ]

    monkeypatch.setattr(app_main, "qloo_client", FakeQloo())
    payload = {"names": ["Radiohead", "radiohead", "RADIOHEAD"]}
    first = client.post("/api/import/resolve", json=payload)
    second = client.post("/api/import/resolve", json=payload)
    assert first.status_code == 200 and second.status_code == 200
    assert len(first.json()["matches"]) == 1, "duplicate names are resolved once"
    assert calls == ["Radiohead"], "repeat requests are served from the resolve cache"
    assert second.json()["matches"][0]["cached"] is True


def test_unmatched_acts_are_missing_data_not_zero_similarity(client):
    """Imported artists without a confirmed Qloo match must not be scored."""
    response = client.post(
        "/api/similarity",
        json={
            "entity_ids": ["", "unmatched:a2", "unmatched:a3"],
            "names": {
                "": "Radiohead",
                "unmatched:a2": "Muse",
                "unmatched:a3": "Björk",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "unmatched"
    assert body["pairs"][0]["missing"] is True
    assert body["pairs"][0]["genre_similarity"] is None
    assert all(pair["missing"] for pair in body["pairs"])
    # one honest warning per act, named correctly, never a fabricated profile
    assert len(body["warnings"]) == 3
    assert sorted(w.split(":")[0] for w in body["warnings"]) == ["Björk", "Muse", "Radiohead"]
    assert all("Not matched to a Qloo entity" in w for w in body["warnings"])
    assert [p["source"] for p in body["profiles"]] == ["unmatched"] * 3
