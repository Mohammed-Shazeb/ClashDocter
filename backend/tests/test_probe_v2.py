"""Offline tests for probe v2. No network calls are made.

The probe reuses app.qloo and app.similarity; these tests inject a fake Qloo
client so the whole run, the analysis and the Markdown rendering stay offline.
"""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import config
from app.qloo import (
    ArtistRecord,
    QlooClient,
    QlooUpstreamError,
    tags_from_search_entity,
)
from probe.v2 import (
    CachedQlooClient,
    ProbeConfigError,
    ProbeDatasetError,
    _cache_key,
    dataset_digest,
    is_transient_message,
    load_dataset,
    main,
    run_probe_v2,
    validate_dataset,
)
from probe.v2_report import render_markdown, write_v2_reports

GENRE = "urn:tag:genre:music:"
GENRE_SUBTYPE = "urn:tag:genre:music"
AUDIENCE_SUBTYPE = "urn:tag:audience:qloo"
STYLE_SUBTYPE = "urn:tag:style:qloo"
MUSIC_SUBTYPE = "urn:tag:music:qloo"
ALTERNATIVE = f"{GENRE}alternative"
SPARSE_ARTIST = "ar-rahman"
MISSING_ARTISTS = {"sza", "bts", "blackpink", "metallica", "shreya-ghoshal"}

# Artists moved into a shared synthetic bucket so the five predeclared sanity
# pairs get deterministic evidence. Everything else uses index % 5.
BUCKET_OVERRIDES = {
    "aphex-twin": 0,
    "the-chemical-brothers": 5,
    "daft-punk": 5,
    "kendrick-lamar": 6,
    "drake": 6,
    "bad-bunny": 9,
}


def _tag(tag_id, subtype):
    return {"tag_id": tag_id, "subtype": subtype}


def _synthetic_tags(artist_id, index):
    if artist_id == SPARSE_ARTIST:
        return [_tag(f"{GENRE}g2a", GENRE_SUBTYPE)]
    bucket = BUCKET_OVERRIDES.get(artist_id, index % 5)
    tags = [
        _tag(f"{GENRE}g{bucket}a", GENRE_SUBTYPE),
        _tag(f"{GENRE}g{bucket}b", GENRE_SUBTYPE),
        _tag(f"urn:tag:audience:qloo:aud{bucket}", AUDIENCE_SUBTYPE),
        _tag(f"urn:tag:style:qloo:sty{bucket}", STYLE_SUBTYPE),
        _tag(f"urn:tag:music:qloo:mus{bucket}", MUSIC_SUBTYPE),
    ]
    if bucket in (0, 3):
        tags.append(_tag(ALTERNATIVE, GENRE_SUBTYPE))
    return tags


def _search_result(artist, tags=None):
    result = {
        "name": artist["query"],
        "entity_id": f"fake:{artist['id']}",
        "types": ["urn:entity:artist"],
        "popularity": 0.5,
        "disambiguation": "synthetic fixture entity",
    }
    if tags is not None:
        result["tags"] = tags
    return result


