"""Unit tests for the Qloo client: parsing, filtering, fallback, errors.
All network access is mocked via httpx.MockTransport."""
import asyncio

import httpx
import pytest

from app.qloo import (
    QlooClient,
    QlooNotConfigured,
    QlooUpstreamError,
    canonical_genre_tag,
    fetch_profile,
    score_candidate,
    select_best_match,
    tags_from_insights,
    tags_from_search_entity,
)
from app.cache import TTLCache


SEARCH_OK = {
    "results": [
        {
            "name": "Radiohead",
            "entity_id": "ID-RADIOHEAD",
            "types": ["urn:entity:artist"],
            "popularity": 0.999,
            "disambiguation": "Radiohead",
            "properties": {"short_description": "English rock band"},
            "tags": [
                {"name": "Rock", "tag_id": "urn:tag:genre:rock"},
                {"name": "Alternative Rock", "tag_id": "urn:tag:genre:alternative_rock"},
                {"name": "Cultivated", "tag_id": "urn:tag:audience:qloo:cultivated"},
                {"name": "Cerebral", "tag_id": "urn:tag:style:qloo:cerebral"},
                {"name": "VISA", "tag_id": "urn:tag:credit_card:place:visa"},
                {"name": "Bar", "tag_id": "urn:tag:genre:place:restaurant:bar"},
            ],
        },
        {
            "name": "Radiohead Tribute Band",
            "entity_id": "ID-TRIBUTE",
            "types": ["urn:entity:artist"],
            "popularity": 0.3,
            "properties": {"short_description": "A tribute act"},
        },
    ]
}

INSIGHTS_OK = {
    "success": True,
    "results": {
        "tags": [
            {"tag_id": "urn:tag:genre:music:rock", "name": " rock", "subtype": "urn:tag:genre:music"},
            {"tag_id": "urn:tag:genre:music:alternative_rock", "name": "Alternative Rock", "subtype": "urn:tag:genre:music"},
            {"tag_id": "urn:tag:audience:qloo:cultivated", "name": "Cultivated", "subtype": "urn:tag:audience:qloo"},
            {"tag_id": "urn:tag:style:qloo:cerebral", "name": "Cerebral", "subtype": "urn:tag:style:qloo"},
            {"tag_id": "urn:tag:genre:place:restaurant:bar", "name": "Bar", "subtype": "urn:tag:genre:place"},
            {"tag_id": "urn:tag:credit_card:place:visa", "name": "VISA", "subtype": "urn:tag:credit_card:place"},
        ]
    },
}

INSIGHTS_EMPTY = {"success": True, "results": {"tags": []}}


def make_client(handler, api_key="test-key"):
    client = QlooClient(api_key=api_key, base_url="https://hackathon.api.qloo.com")
    client._client = httpx.AsyncClient(
        base_url="https://hackathon.api.qloo.com",
        transport=httpx.MockTransport(handler),
    )
    return client


def run(coro):
    return asyncio.run(coro)


# --- tag filtering ---

def test_insights_filtering_keeps_music_tags_only():
    tags = tags_from_insights(INSIGHTS_OK["results"]["tags"])
    assert tags.genre == {"urn:tag:genre:music:rock", "urn:tag:genre:music:alternative_rock"}
    assert tags.audience == {"urn:tag:audience:qloo:cultivated"}
    assert tags.style == {"urn:tag:style:qloo:cerebral"}
    assert tags.music == set()


def test_search_tag_filtering_excludes_non_music_genres():
    tags = tags_from_search_entity(SEARCH_OK["results"][0]["tags"])
    assert tags.genre == {"urn:tag:genre:rock", "urn:tag:genre:alternative_rock"}
    assert tags.audience == {"urn:tag:audience:qloo:cultivated"}
    assert tags.style == {"urn:tag:style:qloo:cerebral"}
    # place/brand tags dropped
    assert not any("place" in t or "credit_card" in t for t in tags.all_tags())


# --- genre namespace normalization ---

