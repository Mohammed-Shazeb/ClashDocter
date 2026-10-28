"""Offline tests for the Qloo coverage probe. No network calls are made."""
import asyncio
import copy
import csv
import json
from pathlib import Path

import pytest

from app.qloo import QlooUpstreamError
from probe import run as probe_run
from probe.core import (
    DatasetError,
    ProbeConfigError,
    _generic_diagnostics,
    dataset_warnings,
    different_verdict,
    leave_one_out,
    load_dataset,
    percentile_value,
    percentile_values,
    run_probe,
    similar_verdict,
    validate_dataset,
)
from probe.mock import MockQloo, load_mock_cases
from probe.report import write_reports


@pytest.fixture(scope="module")
def mock_report():
    return asyncio.run(run_probe(mode="mock"))


@pytest.fixture(scope="module")
def by_id(mock_report):
    return {record["id"]: record for record in mock_report["observed"]["artists"]}


def _pair(record_ids, shared_tags):
    a, b = record_ids
    return {
        "missing": False,
        "taste_similarity": 0.5,
        "signals": [{"shared_tags": shared_tags}],
        "artist_a": {"name": a, "id": a, "label": "established"},
        "artist_b": {"name": b, "id": b, "label": "established"},
    }


def _fake_record(artist_id, genre_tags, label="established"):
    return {
        "id": artist_id,
        "name": artist_id,
        "label": label,
        "profile": {
            "missing": False,
            "tags": {
                "genre": genre_tags,
                "audience": [],
                "style": [],
                "music": [],
            },
        },
    }


class _UnconfiguredClient:
    configured = False


class _SearchAuthFailClient:
    configured = True
    base_url = "https://example.invalid"

    def __init__(self, secret):
        self.secret = secret
        self.searches = 0
        self.insights = 0

    async def search_artists(self, query, record_cache=None):
        self.searches += 1
        raise QlooUpstreamError(
            f"Qloo rejected the API key (HTTP 401). Key was {self.secret}"
        )

    async def insights_tags(self, entity_id, take=None):
        self.insights += 1
        raise AssertionError("insights must not be called after a search auth failure")


class _MalformedClient:
    configured = True
    base_url = "https://example.invalid"

    def __init__(self):
        self.searches = 0

    async def search_artists(self, query, record_cache=None):
        self.searches += 1
        raise QlooUpstreamError("Qloo returned a non-JSON payload for /search.")

    async def insights_tags(self, entity_id, take=None):
        raise AssertionError("insights must not be called when search fails")


class _InsightsAuthFailClient:
    configured = True
    base_url = "https://example.invalid"

    def __init__(self, secret):
        self.secret = secret
        self.searches = 0
        self.insights = 0

    async def search_artists(self, query, record_cache=None):
        self.searches += 1
        return [
            {
                "name": "Radiohead",
                "entity_id": "fake:radiohead",
                "types": ["urn:entity:artist"],
                "disambiguation": "English rock band",
            }
        ]

    async def insights_tags(self, entity_id, take=None):
        self.insights += 1
        raise QlooUpstreamError(
            f"Qloo rejected the API key (HTTP 401). Key was {self.secret}"
        )


# --- dataset ---


def test_shipped_dataset_is_complete_and_valid():
    dataset = load_dataset()
    assert len(dataset["artists"]) == 50
    labels = [artist["label"] for artist in dataset["artists"]]
    assert labels.count("established") == 30
    assert labels.count("emerging") == 20
    assert len({artist["id"] for artist in dataset["artists"]}) == 50
    assert validate_dataset(dataset) == []
    assert dataset_warnings(dataset) == []

    known = {artist["id"] for artist in dataset["artists"]}
    for kind in ("expected_similar_pairs", "expected_different_pairs"):
        for entry in dataset[kind]:
            assert entry["a"] in known and entry["b"] in known
            assert entry["a"] != entry["b"]
            assert entry["rationale"].strip()