class FakeQlooClient:
    """Deterministic stand-in for QlooClient; records every call."""

    configured = True
    base_url = "https://synthetic.invalid"

    def __init__(self):
        self.dataset = load_dataset()
        self.search_calls = []
        self.insights_calls = []
        self.search_errors = {}
        self.insights_errors = {}
        self.search_by_query = {}
        self.tags_by_entity = {}
        for index, artist in enumerate(self.dataset["artists"]):
            artist_id = artist["id"]
            query = artist["query"]
            if artist_id == "bts":
                self.search_errors[query] = QlooUpstreamError(
                    "Qloo returned HTTP 500 for /search."
                )
            if artist_id == "sza":
                self.search_by_query[query] = [
                    _search_result(artist),
                    _search_result(artist),
                ]
                for suffix in ("1", "2"):
                    self.search_by_query[query][-1 if suffix == "2" else 0][
                        "entity_id"
                    ] = f"fake:sza:{suffix}"
            elif artist_id == "blackpink":
                self.search_by_query[query] = []
            elif artist_id == "fela-kuti":
                self.search_by_query[query] = [
                    _search_result(
                        artist,
                        tags=[
                            {"tag_id": "urn:tag:genre:afrobeat"},
                            {"tag_id": "urn:tag:genre:music:world"},
                            {"tag_id": "urn:tag:style:qloo:energetic"},
                        ],
                    )
                ]
            else:
                self.search_by_query[query] = [_search_result(artist)]

            entity_id = f"fake:{artist_id}"
            if artist_id == "metallica":
                self.insights_errors[entity_id] = QlooUpstreamError(
                    "Qloo returned HTTP 500 for /v2/insights."
                )
            if artist_id in {"fela-kuti", "shreya-ghoshal"}:
                self.tags_by_entity[entity_id] = []
            else:
                self.tags_by_entity[entity_id] = _synthetic_tags(artist_id, index)

    async def search_artists(self, query, record_cache=None):
        self.search_calls.append(query)
        if query in self.search_errors:
            raise self.search_errors[query]
        results = self.search_by_query.get(query, [])
        for item in results:
            entity_id = item.get("entity_id")
            if record_cache is not None and entity_id:
                if record_cache.get(entity_id) is None:
                    record_cache.set(
                        entity_id,
                        ArtistRecord(
                            name=item.get("name"),
                            tags=tags_from_search_entity(item.get("tags") or []),
                        ),
                    )
        return results

    async def insights_tags(self, entity_id, take=None):
        self.insights_calls.append((entity_id, take))
        if entity_id in self.insights_errors:
            raise self.insights_errors[entity_id]
        return self.tags_by_entity.get(entity_id, [])


@pytest.fixture(scope="module")
def scenario():
    client = FakeQlooClient()
    report = asyncio.run(run_probe_v2(client=client, depth_pairs=3))
    return client, report


@pytest.fixture(scope="module")
def report(scenario):
    return scenario[1]


@pytest.fixture(scope="module")
def client(scenario):
    return scenario[0]


def _records(report):
    return {record["id"]: record for record in report["observed"]["artists"]}


def _pair(report, a, b):
    for pair in report["computed"]["pairs"]:
        ids = {pair["artist_a"]["id"], pair["artist_b"]["id"]}
        if ids == {a, b}:
            return pair
    raise AssertionError(f"pair {a}/{b} not present")


# --- dataset ---


def test_shipped_dataset_is_the_fixed_30_artist_set():
    dataset = load_dataset()
    artists = dataset["artists"]
    assert dataset["version"] == 2
    assert len(artists) == 30
    assert len({artist["id"] for artist in artists}) == 30
    assert len({artist["query"] for artist in artists}) == 30
    ids = {artist["id"] for artist in artists}
    assert "radiohead" in ids and "fela-kuti" in ids
    assert sum(1 for artist in artists if artist["id"] == "radiohead") == 1
    assert validate_dataset(dataset) == []

    checks = dataset["sanity_checks"]
    assert len(checks) == 5
    assert {check["expectation"] for check in checks} <= {"similar", "lower"}
    for check in checks:
        assert check["a"] in ids and check["b"] in ids
        assert check["a"] != check["b"]
        assert check["hypothesis"].strip()

    digest = dataset_digest()
    assert len(digest) == 64
    assert digest == dataset_digest()


def test_dataset_validation_rejects_duplicates_bad_references_and_repeat_checks():
    dataset = copy.deepcopy(load_dataset())
    dataset["artists"].append(dict(dataset["artists"][0]))
    dataset["sanity_checks"][0] = {
        "id": "bad",
        "a": "not-an-artist",
        "b": dataset["artists"][1]["id"],
        "expectation": "similar",
        "hypothesis": "test",
    }
    repeated = dict(dataset["sanity_checks"][1])
    dataset["sanity_checks"].append(repeated)
    dataset["sanity_checks"].append(
        {
            "id": "bad-expectation",
            "a": dataset["artists"][0]["id"],
            "b": dataset["artists"][2]["id"],
            "expectation": "maybe",
            "hypothesis": "test",
        }
    )
    errors = validate_dataset(dataset)
    assert any("duplicate artist id" in error for error in errors)
    assert any("unknown artist" in error for error in errors)
    assert any("repeats a pair" in error for error in errors)
    assert any("expectation must be" in error for error in errors)