def test_canonical_genre_tag_normalizes_namespaces_but_never_merges_labels():
    # The same label under each observed namespace becomes the same identifier.
    assert (
        canonical_genre_tag("urn:tag:genre:music:folk")
        == canonical_genre_tag("urn:tag:genre:folk")
        == canonical_genre_tag("urn:tag:genre:qloo:folk")
        == "urn:tag:genre:music:folk"
    )
    assert (
        canonical_genre_tag("urn:tag:genre:qloo:indie_folk")
        == "urn:tag:genre:music:indie_folk"
    )
    assert canonical_genre_tag("urn:tag:genre:music:free_jazz") == (
        "urn:tag:genre:music:free_jazz"
    )
    assert canonical_genre_tag("urn:tag:genre:qloo:jazz") == "urn:tag:genre:music:jazz"
    assert canonical_genre_tag("urn:tag:genre:electronic") == (
        "urn:tag:genre:music:electronic"
    )
    # Distinct labels stay distinct.
    assert canonical_genre_tag("urn:tag:genre:folk") != canonical_genre_tag(
        "urn:tag:genre:indie_folk"
    )
    # Non-music and malformed namespaces are never folded into music genres.
    for unchanged in (
        "urn:tag:genre:person:folk",
        "urn:tag:genre:place:jazz_club",
        "urn:tag:genre:qloo:folk:extra",
        "urn:tag:genre:",
        "not-a-tag",
    ):
        assert canonical_genre_tag(unchanged) == unchanged


# --- candidate validation ---

def test_best_match_prefers_exact_artist_over_tribute():
    results = SEARCH_OK["results"]
    best, ambiguous = select_best_match(results, "Radiohead")
    assert best["entity_id"] == "ID-RADIOHEAD"
    assert ambiguous is False
    assert score_candidate(results[0], "Radiohead") > score_candidate(results[1], "Radiohead")


def test_no_results():
    best, ambiguous = select_best_match([], "Nobody")
    assert best is None
    assert ambiguous is False


def test_ambiguous_when_names_do_not_match():
    results = [
        {"name": "Something Else", "entity_id": "X", "types": ["urn:entity:artist"], "popularity": 0.9},
        {"name": "Something Else Two", "entity_id": "Y", "types": ["urn:entity:artist"], "popularity": 0.8},
    ]
    _, ambiguous = select_best_match(results, "Radiohead")
    assert ambiguous is True


# --- client request handling ---

def test_search_parses_results_and_caches_tags():
    def handler(request: httpx.Request):
        assert request.url.path == "/search"
        assert request.url.params["query"] == "Radiohead"
        assert request.url.params["types"] == "urn:entity:artist"
        assert request.headers["X-Api-Key"] == "test-key"
        return httpx.Response(200, json=SEARCH_OK)

    cache = TTLCache()
    client = make_client(handler)
    results = run(client.search_artists("Radiohead", record_cache=cache))
    assert results[0]["entity_id"] == "ID-RADIOHEAD"
    record = cache.get("ID-RADIOHEAD")
    assert record is not None
    assert "urn:tag:genre:rock" in record.tags.genre


def test_search_empty_results():
    def handler(request):
        return httpx.Response(200, json={"results": []})

    client = make_client(handler)
    assert run(client.search_artists("zzz", record_cache=TTLCache())) == []


def test_not_configured_raises():
    client = QlooClient(api_key="")
    with pytest.raises(QlooNotConfigured):
        run(client.search_artists("Radiohead"))


def test_unauthorized_raises_upstream_error():
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    client = make_client(handler)
    with pytest.raises(QlooUpstreamError, match="401"):
        run(client.search_artists("Radiohead"))


def test_timeout_raises_upstream_error():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    client = make_client(handler)
    with pytest.raises(QlooUpstreamError, match="timed out|failed"):
        run(client.search_artists("Radiohead"))


def test_non_json_raises_upstream_error():
    def handler(request):
        return httpx.Response(200, content=b"not json")

    client = make_client(handler)
    with pytest.raises(QlooUpstreamError, match="non-JSON"):
        run(client.search_artists("Radiohead"))


def test_rate_limit_retries_once_then_succeeds():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})
        return httpx.Response(200, json=SEARCH_OK)

    client = make_client(handler)
    results = run(client.search_artists("Radiohead", record_cache=TTLCache()))
    assert calls["count"] == 2
    assert results[0]["entity_id"] == "ID-RADIOHEAD"


