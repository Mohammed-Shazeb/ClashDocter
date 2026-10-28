"""Deterministic offline stand-in for QlooClient.

The adapter emits the same raw payload shapes the real client returns, so the
production parsers (`tags_from_insights`, `tags_from_search_entity`,
`fetch_profile`) run unchanged in mock mode. Tags are derived from the
dataset's human genre descriptions plus per-group synthetic tags; they are
fixtures, never evidence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.qloo import ArtistRecord, QlooUpstreamError, tags_from_search_entity

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_CASES_PATH = FIXTURES_DIR / "mock_cases.json"

SUBTYPES = {
    "genre": "urn:tag:genre:music",
    "audience": "urn:tag:audience:qloo",
    "style": "urn:tag:style:qloo",
    "music": "urn:tag:music:qloo",
}

# Group-level synthetic vocabulary. These are not Qloo tag ids; they are named
# after the documented genre descriptions in the dataset.
GROUP_TAGS = {
    "art_rock_trip_hop": {"genre": ["alternative_rock"], "style": ["moody", "cinematic"]},
    "electronic_beats": {"genre": ["electronic"], "style": ["cerebral", "atmospheric"]},
    "post_rock": {"genre": ["post_rock", "ambient"], "style": ["cinematic", "atmospheric"]},
    "hip_hop_soul": {"genre": ["hip_hop"], "style": ["rhythmic", "urban"]},
    "jazz": {"genre": ["jazz"], "style": ["improvisational", "cerebral"]},
    "soul_afro": {"genre": ["soul"], "style": ["rhythmic", "uplifting"]},
    "indian_classical": {"genre": ["indian_classical"], "style": ["improvisational", "spiritual"]},
    "indian_fusion": {"genre": ["indian_classical", "progressive_rock"], "style": ["improvisational"]},
    "electronic_dance": {"genre": ["electronic", "dance"], "style": ["rhythmic", "energetic"]},
    "indie_rock": {"genre": ["indie_rock", "alternative_rock"], "style": ["melodic"]},
    "indie_folk": {"genre": ["indie_folk", "folk"], "style": ["acoustic", "melodic"]},
    "indian_hip_hop": {"genre": ["hip_hop"], "style": ["rhythmic", "urban"]},
}


class MockConfigError(ValueError):
    """The mock fixture references an artist that is not in the dataset."""


def load_mock_cases(path: str | Path | None = None) -> dict:
    with Path(path or DEFAULT_CASES_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _tag_ids(artist: dict, cases: dict) -> dict[str, list[str]]:
    """Synthetic tag ids per category for one artist."""
    tags = {category: set() for category in SUBTYPES}
    if artist["id"] in cases.get("sparse", []):
        tags["genre"].add("urn:tag:genre:music:indie_electronic")
    else:
        for genre in artist.get("genres", [])[:3]:
            tags["genre"].add(f"urn:tag:genre:music:{_slug(genre)}")
        group = GROUP_TAGS.get(artist.get("expected_group") or "", {})
        for genre in group.get("genre", []):
            tags["genre"].add(f"urn:tag:genre:music:{genre}")
        for style in group.get("style", []):
            tags["style"].add(f"urn:tag:style:qloo:{style}")
    if artist["id"] in cases.get("generic_artists", []):
        tags["genre"].add(cases["generic_tag"])
    return {category: sorted(values) for category, values in tags.items()}


def _search_vocabulary(tag_id: str) -> str:
    return tag_id.replace("urn:tag:genre:music:", "urn:tag:genre:")


def _candidate(artist: dict, suffix: str = "") -> dict:
    return {
        "name": artist["name"],
        "entity_id": f"mock:{artist['id']}{suffix}",
        "types": ["urn:entity:artist"],
        "disambiguation": "synthetic fixture entity",
        "properties": {
            "short_description": "Synthetic mock fixture — not a real Qloo record."
        },
    }


class MockQloo:
    """In-memory Qloo surface with scripted ambiguity, errors and gaps."""

    configured = True

    def __init__(self, dataset: dict, cases: dict):
        self.cases = cases
        self.by_name = {artist["name"]: artist for artist in dataset["artists"]}
        self.by_id = {artist["id"]: artist for artist in dataset["artists"]}
        missing = [
            artist_id
            for key in ("ambiguous", "no_match", "search_error", "insights_error",
                        "insights_empty", "no_search_tags", "sparse", "generic_artists")
            for artist_id in cases.get(key, [])
            if artist_id not in self.by_id
        ]
        if missing:
            raise MockConfigError(f"mock fixture references unknown artists: {sorted(set(missing))}")
        self.calls: list[tuple[str, str]] = []

    async def search_artists(self, query: str, record_cache=None) -> list[dict]:
        artist = self.by_name.get(query)
        if artist is None:
            return []
        self.calls.append(("search", artist["id"]))
        artist_id = artist["id"]
        if artist_id in self.cases.get("search_error", []):
            raise QlooUpstreamError("Qloo request timed out: /search")
        if artist_id in self.cases.get("no_match", []):
            return []

        results = [_candidate(artist)]
        if artist_id in self.cases.get("ambiguous", []):
            results.append(_candidate(artist, suffix="-namesake"))
        if record_cache is not None:
            for item in results:
                record_cache.set(
                    item["entity_id"],
                    ArtistRecord(
                        name=item["name"],
                        tags=tags_from_search_entity(self._search_tags(artist)),
                    ),
                )
        return results

    def _search_tags(self, artist: dict) -> list[dict]:
        if artist["id"] in self.cases.get("no_search_tags", []):
            return []
        tags = _tag_ids(artist, self.cases)
        return [
            {"tag_id": _search_vocabulary(tag_id)}
            for category in tags
            for tag_id in tags[category]
        ]

    async def insights_tags(self, entity_id: str, take: int | None = None) -> list[dict]:
        artist_id = entity_id.removeprefix("mock:").removesuffix("-namesake")
        artist = self.by_id.get(artist_id)
        if artist is None:
            return []
        self.calls.append(("insights", artist_id))
        if artist_id in self.cases.get("insights_error", []):
            raise QlooUpstreamError("Qloo returned HTTP 500 for /v2/insights.")
        if artist_id in self.cases.get("insights_empty", []):
            return []
        tags = _tag_ids(artist, self.cases)
        raw = [
            {
                "tag_id": tag_id,
                "name": tag_id.rsplit(":", 1)[-1].replace("_", " "),
                "subtype": SUBTYPES[category],
            }
            for category, tag_ids in tags.items()
            for tag_id in tag_ids
        ]
        return raw[:take] if take is not None else raw