def test_unreadable_dataset_raises_dataset_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProbeDatasetError):
        load_dataset(bad)


def test_run_input_guards_reject_unsupported_takes():
    with pytest.raises(ValueError):
        asyncio.run(run_probe_v2(client=FakeQlooClient(), take=51))
    with pytest.raises(ValueError):
        asyncio.run(run_probe_v2(client=FakeQlooClient(), take=0))
    with pytest.raises(ValueError):
        asyncio.run(run_probe_v2(client=FakeQlooClient(), take=50, depth_take=50))
    with pytest.raises(ValueError):
        asyncio.run(run_probe_v2(client=FakeQlooClient(), delay=-1))


# --- resolution and profiles ---


def test_test_double_run_is_not_evidence(client, report):
    meta = report["probe"]
    assert meta["mode"] == "test-double"
    assert meta["evidence"]["is_evidence"] is False
    assert "not evidence" in meta["evidence"]["note"].lower()
    assert meta["transport"]["kind"] == "test-double"
    assert meta["transport"]["cache"] == {"enabled": False}
    assert meta["aborted"] is None
    assert meta["partial"] is False


def test_resolution_statuses_are_recorded_separately(client, report):
    analysis = report["computed"]["analysis"]
    counts = analysis["resolution"]["counts"]
    assert counts == {"matched": 27, "ambiguous": 1, "not_found": 1, "api_error": 1}
    assert analysis["resolution"]["raw_status_counts"] == {
        "ambiguous": 1,
        "error": 1,
        "matched": 27,
        "no_match": 1,
    }
    assert analysis["resolution"]["artists"]["ambiguous"] == ["SZA"]
    assert analysis["resolution"]["artists"]["not_found"] == ["BLACKPINK"]
    assert analysis["resolution"]["artists"]["api_error"] == ["BTS"]

    records = _records(report)
    assert records["sza"]["resolution"]["selected_entity_id"] is None
    assert records["sza"]["resolution"]["top_candidate_entity_id"] == "fake:sza:1"
    assert len(records["sza"]["resolution"]["candidates"]) == 2
    assert records["blackpink"]["resolution"]["candidate_count"] == 0
    assert "HTTP 500" in records["bts"]["resolution"]["error"]
    # The search failure is recorded once and never retried at probe level.
    assert client.search_calls.count("BTS") == 1


def test_ambiguous_artist_is_never_profiled_or_scored(client, report):
    records = _records(report)
    sza = records["sza"]
    assert sza["profile"]["source"] == "unconfirmed"
    assert sza["profile"]["missing"] is True
    assert not any(sza["profile"]["tags"].values())
    profiled_entities = {entity for entity, _take in client.insights_calls}
    assert not profiled_entities & {"fake:sza:1", "fake:sza:2"}
    for pair in report["computed"]["pairs"]:
        if "sza" in (pair["artist_a"]["id"], pair["artist_b"]["id"]):
            assert pair["missing"] is True
            assert pair["taste_similarity"] is None


def test_search_fallback_profile_uses_canonical_genre_namespace(report):
    fela = _records(report)["fela-kuti"]
    profile = fela["profile"]
    assert fela["resolution"]["status"] == "matched"
    assert profile["source"] == "qloo-search"
    assert profile["missing"] is False
    assert "urn:tag:genre:afrobeat" in profile["tags"]["genre"]
    assert all(tag.startswith(GENRE) for tag in profile["canonical_tags"]["genre"])
    assert profile["raw_tag_counts"]["genre"] == 2
    assert profile["tag_counts"]["genre"] == 2
    assert profile["genre_namespace"]["raw_count"] == 2
    assert profile["genre_namespace"]["canonical_count"] == 2
    assert profile["genre_namespace"]["prefix_counts"] == {
        "urn:tag:genre:": 1,
        "urn:tag:genre:music:": 1,
    }


def test_provider_failures_are_recorded_without_stopping_the_run(client, report):
    records = _records(report)
    assert len(report["observed"]["artists"]) == 30
    metallica = records["metallica"]
    assert metallica["profile"]["provider_failed"] is True
    assert metallica["profile"]["missing"] is True
    assert "HTTP 500" in metallica["profile"]["note"]
    stages = {(error["artist_id"], error["stage"]) for error in
              report["observed"]["provider_errors"]}
    assert ("bts", "search") in stages
    assert ("metallica", "insights") in stages
    assert report["probe"]["provider_errors"] == 2
    # An empty, error-free insights response is missing data, not an outage.
    shreya = records["shreya-ghoshal"]
    assert shreya["profile"]["missing"] is True
    assert shreya["profile"]["provider_failed"] is False