def test_dataset_validation_rejects_duplicates_and_bad_references():
    dataset = copy.deepcopy(load_dataset())
    dataset["artists"].append(dict(dataset["artists"][0]))
    dataset["expected_similar_pairs"][0] = {
        "a": "not-an-artist",
        "b": dataset["artists"][1]["id"],
        "rationale": "test",
    }
    repeated = dict(dataset["expected_similar_pairs"][1])
    dataset["expected_different_pairs"].append(repeated)
    errors = validate_dataset(dataset)
    assert any("duplicate artist id" in error for error in errors)
    assert any("unknown artist" in error for error in errors)
    assert any("repeats pair" in error and "expected_similar_pairs" in error for error in errors)


def test_unreadable_dataset_raises_dataset_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetError):
        load_dataset(bad)


# --- mock adapter and run ---


def test_mock_mode_is_labelled_synthetic_and_makes_no_network_requests(mock_report):
    meta = mock_report["probe"]
    assert meta["mode"] == "mock"
    assert meta["evidence"]["is_evidence"] is False
    assert meta["transport"]["requests_attempted"] == 0
    assert meta["transport"]["live_requests_succeeded"] == 0
    assert meta["transport"]["profiles_with_usable_tags"] == 45
    assert meta["transport"]["names_unconfirmed"] == 1
    assert meta["transport"]["mock_calls"] > 0
    assert "Synthetic" in meta["evidence"]["note"]
    assert meta["partial"] is False
    assert meta["aborted"] is None


def test_mock_run_records_resolution_states_and_sources(by_id):
    assert by_id["mali"]["resolution"]["status"] == "ambiguous"
    assert by_id["mali"]["resolution"]["selected_entity_id"]
    # Ambiguity is data quality, not a confirmed match: never profile or score it.
    assert by_id["mali"]["profile"]["source"] == "unconfirmed"
    assert by_id["mali"]["profile"]["missing"] is True
    assert not any(by_id["mali"]["profile"]["tags"].values())
    assert by_id["sutej-singh"]["resolution"]["status"] == "no_match"
    assert by_id["taba-chake"]["resolution"]["status"] == "error"
    assert by_id["the-f16s"]["profile"]["source"] == "qloo-search"
    assert by_id["the-f16s"]["profile"]["missing"] is False
    # The fallback tags carry their provenance per category.
    for category, tags in by_id["the-f16s"]["profile"]["tags"].items():
        if tags:
            assert by_id["the-f16s"]["profile"]["provenance"][category] == "qloo-search"
    assert by_id["komorebi"]["profile"]["tag_counts"]["genre"] == 1


def test_search_fallback_profile_is_canonicalized_for_scoring(mock_report, by_id):
    section = by_id["the-f16s"]["profile"]
    assert section["source"] == "qloo-search"
    # Raw search vocabulary stays on record for provenance.
    assert all(
        tag.startswith("urn:tag:genre:") and not tag.startswith("urn:tag:genre:music:")
        for tag in section["tags"]["genre"]
    )
    # Scoring/diagnostics see the canonical insights namespace.
    assert all(
        tag.startswith("urn:tag:genre:music:")
        for tag in section["canonical_tags"]["genre"]
    )
    assert section["raw_tag_counts"]["genre"] == section["tag_counts"]["genre"]

    pair = next(
        pair
        for pair in mock_report["computed"]["ranked_pairs"]
        if {pair["artist_a"]["id"], pair["artist_b"]["id"]}
        == {"the-f16s", "the-national"}
    )
    assert pair["shared_genre_tags"] == [
        "urn:tag:genre:music:alternative_rock",
        "urn:tag:genre:music:indie_rock",
    ]
    assert pair["genre_similarity"] > 0


def test_scored_pairs_use_only_canonical_genre_ids(mock_report):
    checked = 0
    for pair in mock_report["computed"]["ranked_pairs"]:
        if pair["missing"]:
            continue
        for tag in pair["shared_genre_tags"]:
            assert tag.startswith("urn:tag:genre:music:")
            checked += 1
    assert checked > 0


