"""Qloo hackathon API client.

Only endpoints verified against the official hackathon developer guide and
live API are used:

- GET /search?query=...&types=urn:entity:artist
- GET /v2/insights?filter.type=urn:tag&signal.interests.entities=<entity_id>&take=<n>

Taste analysis tags are a proxy for taste affinity. They are NOT verified
audience overlap, shared-fan percentages, or attendance forecasts.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

from . import config

logger = logging.getLogger("clashdoctor.qloo")


class QlooError(Exception):
    """Base class for Qloo integration errors."""


class QlooNotConfigured(QlooError):
    """No QLOO_API_KEY configured."""


class QlooUpstreamError(QlooError):
    """Transport failure, non-2xx response, or unparseable payload from Qloo."""


# Tag subtypes returned by /v2/insights that are relevant to artist taste.
GENRE_SUBTYPE = "urn:tag:genre:music"
AUDIENCE_SUBTYPE = "urn:tag:audience:qloo"
STYLE_SUBTYPE = "urn:tag:style:qloo"
MUSIC_SUBTYPE = "urn:tag:music:qloo"

# Search results embed tags with a slightly different vocabulary.
_SEARCH_AUDIENCE_PREFIX = "urn:tag:audience:qloo:"
_SEARCH_STYLE_PREFIX = "urn:tag:style:qloo:"
_SEARCH_MUSIC_PREFIX = "urn:tag:music:qloo:"
_SEARCH_GENRE_PREFIX = "urn:tag:genre:"
# Insights already use the music-genre namespace; search fallbacks do not.
CANONICAL_GENRE_PREFIX = "urn:tag:genre:music:"
_SEARCH_GENRE_NAMESPACES = (
    "urn:tag:genre:qloo:",
    _SEARCH_GENRE_PREFIX,
)
_GENRE_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")
# Genre-prefixed tags that are not about music genres.
_SEARCH_NON_MUSIC_GENRE = (
    "urn:tag:genre:person:",
    "urn:tag:genre:place:",
    "urn:tag:genre:brand:",
    "urn:tag:genre:book:",
    "urn:tag:genre:movie:",
    "urn:tag:genre:tv_",
    "urn:tag:genre:game",
    "urn:tag:genre:podcast",
    "urn:tag:genre:restaurant",
    "urn:tag:genre:hotel",
    "urn:tag:genre:cuisine",
    "urn:tag:genre:food",
)

# Candidate names containing these hints are penalized during validation
# (search returns tribute acts, mashups, etc.).
_SUSPECT_MARKERS = ("tribute", "mashup", "cover band", "karaoke", "dj mix", "remix")


@dataclass
class TagSet:
    genre: set = field(default_factory=set)
    audience: set = field(default_factory=set)
    style: set = field(default_factory=set)
    music: set = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (self.genre or self.audience or self.style or self.music)

    def all_tags(self) -> set:
        return self.genre | self.audience | self.style | self.music


@dataclass
class ArtistRecord:
    """Cached search-result data, used as a fallback tag source."""
    name: str | None = None
    tags: TagSet = field(default_factory=TagSet)


def _classify(tag_id: str, subtype: str | None = None) -> str | None:
    """Map a tag to genre/audience/style/music, or None if irrelevant."""
    if subtype:
        if subtype == GENRE_SUBTYPE:
            return "genre"
        if subtype == AUDIENCE_SUBTYPE:
            return "audience"
        if subtype == STYLE_SUBTYPE:
            return "style"
        if subtype == MUSIC_SUBTYPE:
            return "music"
        return None
    if tag_id.startswith(_SEARCH_AUDIENCE_PREFIX):
        return "audience"
    if tag_id.startswith(_SEARCH_STYLE_PREFIX):
        return "style"
    if tag_id.startswith(_SEARCH_MUSIC_PREFIX):
        return "music"
    if tag_id.startswith(_SEARCH_GENRE_PREFIX) and not any(
        tag_id.startswith(prefix) for prefix in _SEARCH_NON_MUSIC_GENRE
    ):
        return "genre"
    return None


def canonical_genre_tag(tag_id: str) -> str:
    """Map a music-genre tag onto the canonical insights namespace.

    Qloo returns the same genre vocabulary under different prefixes depending
    on the endpoint: ``/v2/insights`` uses ``urn:tag:genre:music:`` while the
    search fallback uses ``urn:tag:genre:`` or ``urn:tag:genre:qloo:``. This
    normalizes *the namespace only*: the slug is left untouched, so related but
    distinct labels (``folk`` vs ``indie_folk``) are never merged. Tags whose
    remainder is not a single slug are returned unchanged, which keeps
    non-music genres (``urn:tag:genre:person:...``) out of the canonical space.
    """
    if not tag_id or tag_id.startswith(CANONICAL_GENRE_PREFIX):
        return tag_id
    for prefix in _SEARCH_GENRE_NAMESPACES:
        if tag_id.startswith(prefix):
            slug = tag_id[len(prefix):]
            if _GENRE_SLUG.fullmatch(slug):
                return f"{CANONICAL_GENRE_PREFIX}{slug}"
            return tag_id
    return tag_id


def tags_from_insights(raw_tags: list) -> TagSet:
    """Extract relevant taste tags from /v2/insights response tags."""
    result = TagSet()
    for tag in raw_tags or []:
        tag_id = tag.get("tag_id") or tag.get("tag_value") or ""
        if not tag_id:
            continue
        category = _classify(tag_id, tag.get("subtype"))
        if category:
            getattr(result, category).add(tag_id)
    return result


def tags_from_search_entity(raw_tags: list) -> TagSet:
    """Extract relevant taste tags embedded in /search result entities."""
    result = TagSet()
    for tag in raw_tags or []:
        tag_id = tag.get("tag_id") or tag.get("value") or ""
        if not tag_id:
            continue
        category = _classify(tag_id)
        if category:
            getattr(result, category).add(tag_id)
    return result


def score_candidate(candidate: dict, query: str) -> float:
    """Heuristic match score for validating a search candidate."""
    name = (candidate.get("name") or "").strip().lower()
    target = query.strip().lower()
    score = 0.0
    if name == target:
        score += 2.0
    elif target and (target in name or name in target):
        score += 1.0
    if "urn:entity:artist" in (candidate.get("types") or []):
        score += 0.5
    popularity = candidate.get("popularity")
    if isinstance(popularity, (int, float)):
        score += min(max(popularity, 0.0), 1.0) * 0.5
    disambiguation = (candidate.get("disambiguation") or "").lower()
    properties = candidate.get("properties") or {}
    short_description = (properties.get("short_description") or "").lower()
    for marker in _SUSPECT_MARKERS:
        if marker in disambiguation or marker in short_description:
            score -= 1.5
    return score


def select_best_match(candidates: list[dict], query: str) -> tuple[dict | None, bool]:
    """Pick the best validated candidate; report ambiguity."""
    if not candidates:
        return None, False
    scored = sorted(candidates, key=lambda c: score_candidate(c, query), reverse=True)
    best = scored[0]
    best_score = score_candidate(best, query)
    ambiguous = best_score < 1.0 or (
        len(scored) > 1 and score_candidate(scored[1], query) >= best_score - 0.2
    )
    return best, ambiguous


class QlooClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = api_key if api_key is not None else config.QLOO_API_KEY
        self.base_url = (base_url or config.QLOO_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else config.QLOO_TIMEOUT_SECONDS
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _check_configured(self) -> None:
        if not self.configured:
            raise QlooNotConfigured(
                "QLOO_API_KEY is not set. Live Qloo data is unavailable; "
                "demo mode works without a key."
            )

    async def _request(self, method: str, path: str, params: dict, retries_left: int = 1) -> dict:
        self._check_configured()
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}
        try:
            response = await self._client.request(method, path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise QlooUpstreamError(f"Qloo request timed out: {path}") from exc
        except httpx.HTTPError as exc:
            raise QlooUpstreamError(f"Qloo request failed: {path} ({exc})") from exc
        if response.status_code == 429 and retries_left > 0:
            retry_after = response.headers.get("Retry-After", "")
            wait = min(float(retry_after), 2.0) if retry_after.isdigit() else 0.5
            await asyncio.sleep(wait)
            return await self._request(method, path, params, retries_left=retries_left - 1)
        if response.status_code == 429:
            raise QlooUpstreamError(
                "Qloo rate limit reached (HTTP 429). The request was retried once; "
                "try again shortly."
            )
        if response.status_code == 401:
            raise QlooUpstreamError("Qloo rejected the API key (HTTP 401). Check QLOO_API_KEY.")
        if response.status_code >= 400:
            raise QlooUpstreamError(f"Qloo returned HTTP {response.status_code} for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            raise QlooUpstreamError(f"Qloo returned a non-JSON payload for {path}.") from exc

    async def search_artists(self, query: str, record_cache=None) -> list[dict]:
        """Search Qloo for artist entities; cache embedded tags as fallback."""
        data = await self._request(
            "GET", "/search", {"query": query, "types": "urn:entity:artist"}
        )
        results = data.get("results") or []
        for item in results:
            entity_id = item.get("entity_id")
            if entity_id and record_cache is not None:
                record = record_cache.get(entity_id)
                if record is None:
                    record_cache.set(
                        entity_id,
                        ArtistRecord(
                            name=item.get("name"),
                            tags=tags_from_search_entity(item.get("tags") or []),
                        ),
                    )
        return results

    async def insights_tags(self, entity_id: str, take: int | None = None) -> list[dict]:
        """Fetch taste tags for an entity from /v2/insights."""
        data = await self._request(
            "GET",
            "/v2/insights",
            {
                "filter.type": "urn:tag",
                "signal.interests.entities": entity_id,
                "take": take if take is not None else config.QLOO_INSIGHTS_TAKE,
            },
        )
        return (data.get("results") or {}).get("tags") or []


async def fetch_profile(
    qloo: QlooClient, record_cache, entity_id: str, take: int | None = None
) -> dict:
    """Build a taste profile for an artist entity.

    Primary source: /v2/insights (filtered to genre/audience/style/music).
    Fallback: tags embedded in /search results (still Qloo data).
    An empty profile is reported as missing data, never as zero similarity.
    """
    tag_set = TagSet()
    source = "qloo-insights"
    notes: list[str] = []
    provider_failed = False

    try:
        raw_tags = await qloo.insights_tags(entity_id, take=take)
    except QlooUpstreamError as exc:
        notes.append(f"/v2/insights failed: {exc}")
        provider_failed = True
        raw_tags = []
    except QlooError as exc:
        notes.append(f"/v2/insights failed: {exc}")
        provider_failed = True
        raw_tags = []

    insights_tags = tags_from_insights(raw_tags)
    if not insights_tags.is_empty():
        tag_set = insights_tags
    else:
        notes.append("No relevant tags returned by /v2/insights.")
        record = record_cache.get(entity_id) if record_cache is not None else None
        if record is not None and not record.tags.is_empty():
            tag_set = record.tags
            source = "qloo-search"
            notes.append("Used tags embedded in /search results as fallback.")
        else:
            notes.append("No search-result tags cached for this entity.")

    missing = tag_set.is_empty()
    if missing:
        note = "Missing taste profile — no usable Qloo tags"
        if notes:
            note += f" ({'; '.join(notes)})"
        note += ". Excluded from similarity scores."
    else:
        note = "; ".join(notes) if notes else None

    return {
        "entity_id": entity_id,
        "source": source,
        "missing": missing,
        # True only when the provider failed AND nothing else filled the profile.
        # Such a result is an outage, not evidence about the artist, so the caller
        # must not remember it: the artist would look profile-less for a whole TTL
        # even after Qloo recovers.
        "provider_failed": provider_failed and missing,
        "note": note,
        "genre_tags": sorted(tag_set.genre),
        "canonical_genre_tags": sorted(
            {canonical_genre_tag(tag) for tag in tag_set.genre}
        ),
        "audience_tags": sorted(tag_set.audience),
        "style_tags": sorted(tag_set.style),
        "music_tags": sorted(tag_set.music),
    }