def test_profile_coverage_and_coverage_classes(report):
    coverage = report["computed"]["analysis"]["profile_coverage"]
    assert coverage["profiles_total"] == 30
    assert coverage["usable"] == 25
    assert coverage["missing"] == 5
    assert coverage["genre_artists"] == 25
    assert coverage["genre_share_of_usable"] == 1.0
    assert coverage["source_counts"] == {
        "matched, no usable tags": 2,
        "qloo-insights": 24,
        "qloo-search": 1,
        "unconfirmed": 1,
        "unresolved": 2,
    }
    assert coverage["coverage_class_counts"] == {
        "missing": 5,
        "ok": 24,
        "sparse": 1,
    }
    sparse = _records(report)["ar-rahman"]["profile"]
    assert sparse["coverage_class"] == "sparse"
    assert sparse["tag_counts"]["genre"] == 1
    assert sparse["missing_categories"] == ["audience", "style", "music"]

    insufficient = {row["artist_id"] for row in
                    report["computed"]["analysis"]["insufficient_coverage"]}
    assert insufficient == MISSING_ARTISTS | {SPARSE_ARTIST}


def test_transport_counts_match_the_fake_client(client, report):
    transport = report["probe"]["transport"]
    assert transport["search_requests"] == 30
    assert transport["main_insights_requests"] == 27
    assert transport["depth_insights_requests"] == 6
    assert transport["logical_requests"] == 63
    assert transport["searches_succeeded"] == 29
    assert transport["insights_succeeded"] == 26
    assert transport["profiles_usable"] == 25
    assert transport["profile_cache_hits"] == 0
    assert len(client.search_calls) == 30
    takes = {}
    for _entity, take in client.insights_calls:
        takes[take] = takes.get(take, 0) + 1
    assert takes == {20: 6, 50: 27}


# --- matrix ---


def test_every_pair_is_present_and_missing_profiles_are_excluded(report):
    pairs = report["computed"]["pairs"]
    assert len(pairs) == 30 * 29 // 2
    keys = {frozenset((pair["artist_a"]["id"], pair["artist_b"]["id"])) for pair in pairs}
    assert len(keys) == 435
    missing = [pair for pair in pairs if pair["missing"]]
    assert len(missing) == 435 - 25 * 24 // 2
    assert all(pair["taste_similarity"] is None for pair in missing)
    assert all(pair["missing_reason"] for pair in missing)
    assert all(pair["missing_kind"] == "profile_data" for pair in missing)
    for pair in pairs:
        assert pair["artist_a"]["name"] and pair["artist_b"]["name"]
        assert pair["artist_a"]["profile_source"]
    scored = [pair for pair in pairs if not pair["missing"]]
    assert len(scored) == 300
    assert all(pair["genre_similarity"] is not None for pair in scored)


def test_ranked_scored_pairs_are_ordered_and_missing_pairs_are_last(report):
    pairs = report["computed"]["pairs"]
    scored = [pair for pair in pairs if not pair["missing"]]
    by_rank = sorted(scored, key=lambda pair: pair["rank"])
    assert [pair["rank"] for pair in by_rank] == list(range(1, 301))
    scores = [pair["taste_similarity"] for pair in by_rank]
    assert scores == sorted(scores, reverse=True)
    assert all(pair.get("rank") is None for pair in pairs if pair["missing"])