def test_scored_pairs_expose_evidence_and_limitations(mock_report):
    for pair in mock_report["computed"]["ranked_pairs"]:
        if pair["missing"]:
            continue
        assert pair["genre_backed"] == (pair["genre_similarity"] is not None)
        assert pair["shared_specific_tag_count"] <= pair["shared_tag_count"]
        assert pair["shared_generic_tag_count"] <= pair["shared_tag_count"]
        assert 0.0 <= pair["generic_share"] <= 1.0
        assert 0.0 <= pair["broad_share"] <= 1.0
        if pair["shared_tag_count"]:
            assert pair["shared_generic_tag_count"] + pair[
                "shared_specific_tag_count"
            ] == pair["shared_tag_count"]
            assert pair["generic_share"] == pytest.approx(
                pair["shared_generic_tag_count"] / pair["shared_tag_count"], abs=1e-4
            )
            assert pair["broad_share"] == pytest.approx(
                len(pair["shared_broad_tags"]) / pair["shared_tag_count"], abs=1e-4
            )
        else:
            assert pair["generic_share"] == 0.0
            assert pair["broad_share"] == 0.0
        assert set(pair["profile_sources"]) == {"a", "b"}
        assert pair["profile_sources"]["a"] in {"qloo-insights", "qloo-search"}
        assert isinstance(pair["evidence_limitations"], list)
        if pair["low_confidence"]:
            assert pair["confidence_note"]


def test_provider_failures_are_recorded_without_stopping_the_run(mock_report, by_id):
    failed = by_id["dhruv-visvanath"]
    assert failed["profile"]["provider_failed"] is True
    assert failed["profile"]["missing"] is True
    assert "HTTP 500" in failed["profile"]["note"]
    errors = mock_report["observed"]["provider_errors"]
    assert any(
        error["artist_id"] == "dhruv-visvanath" and error["stage"] == "insights"
        for error in errors
    )
    assert any(
        error["artist_id"] == "taba-chake" and error["stage"] == "search"
        for error in errors
    )
    assert len(mock_report["observed"]["artists"]) == 50


def test_missing_profiles_exclude_pairs_instead_of_scoring_zero(mock_report):
    pairs = mock_report["computed"]["ranked_pairs"]
    affected = [
        pair
        for pair in pairs
        if "sutej-singh" in (pair["artist_a"]["id"], pair["artist_b"]["id"])
    ]
    assert len(affected) == 49
    assert all(pair["missing"] for pair in affected)
    assert all(pair["taste_similarity"] is None for pair in affected)
    assert all(pair["missing_reason"] for pair in affected)
    assert sum(1 for pair in pairs if pair["missing"]) == 235
    mali_pairs = [
        pair
        for pair in pairs
        if "mali" in (pair["artist_a"]["id"], pair["artist_b"]["id"])
    ]
    assert len(mali_pairs) == 49
    assert all(pair["missing"] for pair in mali_pairs)


def test_missing_categories_are_skipped_not_scored_as_disagreement(mock_report):
    pair = next(
        pair
        for pair in mock_report["computed"]["ranked_pairs"]
        if not pair["missing"]
        and "komorebi" in (pair["artist_a"]["id"], pair["artist_b"]["id"])
    )
    assert [signal["category"] for signal in pair["signals"]] == ["genre"]
    skipped = {item["category"]: item for item in pair["skipped_categories"]}
    assert "style" in skipped
    assert skipped["style"]["reason"].startswith("only ")
    assert pair["low_confidence"] is True
    # Genre is the only comparable category, so the blend equals its Jaccard.
    assert pair["taste_similarity"] == pair["genre_similarity"]