def test_rate_limit_exhausted_raises():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})

    client = make_client(handler)
    with pytest.raises(QlooUpstreamError, match="429"):
        run(client.search_artists("Radiohead"))
    assert calls["count"] == 2


def test_insights_request_shape():
    def handler(request: httpx.Request):
        assert request.url.path == "/v2/insights"
        assert request.url.params["filter.type"] == "urn:tag"
        assert request.url.params["signal.interests.entities"] == "ID-RADIOHEAD"
        return httpx.Response(200, json=INSIGHTS_OK)

    client = make_client(handler)
    tags = run(client.insights_tags("ID-RADIOHEAD"))
    assert len(tags) == 6


# --- profile fetching ---

def test_fetch_profile_prefers_insights():
    def handler(request):
        if request.url.path == "/v2/insights":
            return httpx.Response(200, json=INSIGHTS_OK)
        return httpx.Response(200, json=SEARCH_OK)

    client = make_client(handler)
    profile = run(fetch_profile(client, TTLCache(), "ID-RADIOHEAD"))
    assert profile["source"] == "qloo-insights"
    assert profile["missing"] is False
    assert "urn:tag:genre:music:rock" in profile["genre_tags"]


def test_fetch_profile_falls_back_to_search_tags():
    # Beethoven case: insights returns zero tags, search result carries tags
    def handler(request):
        if request.url.path == "/v2/insights":
            return httpx.Response(200, json=INSIGHTS_EMPTY)
        return httpx.Response(200, json=SEARCH_OK)

    client = make_client(handler)
    cache = TTLCache()
    run(client.search_artists("Beethoven", record_cache=cache))
    profile = run(fetch_profile(client, cache, "ID-RADIOHEAD"))
    assert profile["source"] == "qloo-search"
    assert profile["missing"] is False
    assert "urn:tag:genre:rock" in profile["genre_tags"]
    assert profile["note"] and "fallback" in profile["note"]


def test_search_fallback_keeps_raw_ids_and_exposes_canonical_genres():
    def handler(request):
        if request.url.path == "/v2/insights":
            return httpx.Response(200, json=INSIGHTS_EMPTY)
        return httpx.Response(200, json=SEARCH_OK)

    client = make_client(handler)
    cache = TTLCache()
    run(client.search_artists("Radiohead", record_cache=cache))
    profile = run(fetch_profile(client, cache, "ID-RADIOHEAD"))

    # Provenance: the original provider IDs are untouched.
    assert set(profile["genre_tags"]) == {
        "urn:tag:genre:rock",
        "urn:tag:genre:alternative_rock",
    }
    # Scoring sees one namespace for the same labels.
    assert set(profile["canonical_genre_tags"]) == {
        "urn:tag:genre:music:rock",
        "urn:tag:genre:music:alternative_rock",
    }
    assert profile["source"] == "qloo-search"


def test_insights_profile_carries_canonical_genres_alongside_raw_ids():
    def handler(request):
        return httpx.Response(200, json=INSIGHTS_OK)

    client = make_client(handler)
    profile = run(fetch_profile(client, TTLCache(), "ID-RADIOHEAD"))
    assert set(profile["genre_tags"]) == {
        "urn:tag:genre:music:rock",
        "urn:tag:genre:music:alternative_rock",
    }
    assert set(profile["canonical_genre_tags"]) == set(profile["genre_tags"])


def test_fetch_profile_missing_when_no_data_anywhere():
    def handler(request):
        return httpx.Response(200, json=INSIGHTS_EMPTY)

    client = make_client(handler)
    profile = run(fetch_profile(client, TTLCache(), "ID-UNKNOWN"))
    assert profile["missing"] is True
    assert profile["genre_tags"] == []
    assert "Missing" in profile["note"]


def test_fetch_profile_survives_upstream_failure():
    def handler(request):
        raise httpx.ConnectTimeout("down")

    client = make_client(handler)
    profile = run(fetch_profile(client, TTLCache(), "ID-X"))
    assert profile["missing"] is True
    assert profile["note"] and "failed" in profile["note"]