def test_distribution_and_confidence_are_consistent(report):
    analysis = report["computed"]["analysis"]
    matrix = analysis["matrix"]
    distribution = matrix["distribution"]
    assert distribution["n"] == 300
    assert distribution["min"] == 0.0
    assert distribution["max"] == 1.0
    assert distribution["zeros"] == 255
    assert matrix["zero_count"] == 255
    assert matrix["zero_share"] == pytest.approx(0.85, abs=1e-4)
    assert matrix["pairs_scored"] == 300
    assert matrix["pairs_missing"] == 135
    assert matrix["pairs_with_genre_both"] == 300
    assert matrix["pairs_sufficient_with_genre"] == 246
    assert matrix["distinct_scores"] == 4
    assert matrix["verdicts_informative"] is False
    assert "qualified" in matrix["verdict_note"].lower()
    assert set(matrix["score_thresholds"]) == {"p20", "p50", "p80"}
    assert matrix["nonzero_distribution"]["n"] == 45

    confidence = analysis["confidence"]
    assert confidence["sufficient_evidence"] == 246
    assert confidence["low_confidence"] == 54
    assert confidence["genre_backed"] == 300
    assert confidence["without_genre"] == 0
    assert confidence["categories_compared_distribution"] == {
        "1": 24,
        "2": 23,
        "4": 253,
    }
    assert confidence["low_confidence_trigger_counts"] == {
        "all_shared_tags_generic": 16,
        "fewer_than_2_categories": 24,
        "fewer_than_6_union_tags": 38,
        "single_shared_tag": 19,
    }


def test_shared_tag_frequency_and_generic_dominance(report):
    analysis = report["computed"]["analysis"]
    frequency = analysis["shared_tag_frequency"]
    assert frequency["pairs_with_shared_tags"] == 45
    assert frequency["pairs_without_shared_tags"] == 255
    rows = {row["tag"]: row for row in frequency["rows"]}
    alternative = rows[ALTERNATIVE]
    assert alternative["pairs"] == 28
    assert alternative["artists"] == 8
    assert alternative["of_artists"] == 25
    assert alternative["of_scored_pairs"] == 300
    assert alternative["generic_rule"] is True
    assert alternative["broad_rule"] is False
    assert "genre" in alternative["categories"]

    dominance = analysis["generic_dominance"]
    assert dominance["lineup_generic_tags"] == [ALTERNATIVE]
    assert dominance["top_pair_limit"] == 10
    assert len(dominance["top_pairs"]) == 10
    assert dominance["scored_pairs_all_generic"] == 16
    assert dominance["scored_pairs_majority_generic"] == 16
    assert dominance["mean_score_majority_generic"] == pytest.approx(0.11, abs=1e-4)
    assert dominance["mean_score_majority_specific"] == pytest.approx(0.9483, abs=1e-4)
    assert dominance["top_pairs_all_generic"] == 0


def test_highest_and_lowest_nonzero_pairs_carry_shared_evidence(report):
    analysis = report["computed"]["analysis"]
    highest = analysis["highest_nonzero_pairs"]
    lowest = analysis["lowest_nonzero_pairs"]
    assert len(highest) == 5 and len(lowest) == 5
    assert all(pair["taste_similarity"] == 1.0 for pair in highest)
    assert all(pair["shared_tag_count"] >= 5 for pair in highest)
    assert all(pair["taste_similarity"] == pytest.approx(0.11, abs=1e-4)
               for pair in lowest)
    assert all(pair["shared_tag_count"] == 1 for pair in lowest)
    assert all(pair["shared_tags"] == [ALTERNATIVE] for pair in lowest)
    assert all(pair["generic_share"] == 1.0 for pair in lowest)


def test_diagnosis_separates_sparse_vocabulary_from_pipeline_failure(report):
    diagnosis = report["computed"]["analysis"]["diagnosis"]
    assert diagnosis["zero_count"] == 255
    assert diagnosis["zero_share"] == pytest.approx(0.85, abs=1e-4)
    assert diagnosis["zero_pairs_with_genre_both"] == 255
    assert diagnosis["zero_pairs_without_genre_side"] == 0
    assert diagnosis["zero_pairs_no_shared_tags"] == 255
    assert "disjoint returned tag sets" in diagnosis["likely_cause"]
    assert "not a missing-data or namespace failure" in diagnosis["likely_cause"]


# --- sanity checks ---