def test_coverage_counts_are_consistent_and_split_by_label(mock_report):
    coverage = mock_report["computed"]["coverage"]
    assert coverage["profiles_total"] == 50
    assert coverage["profiles_with_data"] == 45
    assert coverage["profiles_missing"] == 5
    assert coverage["pairs_total"] == 50 * 49 // 2
    assert coverage["pairs_scored"] + coverage["pairs_missing"] == coverage["pairs_total"]
    assert (
        coverage["pairs_with_sufficient_evidence"]
        == coverage["pairs_scored"] - coverage["pairs_low_confidence"]
    )

    labels = mock_report["computed"]["coverage_by_label"]
    assert labels["established"]["pairs_total"] == 30 * 29 // 2
    assert labels["emerging"]["pairs_total"] == 20 * 19 // 2
    assert mock_report["computed"]["coverage_cross_label"]["pairs_total"] == 30 * 20
    for label in ("established", "emerging"):
        row = labels[label]
        assert row["pairs_scored"] + row["pairs_missing"] == row["pairs_total"]
        assert (
            row["pairs_with_sufficient_evidence"]
            == row["pairs_scored"] - row["pairs_low_confidence"]
        )
    cross = mock_report["computed"]["coverage_cross_label"]
    assert (
        cross["pairs_with_sufficient_evidence"]
        == cross["pairs_scored"] - cross["pairs_low_confidence"]
    )
    assert labels["established"]["pairs_scored"] == labels["established"]["pairs_total"]
    assert labels["emerging"]["pairs_missing"] > 0
    summary = mock_report["computed"]["matrix_summary"]
    assert summary["pairs_with_genre_both"] <= summary["pairs_scored"]
    assert (
        summary["pairs_sufficient_with_genre"]
        <= summary["pairs_with_sufficient_evidence"]
    )
    for row in (*labels.values(), cross):
        assert 0 <= row["pairs_sufficient_with_genre"] <= row["pairs_with_sufficient_evidence"]


def test_coverage_counts_genre_backing_and_single_tag_pairs(mock_report):
    coverage = mock_report["computed"]["coverage"]
    scored = [
        pair for pair in mock_report["computed"]["ranked_pairs"] if not pair["missing"]
    ]
    assert coverage["pairs_genre_backed"] == sum(1 for pair in scored if pair["genre_backed"])
    assert (
        coverage["pairs_genre_backed"] + coverage["pairs_without_genre"]
        == coverage["pairs_scored"]
    )
    assert coverage["pairs_single_shared_tag"] == sum(
        1 for pair in scored if pair["shared_tag_count"] == 1
    )
    assert coverage["pairs_generic_only"] == sum(
        1
        for pair in scored
        if pair["shared_tag_count"]
        and pair["shared_generic_tag_count"] == pair["shared_tag_count"]
    )
    summary = mock_report["computed"]["matrix_summary"]
    assert summary["pairs_with_genre_both"] == coverage["pairs_genre_backed"]


def test_zero_inflated_verdicts_are_qualified(mock_report):
    summary = mock_report["computed"]["matrix_summary"]
    assert summary["zero_low_share"] >= 0.5
    assert summary["distinct_scores"] >= 3
    assert summary["verdicts_informative"] is False
    assert "qualified" in summary["verdict_note"].lower()
    for row in (
        mock_report["computed"]["expected_similar_checks"]
        + mock_report["computed"]["expected_different_checks"]
    ):
        assert row["percentile_informative"] is False
        if row["taste_similarity"] is None:
            assert row["verdict_basis"] == "unscored"
        else:
            assert row["verdict_basis"] == "zero-vs-nonzero"
            assert row["genre_backed"] is not None
            assert row["shared_tag_count"] is not None


def test_ranked_pairs_are_ordered_and_missing_pairs_come_last(mock_report):
    ranked = mock_report["computed"]["ranked_pairs"]
    scored = [pair for pair in ranked if not pair["missing"]]
    assert [pair["rank"] for pair in scored] == list(range(1, len(scored) + 1))
    scores = [pair["taste_similarity"] for pair in scored]
    assert scores == sorted(scores, reverse=True)
    assert all(pair.get("rank") is None for pair in ranked if pair["missing"])
    assert ranked[: len(scored)] == scored


# --- calculations ---


def test_leave_one_out_renormalizes_remaining_weights():
    pair = {
        "taste_similarity": round((0.55 * 1.0 + 0.20 * 0.0) / 0.75, 4),
        "signals": [
            {"category": "genre", "weight": 0.55, "jaccard": 1.0},
            {"category": "audience", "weight": 0.20, "jaccard": 0.0},
        ],
    }
    assert leave_one_out(pair) == {"genre": 0.0, "audience": 1.0}
    assert leave_one_out({"taste_similarity": 1.0, "signals": [pair["signals"][0]]}) == {}