def test_predeclared_sanity_checks_are_all_reported(report):
    rows = report["computed"]["analysis"]["sanity_checks"]
    dataset = load_dataset()
    assert [row["id"] for row in rows] == [
        check["id"] for check in dataset["sanity_checks"]
    ]
    assert [row["expectation"] for row in rows] == [
        check["expectation"] for check in dataset["sanity_checks"]
    ]
    allowed = {"supported", "mixed", "not_supported", "unscored"}
    for row in rows:
        assert row["verdict"] in allowed
        assert row["hypothesis"].strip()
        if row["taste_similarity"] is None:
            assert row["verdict"] == "unscored"
            assert "Not scored" in row["interpretation"]

    radiohead_aphex = _pair(report, "radiohead", "aphex-twin")
    assert radiohead_aphex["taste_similarity"] == 1.0
    assert radiohead_aphex["shared_tag_count"] == 6
    assert rows[0]["verdict"] == "supported"
    assert rows[0]["low_confidence"] is False

    daft_chemical = _pair(report, "daft-punk", "the-chemical-brothers")
    kendrick_drake = _pair(report, "kendrick-lamar", "drake")
    assert daft_chemical["taste_similarity"] == 1.0
    assert kendrick_drake["taste_similarity"] == 1.0
    assert rows[2]["verdict"] == "supported"
    assert rows[3]["verdict"] == "supported"

    radiohead_bad_bunny = _pair(report, "radiohead", "bad-bunny")
    assert radiohead_bad_bunny["taste_similarity"] == 0.0
    assert radiohead_bad_bunny["shared_tag_count"] == 0
    assert rows[1]["verdict"] == "supported"

    assert rows[4]["verdict"] == "unscored"
    # pair_similarity reports False (not None) for a missing pair; the renderer
    # must still show "unscored" rather than "passes".
    assert rows[4]["low_confidence"] is False


# --- depth sensitivity ---


def test_depth_sensitivity_reports_three_pairs_at_both_depths(client, report):
    depth = report["computed"]["analysis"]["depth_sensitivity"]
    assert depth["enabled"] is True
    assert depth["take_deep"] == 50
    assert depth["take_shallow"] == 20
    assert depth["pairs_requested"] == 3
    assert depth["pairs_checked"] == 3
    assert depth["pairs_with_comparable_scores"] == 3
    assert depth["material_pairs"] == 0
    assert depth["max_abs_taste_delta"] == 0.0
    assert depth["mean_abs_taste_delta"] == 0.0
    rows = depth["rows"]
    assert len(rows) == 3
    used = set()
    for row in rows:
        assert row["deep"]["take"] == 50
        assert row["shallow"]["take"] == 20
        assert row["delta_taste_deep_minus_shallow"] == 0.0
        assert row["material"] is False
        assert set(row["profile_sources_shallow"].values()) <= {
            "qloo-insights",
            "qloo-search",
        }
        assert row["insights_errors"] == []
        used.update(row["artist_ids"])
    assert len(used) == 6


# --- reporting ---


def test_markdown_and_json_artifacts_are_timestamped_and_complete(report, tmp_path):
    paths = write_v2_reports(report, tmp_path)
    json_path = Path(paths["json"])
    markdown_path = Path(paths["markdown"])
    assert json_path.name == f"{report['probe']['run_id']}-qloo-probe-v2.json"
    assert markdown_path.name == f"{report['probe']['run_id']}-qloo-probe-v2.md"
    assert json.loads(json_path.read_text(encoding="utf-8")) == report

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "TEST DOUBLE - NOT EVIDENCE" in markdown
    for section in range(1, 12):
        assert f"## {section}." in markdown
    # An unscored pair must not be labelled as passing the confidence rule.
    assert (
        "| Metallica / Nirvana | similar | - | - | - | unscored | unscored | - |"
        in markdown
    )
    assert "tag affinity" in markdown.lower()
    assert "audience overlap" in markdown.lower()