def test_percentiles_are_midrank_and_thresholds_are_nearest_rank():
    scores = [0.0, 0.0, 0.5, 1.0]
    assert percentile_values(scores, 0.0) == 25
    assert percentile_values(scores, 0.5) == 62
    assert percentile_values(scores, 1.0) == 88
    assert percentile_values([], 0.5) == 0
    assert percentile_value(scores, 0.80) == 1.0
    assert percentile_value(scores, 0.20) == 0.0
    assert percentile_value([], 0.80) is None


def test_verdicts_compare_scores_with_percentile_values_and_survive_ties():
    assert similar_verdict(None, 0.8, 0.5) == "unscored"
    assert similar_verdict(0.8, 0.8, 0.5) == "supported"
    assert similar_verdict(0.6, 0.8, 0.5) == "mixed"
    assert similar_verdict(0.5, 0.8, 0.5) == "not_supported"
    assert similar_verdict(0.0, 0.0, 0.0) == "not_supported"

    assert different_verdict(None, 0.1, 0.3) == "unscored"
    assert different_verdict(0.1, 0.1, 0.3) == "supported"
    assert different_verdict(0.2, 0.1, 0.3) == "mixed"
    assert different_verdict(0.3, 0.1, 0.3) == "not_supported"
    assert different_verdict(0.0, 0.0, 0.0) == "supported"
    assert different_verdict(1.0, 1.0, 1.0) == "not_supported"


def test_expected_pairs_are_all_reported_with_verdicts(mock_report):
    computed = mock_report["computed"]
    assert len(computed["expected_similar_checks"]) == 10
    assert len(computed["expected_different_checks"]) == 6
    allowed = {"supported", "mixed", "not_supported", "unscored"}
    for row in (
        computed["expected_similar_checks"] + computed["expected_different_checks"]
    ):
        assert row["verdict"] in allowed
        assert row["rationale"].strip()
        if row["taste_similarity"] is None:
            assert row["verdict"] == "unscored"
            assert row["missing_reason"]
    thresholds = computed["matrix_summary"]["score_thresholds"]
    assert set(thresholds) == {"p20", "p50", "p80"}
    assert all(value is not None for value in thresholds.values())


def test_generic_tag_diagnostics_flag_broad_shared_tags(mock_report):
    generic = mock_report["computed"]["generic_tags"]
    top = {row["tag"] for row in generic["top_tags"]}
    assert "urn:tag:genre:music:popular_music" in top
    assert generic["profiles_with_data"] == 45
    assert all(0 <= row["document_frequency"] <= 1 for row in generic["top_tags"])


def test_generic_tag_pair_and_artist_flags_use_document_frequency():
    generic = "urn:tag:genre:music:x"
    records = [
        _fake_record("a", [generic]),
        _fake_record("b", [generic]),
        _fake_record("c", [generic, "urn:tag:genre:music:y"]),
        _fake_record("d", ["urn:tag:genre:music:z"]),
        _fake_record("e", ["urn:tag:genre:music:w"]),
        _fake_record("f", ["urn:tag:genre:music:v"]),
    ]
    pairs = [
        _pair(("a", "b"), [generic]),
        _pair(("a", "c"), [generic]),
        _pair(("a", "d"), []),
    ]
    result = _generic_diagnostics(records, pairs)
    assert result["profiles_with_data"] == 6
    assert result["pairs_flagged_total"] == 2
    for pair in pairs:
        # Every scored pair is annotated, not only the flagged ones.
        assert 0.0 <= pair["probe_generic_share"] <= 1.0
        shared = {tag for signal in pair["signals"] for tag in signal["shared_tags"]}
        specific = set(pair["probe_specific_shared_tags"])
        pair_generic = set(pair["probe_generic_shared_tags"])
        assert specific | pair_generic == shared
        assert not (specific & pair_generic)
    for flag in result["pairs_flagged"]:
        assert flag["generic_share"] == 1.0
        assert flag["labels"] == ["established", "established"]
    dominated = {row["artist_id"] for row in result["artists_dominated_by_generic_tags"]}
    assert {"a", "b"}.issubset(dominated)
    assert "c" not in dominated
    assert result["top_tags"][0]["tag"] == generic
    assert result["top_tags"][0]["artists"] == 3