def test_run_timestamp_and_disabled_depth():
    report = asyncio.run(
        run_probe_v2(
            client=FakeQlooClient(),
            depth_pairs=0,
            now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
    )
    assert report["probe"]["run_id"] == "20260102T030405Z"
    assert report["probe"]["generated_at"] == "2026-01-02T03:04:05Z"
    assert report["probe"]["evidence"]["is_evidence"] is False
    markdown = render_markdown(report)
    assert "TEST DOUBLE - NOT EVIDENCE" in markdown
    assert "## 8. Depth sensitivity" in markdown
    assert "Depth sensitivity was disabled for this run." in markdown


def test_timestamp_is_normalized_to_utc():
    naive = datetime(2026, 5, 6, 7, 8, 9)
    result = asyncio.run(
        run_probe_v2(client=FakeQlooClient(), depth_pairs=0, now=naive)
    )
    assert result["probe"]["run_id"] == "20260506T070809Z"
    shifted = naive.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    result = asyncio.run(
        run_probe_v2(client=FakeQlooClient(), depth_pairs=0, now=shifted)
    )
    assert result["probe"]["run_id"] == "20260506T013809Z"


def test_auth_failure_aborts_and_redacts_the_secret(tmp_path):
    secret = "super-secret-key-value"
    attempts = []

    class AuthFailClient(FakeQlooClient):
        async def search_artists(self, query, record_cache=None):
            attempts.append(query)
            raise QlooUpstreamError(
                f"Qloo rejected the API key (HTTP 401). Key was {secret}"
            )

    report = asyncio.run(
        run_probe_v2(client=AuthFailClient(), secret=secret, depth_pairs=0)
    )
    meta = report["probe"]
    assert meta["aborted"] == {
        "stage": "search",
        "artist_id": "radiohead",
        "reason": "Qloo rejected the API key (HTTP 401). Key was [redacted]",
    }
    assert meta["partial"] is True
    assert meta["evidence"]["is_evidence"] is False
    assert len(report["observed"]["artists"]) == 1
    assert report["computed"]["pairs"] == []
    assert meta["transport"]["searches_succeeded"] == 0
    assert len(attempts) == 1

    dumped = json.dumps(report)
    assert secret not in dumped
    markdown = render_markdown(report)
    assert secret not in markdown
    assert "[redacted]" in markdown


def test_missing_key_raises_config_error_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "QLOO_API_KEY", "")
    with pytest.raises(ProbeConfigError):
        asyncio.run(run_probe_v2(cache_dir=tmp_path / "cache", depth_pairs=0))


def test_cli_requires_live_and_valid_takes():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        main(["--live", "--take", "51"])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        main(["--live", "--take", "50", "--depth-take", "50"])
    assert excinfo.value.code == 2


def test_cli_returns_dataset_error_and_missing_key_codes(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["--live", "--dataset", str(bad)]) == 1

    monkeypatch.setattr(config, "QLOO_API_KEY", "")
    assert (
        main(
            [
                "--live",
                "--out",
                str(tmp_path / "out"),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--depth-pairs",
                "0",
            ]
        )
        == 3
    )


# --- cached transport ---


def _install_fake_request(monkeypatch, responder):
    calls = []

    async def fake_request(self, method, path, params, retries_left=1):
        calls.append(
            {
                "method": method,
                "path": path,
                "params": dict(params),
                "retries_left": retries_left,
            }
        )
        return responder(len(calls), method, path, params)

    monkeypatch.setattr(QlooClient, "_request", fake_request)
    return calls


def _cached_client(tmp_path, **overrides):
    options = {
        "api_key": "test-key",
        "base_url": "https://synthetic.invalid",
        "delay": 0,
        "retry_backoff": 0,
    }
    options.update(overrides)
    return CachedQlooClient(tmp_path / "cache", **options)


def test_cache_key_depends_on_base_url_and_params():
    first = _cache_key("GET", "/search", {"query": "a"}, "https://one")
    assert first == _cache_key("GET", "/search", {"query": "a"}, "https://one")
    assert first != _cache_key("GET", "/search", {"query": "b"}, "https://one")
    assert first != _cache_key("GET", "/search", {"query": "a"}, "https://two")


def test_cached_client_reuses_disk_responses_without_repeating_network(tmp_path, monkeypatch):
    calls = _install_fake_request(
        monkeypatch, lambda n, *args: {"results": [], "n": n}
    )
    client = _cached_client(tmp_path)
    first = asyncio.run(client._request("GET", "/search", {"query": "Radiohead"}))
    second = asyncio.run(client._request("GET", "/search", {"query": "Radiohead"}))
    assert first == second == {"results": [], "n": 1}
    assert len(calls) == 1
    assert client.stats["logical_requests"] == 2
    assert client.stats["cache_hits"] == 1
    assert client.stats["cache_misses"] == 1
    assert client.stats["network_succeeded"] == 1

    cache_files = list((tmp_path / "cache").glob("*.json"))
    assert len(cache_files) == 1
    payload = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert payload["base_url"] == "https://synthetic.invalid"
    assert payload["params"] == {"query": "Radiohead"}
    text = cache_files[0].read_text(encoding="utf-8")
    assert "X-Api-Key" not in text and "test-key" not in text

    fresh = _cached_client(tmp_path)
    third = asyncio.run(fresh._request("GET", "/search", {"query": "Radiohead"}))
    assert third == first
    assert len(calls) == 1
    assert fresh.stats["cache_hits"] == 1