def test_generic_diagnostics_detects_label_specific_catch_all_tag():
    catch_all = "urn:tag:genre:music:catch_all"
    records = [
        _fake_record(f"e{i}", [f"urn:tag:genre:music:e{i}"]) for i in range(20)
    ]
    records += [
        _fake_record(
            f"m{i}",
            [catch_all] if i < 5 else [f"urn:tag:genre:music:m{i}"],
            label="emerging",
        )
        for i in range(10)
    ]
    pair = {
        "missing": False,
        "taste_similarity": 0.5,
        "signals": [{"shared_tags": [catch_all]}],
        "artist_a": {"name": "m0", "id": "m0", "label": "emerging"},
        "artist_b": {"name": "m1", "id": "m1", "label": "emerging"},
    }
    result = _generic_diagnostics(records, [pair])

    # 5/30 overall is below the threshold, so only the within-set check sees it.
    catch_all_row = next(
        row for row in result["top_tags"] if row["tag"] == catch_all
    )
    assert catch_all_row["document_frequency"] < result["threshold"]
    emerging = next(
        section for section in result["by_label"] if section["label"] == "emerging"
    )
    assert any(row["tag"] == catch_all for row in emerging["generic_tags"])
    assert result["pairs_flagged_total"] == 1
    scopes = {
        scope
        for tag in result["pairs_flagged"][0]["shared_tag_detail"]
        for scope in tag.get("scopes", [])
    }
    assert "emerging" in scopes


def test_generic_diagnostics_uses_canonical_tags_when_present():
    canonical = "urn:tag:genre:music:bollywood"
    records = [_fake_record(f"a{i}", ["urn:tag:genre:bollywood"]) for i in range(6)]
    for record in records:
        record["profile"]["canonical_tags"] = {
            "genre": [canonical],
            "audience": [],
            "style": [],
            "music": [],
        }
    result = _generic_diagnostics(records, [])
    assert result["profiles_with_data"] == 6
    assert result["top_tags"][0]["tag"] == canonical
    assert result["top_tags"][0]["artists"] == 6


# --- failures ---


def test_live_mode_without_configuration_raises_before_any_request():
    with pytest.raises(ProbeConfigError):
        asyncio.run(run_probe(mode="live", client=_UnconfiguredClient()))


def test_search_auth_failure_aborts_once_and_never_calls_insights():
    secret = "sk-live-SECRET-123"
    client = _SearchAuthFailClient(secret)
    report = asyncio.run(run_probe(mode="live", client=client, secret=secret))

    assert report["probe"]["aborted"]["stage"] == "search"
    assert report["probe"]["partial"] is True
    assert report["probe"]["evidence"]["is_evidence"] is False
    assert report["probe"]["transport"]["live_requests_succeeded"] == 0
    assert report["probe"]["transport"]["requests_attempted"] == 1
    assert client.searches == 1
    assert client.insights == 0
    assert len(report["observed"]["artists"]) == 1
    reason = report["probe"]["aborted"]["reason"]
    assert "[redacted]" in reason
    assert secret not in reason


def test_insights_auth_failure_aborts_with_a_redacted_reason():
    secret = "sk-live-SECRET-456"
    client = _InsightsAuthFailClient(secret)
    report = asyncio.run(run_probe(mode="live", client=client, secret=secret))

    assert report["probe"]["aborted"]["stage"] == "insights"
    assert report["probe"]["aborted"]["artist_id"] == "radiohead"
    assert report["probe"]["transport"]["requests_attempted"] == 2
    assert client.searches == 1
    assert client.insights == 1
    assert secret not in json.dumps(report)
    assert "[redacted]" in report["probe"]["aborted"]["reason"]


def test_malformed_provider_payloads_are_recorded_and_do_not_crash(tmp_path):
    client = _MalformedClient()
    report = asyncio.run(run_probe(mode="live", client=client))

    assert client.searches == 50
    assert len(report["observed"]["provider_errors"]) == 50
    assert report["probe"]["partial"] is False
    assert report["probe"]["evidence"]["is_evidence"] is False
    assert report["probe"]["transport"]["searches_succeeded"] == 0
    assert report["probe"]["transport"]["profiles_with_usable_tags"] == 0
    coverage = report["computed"]["coverage"]
    assert coverage["profiles_with_data"] == 0
    assert coverage["pairs_scored"] == 0
    assert coverage["pairs_missing"] == coverage["pairs_total"]

    paths = write_reports(report, tmp_path)
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "LIVE RUN - NO USABLE EVIDENCE" in markdown
    assert "LIVE MODE." not in markdown


def test_mock_insights_honors_take():
    client = MockQloo(load_dataset(), load_mock_cases())
    raw = asyncio.run(client.insights_tags("mock:radiohead", take=2))
    assert len(raw) == 2


# --- artifacts ---


def test_write_reports_produces_valid_json_markdown_and_csv(mock_report, tmp_path):
    paths = write_reports(mock_report, tmp_path)
    assert set(paths) == {"json", "markdown", "matrix_csv"}
    for path in paths.values():
        assert Path(path).is_file()

    data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert data["probe"]["mode"] == "mock"
    assert data["probe"]["evidence"]["is_evidence"] is False
    assert len(data["computed"]["ranked_pairs"]) == 1225

    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "MOCK MODE - synthetic fixture, not evidence" in markdown
    assert "LIVE MODE" not in markdown
    assert "## 6. Human judgments" in markdown
    assert "Genre ids are normalized across Qloo namespaces" in markdown
    assert "Qualified verdicts" in markdown
    assert "Generic share" in markdown
    assert "evidence: genre-backed" in markdown

    with Path(paths["matrix_csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1225
    for column in (
        "shared_tags",
        "shared_tag_count",
        "shared_specific_tags",
        "shared_specific_tag_count",
        "shared_generic_tags",
        "shared_generic_tag_count",
        "generic_share",
        "probe_generic_share",
        "probe_generic_shared_tags",
        "probe_specific_shared_tags",
        "genre_backed",
        "profile_source_a",
        "profile_source_b",
        "evidence_limitations",
    ):
        assert column in rows[0]
    assert rows[0]["genre_backed"] in {"yes", "no"}
    assert rows[0]["profile_source_a"] in {"qloo-insights", "qloo-search"}
    assert rows[0]["profile_source_b"] in {"qloo-insights", "qloo-search"}
    assert rows[0]["rank"] == "1"
    assert rows[0]["missing"] == "no"
    assert rows[-1]["missing"] == "yes"
    assert sum(1 for row in rows if row["missing"] == "yes") == 235
    assert all(
        row["taste_similarity"] == ""
        for row in rows
        if row["missing"] == "yes"
    )
    assert all(row["missing_reason"] for row in rows if row["missing"] == "yes")


def test_cli_mock_run_writes_reports_and_exits_zero(tmp_path, capsys):
    code = probe_run.main(["--out", str(tmp_path)])
    assert code == probe_run.EXIT_OK
    output = capsys.readouterr().out
    assert "mode: mock" in output
    assert "evidence: no" in output
    for name in ("report.json", "report.md", "similarity_matrix.csv"):
        assert (tmp_path / name).is_file()


def test_cli_invalid_dataset_exits_one(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    code = probe_run.main(["--dataset", str(bad), "--out", str(tmp_path / "out")])
    assert code == probe_run.EXIT_DATASET_ERROR
    assert "dataset invalid" in capsys.readouterr().err


def test_cli_live_without_key_exits_three(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.config.QLOO_API_KEY", "")
    code = probe_run.main(["--live", "--out", str(tmp_path)])
    assert code == probe_run.EXIT_MISSING_KEY
    assert "QLOO_API_KEY is not set" in capsys.readouterr().err
    assert not (tmp_path / "report.json").exists()