def test_refresh_bypasses_cache_and_corrupt_entries_are_refetched(tmp_path, monkeypatch):
    calls = _install_fake_request(monkeypatch, lambda n, *args: {"n": n})
    client = _cached_client(tmp_path)
    asyncio.run(client._request("GET", "/v2/insights", {"take": 50}))
    client.refresh = True
    asyncio.run(client._request("GET", "/v2/insights", {"take": 50}))
    assert len(calls) == 2

    cache_file = next((tmp_path / "cache").glob("*.json"))
    cache_file.write_text("{broken", encoding="utf-8")
    client.refresh = False
    response = asyncio.run(client._request("GET", "/v2/insights", {"take": 50}))
    assert response == {"n": 3}
    assert len(calls) == 3
    assert json.loads(cache_file.read_text(encoding="utf-8"))["response"] == {"n": 3}


def test_transient_failures_are_retried_once_then_succeed(tmp_path, monkeypatch):
    attempts = []

    async def fake_request(self, method, path, params, retries_left=1):
        attempts.append(path)
        if len(attempts) == 1:
            raise QlooUpstreamError("Qloo request timed out: /search")
        return {"results": []}

    monkeypatch.setattr(QlooClient, "_request", fake_request)
    client = _cached_client(tmp_path)
    assert asyncio.run(client._request("GET", "/search", {"query": "x"})) == {
        "results": []
    }
    assert len(attempts) == 2
    assert client.stats["transient_retries"] == 1
    assert client.stats["network_attempts"] == 2
    assert client.stats["network_succeeded"] == 1
    assert client.stats["network_failures"] == 0


def test_nontransient_failures_are_not_retried(tmp_path, monkeypatch):
    attempts = []

    async def fake_request(self, method, path, params, retries_left=1):
        attempts.append(path)
        raise QlooUpstreamError(
            "Qloo rejected the API key (HTTP 401). Check QLOO_API_KEY."
        )

    monkeypatch.setattr(QlooClient, "_request", fake_request)
    client = _cached_client(tmp_path)
    with pytest.raises(QlooUpstreamError):
        asyncio.run(client._request("GET", "/search", {"query": "x"}))
    assert len(attempts) == 1
    assert client.stats["transient_retries"] == 0
    assert client.stats["network_failures"] == 1
    assert not list((tmp_path / "cache").glob("*.json"))


def test_client_internal_retries_do_not_reenter_the_cache_layer(tmp_path, monkeypatch):
    calls = _install_fake_request(
        monkeypatch, lambda n, method, path, params: {"retries_left": 0}
    )
    client = _cached_client(tmp_path)
    result = asyncio.run(
        client._request("GET", "/search", {"query": "x"}, retries_left=0)
    )
    assert result == {"retries_left": 0}
    assert calls[0]["retries_left"] == 0
    assert client.stats["client_internal_retries"] == 1
    assert client.stats["logical_requests"] == 0
    assert not list((tmp_path / "cache").glob("*.json"))


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Qloo request timed out: /search", True),
        ("Qloo request failed: /search (connection reset)", True),
        ("Qloo returned HTTP 500 for /v2/insights.", True),
        ("Qloo rejected the API key (HTTP 401). Check QLOO_API_KEY.", False),
        ("Qloo rate limit reached (HTTP 429). The request was retried once.", False),
        ("Qloo returned a non-JSON payload for /search.", False),
        ("Qloo returned HTTP 400 for /v2/insights.", False),
    ],
)
def test_only_transport_timeout_and_5xx_messages_are_transient(message, expected):
    assert is_transient_message(message) is expected
