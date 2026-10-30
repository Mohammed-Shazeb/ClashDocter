"""Live Qloo probe v2: what real data supports for 30 established artists.

This probe reuses the shipped application pipeline rather than imitating it:

- resolution: ``app.qloo.QlooClient.search_artists`` + ``select_best_match``
- profiles:   ``app.qloo.fetch_profile`` (insights, search fallback, missing)
- scoring:    ``app.similarity.similarity_matrix`` and ``coverage``

Probe-specific code is limited to transport (disk cache, sequential throttling,
one retry for transient provider failures), analysis that the product does not
need, and reporting. No scoring rule is reimplemented here.

Successful raw responses are cached under the probe's ignored output root so a
rerun does not repeat paid/live calls. Cached payloads contain the response body
and request parameters, never headers or credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app import config
from app import similarity as sim
from app.cache import TTLCache
from app.qloo import (
    QlooClient,
    QlooError,
    QlooUpstreamError,
    canonical_genre_tag,
    fetch_profile,
    select_best_match,
)

from .core import (
    ProbeAborted,
    ProbeConfigError,
    different_verdict,
    is_auth_failure,
    percentile_values,
    redact,
    score_thresholds,
    similar_verdict,
)
from .v2_report import write_v2_reports

PROBE_VERSION = 2
DATASET_VERSION = 2
EXPECTED_ARTISTS = 30
DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "probe_v2_30.json"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "outputs" / "live-v2"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "outputs" / "cache" / "v2"
PRODUCTION_TAKE = 20
DEFAULT_TAKE = 50
MAX_TAKE = 50
DEFAULT_DEPTH_TAKE = 20
DEFAULT_DEPTH_PAIRS = 3
DEPTH_MATERIAL_DELTA = 0.05
DEFAULT_DELAY = 0.25
RETRY_BACKOFF_SECONDS = 1.0

STATUSES = ("matched", "ambiguous", "not_found", "api_error")
RAW_STATUS = {
    "matched": "matched",
    "ambiguous": "ambiguous",
    "not_found": "no_match",
    "api_error": "error",
}
GENRE_PREFIXES = (
    "urn:tag:genre:music:",
    "urn:tag:genre:qloo:",
    "urn:tag:genre:",
)
INSIGHTS_ERROR_MARKER = "/v2/insights failed:"

LIMITATIONS = [
    "Qloo tags are a proxy for taste affinity. They are not measured audience "
    "overlap, shared-fan percentages, ticket demand or attendance.",
    "take=50 is the largest /v2/insights depth documented as accepted (30 and 50 "
    "were accepted on 2026-10-23; 100 was rejected with HTTP 400). No pagination "
    "parameter is documented, so none was sent. Profiles remain truncated at 50.",
    "The 30 artists are handpicked established acts. Counts and percentiles "
    "describe this set only; this is not a statistical validation.",
    "A zero score means no shared returned tag in a category both artists have. It "
    "is not proof that fans, tastes or audiences do not overlap.",
    "Ambiguous names are excluded from profiling and scoring rather than manually "
    "confirmed, matching the product's resolution rule.",
    "The generic and broad tag annotations are lineup-local heuristics, not fitted "
    "or calibrated probabilities.",
    "Depth sensitivity is measured only on a small selected subset at take=20, not "
    "on every artist; the main matrix uses take=50.",
    "Successful responses may be served from the probe's disk cache on a rerun. "
    "The cache stores raw response bodies and request parameters only.",
    "There is no ground-truth audience-overlap data anywhere in this probe. No "
    "audience, attendance or ticket-split claim is supported.",
]


class ProbeDatasetError(ValueError):
    """The probe v2 dataset is missing, unreadable or invalid."""


# --- dataset ---

def load_dataset(path: str | Path | None = None) -> dict:
    target = Path(path or DEFAULT_DATASET)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProbeDatasetError(f"cannot read dataset {target}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeDatasetError(f"dataset {target} is not valid JSON: {exc}") from exc
    errors = validate_dataset(data)
    if errors:
        raise ProbeDatasetError("dataset invalid:\n- " + "\n- ".join(errors))
    return data


def validate_dataset(data: dict) -> list[str]:
    if not isinstance(data, dict):
        return ["top level must be a JSON object"]
    errors: list[str] = []
    if data.get("version") != DATASET_VERSION:
        errors.append(f"'version' must be {DATASET_VERSION}")
    artists = data.get("artists")
    if not isinstance(artists, list) or not artists:
        return errors + ["'artists' must be a non-empty list"]
    if len(artists) != EXPECTED_ARTISTS:
        errors.append(
            f"'artists' must contain exactly {EXPECTED_ARTISTS} entries "
            f"(found {len(artists)})"
        )
    ids: set[str] = set()
    queries: set[str] = set()
    for index, artist in enumerate(artists):
        where = f"artists[{index}]"
        if not isinstance(artist, dict):
            errors.append(f"{where} must be an object")
            continue
        for field in ("id", "name", "query", "scene", "why_selected"):
            value = artist.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{where} needs a non-empty {field!r}")
        artist_id = artist.get("id")
        if isinstance(artist_id, str):
            if artist_id in ids:
                errors.append(f"duplicate artist id {artist_id!r}")
            ids.add(artist_id)
        query = artist.get("query")
        if isinstance(query, str):
            if query in queries:
                errors.append(f"duplicate artist query {query!r}")
            queries.add(query)

    checks = data.get("sanity_checks")
    if not isinstance(checks, list) or not checks:
        errors.append("'sanity_checks' must be a non-empty list")
        return errors
    seen_checks: set[frozenset] = set()
    for index, check in enumerate(checks):
        where = f"sanity_checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{where} must be an object")
            continue
        a, b = check.get("a"), check.get("b")
        if a not in ids or b not in ids:
            errors.append(f"{where} references an unknown artist ({a!r}, {b!r})")
            continue
        if a == b:
            errors.append(f"{where} pairs an artist with itself")
        key = frozenset((a, b))
        if key in seen_checks:
            errors.append(f"{where} repeats a pair already checked")
        seen_checks.add(key)
        if check.get("expectation") not in ("similar", "lower"):
            errors.append(f"{where} expectation must be 'similar' or 'lower'")
        for field in ("id", "hypothesis"):
            value = check.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{where} needs a non-empty {field!r}")
    return errors


def dataset_digest(path: str | Path | None = None) -> str:
    target = Path(path or DEFAULT_DATASET)
    return hashlib.sha256(target.read_bytes()).hexdigest()


# --- cached transport ---

def _cache_key(method: str, path: str, params: dict, base_url: str) -> str:
    payload = json.dumps(
        {
            "base_url": base_url,
            "method": method,
            "path": path,
            "params": params,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_transient_message(message: str) -> bool:
    """Only transport, timeout and 5xx failures are safe to retry.

    429 is already retried once inside the production client, and auth or other
    4xx failures will not improve on a second attempt.
    """
    markers = ("timed out", "request failed", "HTTP 5")
    return any(marker in message for marker in markers)


class CachedQlooClient(QlooClient):
    """Production Qloo client plus a disk cache, throttling and bounded retries."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        delay: float = 0.0,
        refresh: bool = False,
        retry_backoff: float = RETRY_BACKOFF_SECONDS,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = max(0.0, delay)
        self.refresh = refresh
        self.retry_backoff = max(0.0, retry_backoff)
        self._last_attempt = 0.0
        self.stats = {
            "enabled": True,
            "cache_dir": str(self.cache_dir),
            "refresh": refresh,
            "cache_hits": 0,
            "cache_misses": 0,
            "logical_requests": 0,
            "network_attempts": 0,
            "network_succeeded": 0,
            "network_failures": 0,
            "transient_retries": 0,
            "client_internal_retries": 0,
        }

    async def _throttle(self) -> None:
        if not self.delay:
            return
        wait = self._last_attempt + self.delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_attempt = time.monotonic()

    def _read_cache(self, path: Path) -> dict | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        response = payload.get("response") if isinstance(payload, dict) else None
        return response if isinstance(response, dict) else None

    def _write_cache(
        self, path: Path, method: str, request_path: str, params: dict, response: dict
    ) -> None:
        payload = {
            "schema": 1,
            "base_url": self.base_url,
            "method": method,
            "path": request_path,
            "params": params,
            "fetched_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "response": response,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, path)

    async def _request(self, method: str, path: str, params: dict, retries_left: int = 1) -> dict:
        # The production client retries 429 by calling self._request again with
        # retries_left=0. That is a transport retry, not a new logical request, so
        # it must not enter the cache/stats layer a second time.
        if retries_left != 1:
            self.stats["client_internal_retries"] += 1
            return await super()._request(
                method, path, params, retries_left=retries_left
            )
        key = _cache_key(method, path, params, self.base_url)
        cache_path = self.cache_dir / f"{key}.json"
        self.stats["logical_requests"] += 1
        if not self.refresh:
            cached = self._read_cache(cache_path)
            if cached is not None:
                self.stats["cache_hits"] += 1
                return cached
        self.stats["cache_misses"] += 1

        response = None
        for attempt in (1, 2):
            await self._throttle()
            self.stats["network_attempts"] += 1
            try:
                response = await super()._request(
                    method, path, params, retries_left=retries_left
                )
                break
            except QlooUpstreamError as exc:
                if attempt == 1 and is_transient_message(str(exc)):
                    self.stats["transient_retries"] += 1
                    if self.retry_backoff:
                        await asyncio.sleep(self.retry_backoff)
                    continue
                self.stats["network_failures"] += 1
                raise
        if response is None:
            self.stats["network_failures"] += 1
            raise QlooUpstreamError(f"Qloo request failed without a response: {path}")
        self.stats["network_succeeded"] += 1
        self._write_cache(cache_path, method, path, params, response)
        return response


# --- profile records ---

def _genre_prefix_counts(tags: list[str]) -> dict[str, int]:
    counts: Counter = Counter()
    for tag in tags:
        for prefix in GENRE_PREFIXES:
            if tag.startswith(prefix):
                counts[prefix] += 1
                break
        else:
            counts["(other)"] += 1
    return dict(sorted(counts.items()))


def _coverage_class(missing: bool, tag_counts: dict[str, int]) -> str:
    if missing:
        return "missing"
    categories = sum(1 for value in tag_counts.values() if value)
    total = sum(tag_counts.values())
    if categories < 2 or total < 3:
        return "sparse"
    if not tag_counts.get("genre"):
        return "genre_thin"
    return "ok"


def _profile_section(profile: dict | None, resolution: dict) -> dict:
    if profile is None:
        status = resolution["status"]
        if status == "ambiguous":
            source = "unconfirmed"
            reason = "Name matched only ambiguous candidates; a user must confirm an entity"
        elif status == "api_error":
            source = "unresolved"
            reason = resolution.get("error") or "Qloo search failed"
        elif status == "not_found":
            source = "unresolved"
            reason = "No Qloo artist entity selected"
        else:
            source = "unresolved"
            reason = "No Qloo entity selected"
        empty = {category: [] for category in sim.CATEGORIES}
        zero = {category: 0 for category in sim.CATEGORIES}
        return {
            "source": source,
            "missing": True,
            "provider_failed": status == "api_error",
            "note": f"{reason}; excluded from similarity.",
            "tags": empty,
            "canonical_tags": {category: [] for category in sim.CATEGORIES},
            "tag_counts": zero,
            "raw_tag_counts": {category: 0 for category in sim.CATEGORIES},
            "missing_categories": list(sim.CATEGORIES),
            "genre_namespace": {
                "prefix_counts": {},
                "raw_count": 0,
                "canonical_count": 0,
            },
            "coverage_class": "missing",
        }

    tags = {
        category: sorted(profile.get(f"{category}_tags") or [])
        for category in sim.CATEGORIES
    }
    canonical_genre = sorted(
        profile.get("canonical_genre_tags")
        or {canonical_genre_tag(tag) for tag in tags["genre"]}
    )
    canonical_tags = {**tags, "genre": canonical_genre}
    tag_counts = {
        category: len(canonical_tags[category]) for category in sim.CATEGORIES
    }
    missing = bool(profile.get("missing"))
    return {
        "source": profile.get("source"),
        "missing": missing,
        "provider_failed": bool(profile.get("provider_failed")),
        "note": profile.get("note"),
        "tags": tags,
        "canonical_tags": canonical_tags,
        "tag_counts": tag_counts,
        "raw_tag_counts": {
            category: len(tags[category]) for category in sim.CATEGORIES
        },
        "missing_categories": [
            category for category in sim.CATEGORIES if not tag_counts[category]
        ],
        "genre_namespace": {
            "prefix_counts": _genre_prefix_counts(tags["genre"]),
            "raw_count": len(tags["genre"]),
            "canonical_count": len(canonical_genre),
        },
        "coverage_class": _coverage_class(missing, tag_counts),
    }


def _scoring_profile(record: dict) -> dict:
    section = record["profile"]
    entity_id = (
        record["resolution"].get("selected_entity_id")
        if record["resolution"]["status"] == "matched"
        else f"unresolved:{record['id']}"
    )
    return {
        "entity_id": entity_id or f"unresolved:{record['id']}",
        "name": record["name"],
        "source": section["source"],
        "missing": section["missing"],
        "genre_tags": section["tags"]["genre"],
        "canonical_genre_tags": section["canonical_tags"]["genre"],
        "audience_tags": section["canonical_tags"]["audience"],
        "style_tags": section["canonical_tags"]["style"],
        "music_tags": section["canonical_tags"]["music"],
    }


def _artist_record(artist: dict, resolution: dict, profile: dict | None) -> dict:
    return {
        "id": artist["id"],
        "name": artist["name"],
        "query": artist["query"],
        "scene": artist["scene"],
        "why_selected": artist["why_selected"],
        "resolution": resolution,
        "profile": _profile_section(profile, resolution),
    }


def _candidate(item: dict) -> dict:
    properties = item.get("properties") or {}
    return {
        "name": item.get("name"),
        "entity_id": item.get("entity_id"),
        "types": item.get("types") or [],
        "popularity": item.get("popularity"),
        "disambiguation": item.get("disambiguation"),
        "short_description": properties.get("short_description"),
    }


async def _resolve_artist(
    client, artist: dict, record_cache: TTLCache, secret: str | None, calls: dict
) -> tuple[dict, dict | None]:
    calls["search"] += 1
    try:
        results = await client.search_artists(artist["query"], record_cache=record_cache)
    except QlooError as exc:
        message = redact(str(exc), secret) or "Qloo search failed"
        if is_auth_failure(message):
            raise ProbeAborted(message, "search", artist["id"]) from exc
        return (
            {
                "status": "api_error",
                "raw_status": RAW_STATUS["api_error"],
                "query": artist["query"],
                "selected_entity_id": None,
                "top_candidate_entity_id": None,
                "ambiguous": False,
                "candidate_count": 0,
                "candidates": [],
                "error": message,
            },
            None,
        )

    best, ambiguous = select_best_match(results, artist["query"])
    if best is None:
        status = "not_found"
    elif ambiguous:
        status = "ambiguous"
    else:
        status = "matched"
    return (
        {
            "status": status,
            "raw_status": RAW_STATUS[status],
            "query": artist["query"],
            "selected_entity_id": (
                best.get("entity_id") if status == "matched" and best else None
            ),
            "top_candidate_entity_id": best.get("entity_id") if best else None,
            "ambiguous": bool(ambiguous),
            "candidate_count": len(results),
            "candidates": [_candidate(item) for item in results[:5]],
            "error": None,
        },
        best,
    )


async def _load_profile(
    client,
    profile_cache: TTLCache,
    record_cache: TTLCache,
    entity_id: str,
    take: int,
    secret: str | None,
    calls: dict,
) -> tuple[dict, bool]:
    key = (entity_id, take)
    cached = profile_cache.get(key)
    if cached is not None:
        profile = dict(cached)
        profile["note"] = redact(profile.get("note"), secret)
        return profile, True
    calls["insights"] += 1
    profile = dict(await fetch_profile(client, record_cache, entity_id, take=take))
    profile["note"] = redact(profile.get("note"), secret)
    note = profile.get("note") or ""
    if profile.get("provider_failed") and is_auth_failure(note):
        raise ProbeAborted(note, "insights", entity_id)
    if not profile.get("provider_failed"):
        profile_cache.set(key, profile)
    return profile, False


def _insights_error(profile: dict) -> str | None:
    note = profile.get("note") or ""
    return note if INSIGHTS_ERROR_MARKER in note else None


# --- analysis ---

def _distribution(values: list[float]) -> dict:
    n = len(values)
    if not n:
        return {
            "n": 0,
            "min": None,
            "q1": None,
            "median": None,
            "q3": None,
            "mean": None,
            "max": None,
            "p90": None,
            "zeros": 0,
            "zero_share": 0.0,
        }
    ordered = sorted(values)
    if n == 1:
        q1 = q2 = q3 = ordered[0]
    else:
        q1, q2, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    zeros = sum(1 for value in ordered if value == 0.0)
    return {
        "n": n,
        "min": round(ordered[0], 4),
        "q1": round(q1, 4),
        "median": round(q2, 4),
        "q3": round(q3, 4),
        "mean": round(statistics.fmean(ordered), 4),
        "max": round(ordered[-1], 4),
        "p90": round(ordered[max(0, math.ceil(0.9 * n) - 1)], 4),
        "zeros": zeros,
        "zero_share": round(zeros / n, 4),
    }


def _resolution_summary(records: list[dict]) -> dict:
    artists = {status: [] for status in STATUSES}
    raw = Counter()
    for record in records:
        status = record["resolution"]["status"]
        artists.setdefault(status, []).append(record["name"])
        raw[record["resolution"]["raw_status"]] += 1
    return {
        "counts": {status: len(artists.get(status, [])) for status in STATUSES},
        "artists": artists,
        "raw_status_counts": dict(sorted(raw.items())),
    }


def _profile_coverage(records: list[dict], coverage: dict) -> dict:
    sources: Counter = Counter()
    classes: Counter = Counter()
    genre_artists = 0
    usable = 0
    for record in records:
        status = record["resolution"]["status"]
        section = record["profile"]
        if status == "matched" and not section["missing"]:
            usable += 1
            sources[section["source"]] += 1
            if section["tag_counts"]["genre"]:
                genre_artists += 1
        elif status == "matched":
            sources["matched, no usable tags"] += 1
        elif status == "ambiguous":
            sources["unconfirmed"] += 1
        else:
            sources["unresolved"] += 1
        classes[section["coverage_class"]] += 1
    return {
        "profiles_total": len(records),
        "usable": usable,
        "missing": len(records) - usable,
        "source_counts": dict(sorted(sources.items())),
        "coverage_class_counts": dict(sorted(classes.items())),
        "genre_artists": genre_artists,
        "genre_share_of_usable": round(genre_artists / usable, 4) if usable else 0.0,
        "category_coverage": coverage["category_coverage"],
        "thin_categories": coverage["thin_categories"],
    }


def _confidence_breakdown(scored: list[dict]) -> dict:
    triggers: Counter = Counter()
    category_counts: Counter = Counter()
    for pair in scored:
        category_count = len(pair["categories_compared"])
        category_counts[category_count] += 1
        union_tags = sum(signal["union_count"] for signal in pair["signals"])
        if category_count < sim.MIN_CATEGORIES_FOR_CONFIDENT_SCORE:
            triggers["fewer_than_2_categories"] += 1
        if union_tags < sim.MIN_UNION_TAGS_FOR_CONFIDENT_SCORE:
            triggers["fewer_than_6_union_tags"] += 1
        if 0 < pair["shared_tag_count"] < sim.MIN_SHARED_TAGS_FOR_CONFIDENT_SCORE:
            triggers["single_shared_tag"] += 1
        if (
            pair["shared_tag_count"]
            and pair["shared_generic_tag_count"] == pair["shared_tag_count"]
        ):
            triggers["all_shared_tags_generic"] += 1
    return {
        "sufficient_evidence": sum(1 for pair in scored if not pair["low_confidence"]),
        "low_confidence": sum(1 for pair in scored if pair["low_confidence"]),
        "genre_backed": sum(
            1 for pair in scored if pair["genre_similarity"] is not None
        ),
        "without_genre": sum(
            1 for pair in scored if pair["genre_similarity"] is None
        ),
        "categories_compared_distribution": {
            str(key): value for key, value in sorted(category_counts.items())
        },
        "low_confidence_trigger_counts": dict(sorted(triggers.items())),
        "note": (
            "Triggers overlap: a pair can be low-confidence for more than one reason, "
            "so trigger counts are not mutually exclusive."
        ),
    }


def _shared_tag_frequency(
    scoring_profiles: list[dict], scored: list[dict], generic: set, broad: set
) -> dict:
    tagged = [profile for profile in scoring_profiles if sim.all_tags(profile)]
    artist_counts: Counter = Counter()
    tag_categories: dict[str, set] = defaultdict(set)
    for profile in tagged:
        for category in sim.CATEGORIES:
            for tag in sim.category_tags(profile, category):
                artist_counts[tag] += 1
                tag_categories[tag].add(category)
    pair_counts: Counter = Counter()
    for pair in scored:
        for tag in set(pair["shared_tags"]):
            pair_counts[tag] += 1
    rows = []
    for tag, pair_count in pair_counts.items():
        rows.append(
            {
                "tag": tag,
                "categories": sorted(tag_categories.get(tag, set())),
                "artists": artist_counts.get(tag, 0),
                "of_artists": len(tagged),
                "artist_share": (
                    round(artist_counts.get(tag, 0) / len(tagged), 4) if tagged else 0.0
                ),
                "pairs": pair_count,
                "of_scored_pairs": len(scored),
                "pair_share": round(pair_count / len(scored), 4) if scored else 0.0,
                "generic_rule": tag in generic,
                "broad_rule": tag in broad,
            }
        )
    rows.sort(key=lambda row: (-row["pairs"], -row["artists"], row["tag"]))
    return {
        "distinct_shared_tags": len(rows),
        "pairs_with_shared_tags": sum(
            1 for pair in scored if pair["shared_tag_count"] > 0
        ),
        "pairs_without_shared_tags": sum(
            1 for pair in scored if pair["shared_tag_count"] == 0
        ),
        "rows": rows,
    }


def _generic_dominance(scored: list[dict], generic: set) -> dict:
    top = scored[:10]
    top_with_shared = [pair for pair in top if pair["shared_tag_count"]]
    top_rows = [
        {
            "pair": [pair["artist_a"]["name"], pair["artist_b"]["name"]],
            "artist_ids": [pair["artist_a"]["id"], pair["artist_b"]["id"]],
            "rank": pair.get("rank"),
            "taste_similarity": pair["taste_similarity"],
            "shared_tag_count": pair["shared_tag_count"],
            "shared_generic_tag_count": pair["shared_generic_tag_count"],
            "generic_share": pair["generic_share"],
            "all_shared_tags_generic": (
                pair["shared_tag_count"] > 0
                and pair["shared_generic_tag_count"] == pair["shared_tag_count"]
            ),
            "shared_tags": pair["shared_tags"],
            "shared_specific_tags": pair["shared_specific_tags"],
        }
        for pair in top
    ]
    majority = [
        pair
        for pair in scored
        if pair["shared_tag_count"] and pair["generic_share"] >= 0.5
    ]
    specific = [
        pair
        for pair in scored
        if pair["shared_tag_count"] and pair["generic_share"] < 0.5
    ]
    return {
        "lineup_generic_tags": sorted(generic),
        "lineup_generic_tag_count": len(generic),
        "top_pair_limit": len(top),
        "top_pairs": top_rows,
        "top_mean_generic_share": (
            round(
                statistics.fmean(
                    pair["generic_share"] for pair in top_with_shared
                ),
                4,
            )
            if top_with_shared
            else 0.0
        ),
        "top_pairs_all_generic": sum(
            1
            for pair in top
            if pair["shared_tag_count"]
            and pair["shared_generic_tag_count"] == pair["shared_tag_count"]
        ),
        "top_pairs_majority_generic": sum(
            1
            for pair in top
            if pair["shared_tag_count"] and pair["generic_share"] >= 0.5
        ),
        "scored_pairs_all_generic": sum(
            1
            for pair in scored
            if pair["shared_tag_count"]
            and pair["shared_generic_tag_count"] == pair["shared_tag_count"]
        ),
        "scored_pairs_majority_generic": len(majority),
        "scored_pairs_majority_specific": len(specific),
        "mean_score_majority_generic": (
            round(statistics.fmean(pair["taste_similarity"] for pair in majority), 4)
            if majority
            else None
        ),
        "mean_score_majority_specific": (
            round(statistics.fmean(pair["taste_similarity"] for pair in specific), 4)
            if specific
            else None
        ),
        "note": (
            "Generic is the production lineup-local rule: a tag on at least a "
            f"quarter of tagged profiles (minimum {sim.MIN_GENERIC_TAG_ARTISTS} "
            "carriers and 6 tagged profiles). It never changes a score."
        ),
    }


def _pair_brief(pair: dict, percentiles: dict) -> dict:
    ids = [pair["artist_a"]["id"], pair["artist_b"]["id"]]
    return {
        "rank": pair.get("rank"),
        "pair": [pair["artist_a"]["name"], pair["artist_b"]["name"]],
        "artist_ids": ids,
        "scenes": [pair["artist_a"]["scene"], pair["artist_b"]["scene"]],
        "taste_similarity": pair["taste_similarity"],
        "genre_similarity": pair["genre_similarity"],
        "combined_similarity": pair["combined_similarity"],
        "percentile": percentiles.get(frozenset(ids)),
        "low_confidence": pair["low_confidence"],
        "confidence_note": pair["confidence_note"],
        "genre_backed": pair["genre_backed"],
        "shared_tag_count": pair["shared_tag_count"],
        "shared_tags": pair["shared_tags"],
        "shared_generic_tag_count": pair["shared_generic_tag_count"],
        "shared_specific_tags": pair["shared_specific_tags"],
        "generic_share": pair["generic_share"],
        "categories_compared": pair["categories_compared"],
        "profile_sources": pair["profile_sources"],
        "evidence_limitations": pair["evidence_limitations"],
    }


def _insufficient_coverage(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        status = record["resolution"]["status"]
        section = record["profile"]
        coverage_class = section["coverage_class"]
        if status == "matched" and coverage_class == "ok":
            continue
        if status == "ambiguous":
            reason = (
                "Ambiguous name with no user-confirmed entity; not profiled or scored."
            )
        elif status == "not_found":
            reason = "No Qloo artist entity selected."
        elif status == "api_error":
            reason = record["resolution"].get("error") or "Qloo search failed."
        elif section["missing"]:
            reason = section.get("note") or "No usable Qloo tags."
        elif coverage_class == "sparse":
            categories = sum(
                1 for value in section["tag_counts"].values() if value
            )
            total = sum(section["tag_counts"].values())
            reason = (
                f"{categories} categories, {total} tag(s); comparisons involving "
                "this artist are thin."
            )
        else:
            reason = (
                "No genre tags; only non-genre dimensions can be compared, so the "
                "0.55 genre weight is unavailable."
            )
        rows.append(
            {
                "artist_id": record["id"],
                "name": record["name"],
                "resolution_status": status,
                "source": section["source"],
                "coverage_class": coverage_class,
                "tag_counts": section["tag_counts"],
                "raw_genre_count": section["genre_namespace"]["raw_count"],
                "canonical_genre_count": section["genre_namespace"]["canonical_count"],
                "missing_categories": section["missing_categories"],
                "reason": reason,
            }
        )
    return rows


def _matrix_summary(pairs: list[dict], scored: list[dict], thresholds: dict) -> dict:
    scores = [pair["taste_similarity"] for pair in scored]
    zero_count = sum(1 for score in scores if score == 0.0)
    zero_share = zero_count / len(scores) if scores else 0.0
    distinct = len(set(scores))
    verdicts_informative = bool(
        scores and zero_share < 0.5 and distinct >= 3
    )
    if not scores:
        verdict_note = "No scored pairs; no percentile verdict can be computed."
    elif verdicts_informative:
        verdict_note = (
            f"Percentile verdicts are descriptive: {zero_share:.1%} of scored pairs "
            f"tie at 0.000 and there are {distinct} distinct score values."
        )
    else:
        verdict_note = (
            f"Percentile verdicts are qualified: {zero_share:.1%} of "
            f"{len(scores)} scored pairs tie at 0.000 ({distinct} distinct score "
            "value(s)). Read verdicts as zero-versus-nonzero, not a graded ranking."
        )
    missing = [pair for pair in pairs if pair["missing"]]
    return {
        "pairs_total": len(pairs),
        "pairs_scored": len(scored),
        "pairs_missing": len(missing),
        "scored_share": round(len(scored) / len(pairs), 4) if pairs else 0.0,
        "zero_count": zero_count,
        "zero_share": round(zero_share, 4),
        "distribution": _distribution(scores),
        "nonzero_distribution": _distribution(
            [score for score in scores if score > 0]
        ),
        "score_thresholds": thresholds,
        "distinct_scores": distinct,
        "verdicts_informative": verdicts_informative,
        "verdict_note": verdict_note,
        "pairs_with_genre_both": sum(
            1 for pair in scored if pair["genre_similarity"] is not None
        ),
        "pairs_sufficient_with_genre": sum(
            1
            for pair in scored
            if not pair["low_confidence"] and pair["genre_similarity"] is not None
        ),
        "missing_kinds": dict(
            sorted(
                Counter(pair.get("missing_kind") for pair in missing).items(),
                key=lambda item: (-item[1], str(item[0])),
            )
        ),
    }


def _diagnosis(scored: list[dict], coverage: dict) -> dict:
    scores = [pair["taste_similarity"] for pair in scored]
    zeros = [pair for pair in scored if pair["taste_similarity"] == 0.0]
    zero_both_genre = sum(
        1 for pair in zeros if pair["genre_similarity"] is not None
    )
    zero_disjoint = sum(1 for pair in zeros if pair["shared_tag_count"] == 0)
    zero_without_genre = len(zeros) - zero_both_genre
    zero_share = len(zeros) / len(scores) if scores else 0.0
    usable = coverage["profiles_with_data"]
    genre_artists = coverage["category_coverage"]["genre"]["artists"]

    if usable == 0:
        likely = (
            "No usable profiles: the run cannot support any similarity finding, "
            "even if the search endpoint resolved names."
        )
    elif not scored:
        likely = (
            "Profiles exist but no pair shares a comparable tag category; this is "
            "a data-shape or coverage problem, not a scoring failure."
        )
    elif zero_share >= 0.5 and zero_disjoint >= max(1, int(0.8 * len(zeros))):
        likely = (
            "Zero-heavy distribution driven by disjoint returned tag sets on pairs "
            "that do have comparable categories. This reads as real-data sparsity, "
            "not a missing-data or namespace failure."
        )
    elif zero_share >= 0.5:
        likely = (
            "Zero-heavy distribution with limited or one-sided category coverage. "
            "Inspect the per-artist coverage table before reading low scores as "
            "dissimilarity."
        )
    else:
        likely = (
            "Scores are graded rather than zero-inflated; they remain tag-affinity "
            "estimates, not audience overlap."
        )
    return {
        "zero_count": len(zeros),
        "zero_share": round(zero_share, 4),
        "zero_pairs_with_genre_both": zero_both_genre,
        "zero_pairs_without_genre_side": zero_without_genre,
        "zero_pairs_no_shared_tags": zero_disjoint,
        "usable_artists": usable,
        "genre_artists": genre_artists,
        "genre_share_of_usable": (
            round(genre_artists / usable, 4) if usable else 0.0
        ),
        "likely_cause": likely,
        "basis": (
            f"{len(zeros)} zero pair(s) of {len(scores)} scored; "
            f"{zero_both_genre} zero pair(s) had genre on both sides, "
            f"{zero_disjoint} had no shared tag in any compared category, and "
            f"{zero_without_genre} lacked genre on at least one side. "
            f"{genre_artists} of {usable} usable artist(s) carry genre tags."
        ),
    }


def _sanity_checks(
    dataset: dict,
    records: list[dict],
    pairs_by_key: dict,
    thresholds: dict,
    percentiles: dict,
) -> list[dict]:
    records_by_id = {record["id"]: record for record in records}
    rows = []
    for check in dataset["sanity_checks"]:
        pair = pairs_by_key.get(frozenset((check["a"], check["b"])))
        score = pair["taste_similarity"] if pair else None
        if pair is None or pair["missing"]:
            verdict = "unscored"
        elif check["expectation"] == "similar":
            verdict = similar_verdict(
                score, thresholds["p80"], thresholds["p50"]
            )
        else:
            verdict = different_verdict(
                score, thresholds["p20"], thresholds["p50"]
            )
        percentile = (
            percentiles.get(frozenset((check["a"], check["b"]))) if pair else None
        )
        shared_evidence = (
            [
                {
                    "category": signal["category"],
                    "jaccard": signal["jaccard"],
                    "weight": signal["weight"],
                    "shared_tags": signal["shared_tags"],
                }
                for signal in pair["signals"]
            ]
            if pair and not pair["missing"]
            else []
        )
        profile_counts = {
            side: records_by_id.get(side, {}).get("profile", {}).get("tag_counts")
            for side in (check["a"], check["b"])
        }
        if pair is None:
            interpretation = "The pair is absent from the matrix."
        elif pair["missing"]:
            interpretation = (
                "Not scored: "
                + (pair.get("missing_reason") or "no comparable data")
                + ". No evidence supports or contradicts the hypothesis."
            )
        else:
            confidence_text = (
                "low confidence: " + (pair.get("confidence_note") or "thin evidence")
                if pair["low_confidence"]
                else "the production confidence rule passed"
            )
            shared_text = (
                ", ".join(pair["shared_tags"][:6]) or "none"
            )
            interpretation = (
                f"Taste {score}; genre {pair['genre_similarity']}; "
                f"{pair['shared_tag_count']} shared tag(s) [{shared_text}] across "
                f"{', '.join(pair['categories_compared'])}; {confidence_text}. "
                f"The predeclared hypothesis was '{check['expectation']}'; this "
                f"pair sits at percentile {percentile} of scored pairs. Tag "
                "affinity only, not audience overlap."
            )
        rows.append(
            {
                "id": check["id"],
                "a": check["a"],
                "b": check["b"],
                "pair": (
                    [pair["artist_a"]["name"], pair["artist_b"]["name"]]
                    if pair
                    else None
                ),
                "expectation": check["expectation"],
                "hypothesis": check["hypothesis"],
                "verdict": verdict,
                "verdict_basis": (
                    "percentile among scored pairs in this 30-artist set; "
                    "descriptive, not ground truth"
                ),
                "taste_similarity": score,
                "genre_similarity": pair["genre_similarity"] if pair else None,
                "combined_similarity": pair["combined_similarity"] if pair else None,
                "percentile": percentile,
                "low_confidence": pair["low_confidence"] if pair else None,
                "confidence_note": pair["confidence_note"] if pair else None,
                "genre_backed": pair["genre_backed"] if pair else None,
                "shared_tag_count": pair["shared_tag_count"] if pair else None,
                "shared_tags": pair["shared_tags"] if pair else None,
                "shared_evidence": shared_evidence,
                "skipped_categories": pair["skipped_categories"] if pair else None,
                "profile_tag_counts": profile_counts,
                "evidence_limitations": pair["evidence_limitations"] if pair else None,
                "interpretation": interpretation,
            }
        )
    return rows


def _select_depth_pairs(scored: list[dict], limit: int) -> list[dict]:
    if limit <= 0 or not scored:
        return []
    ordered = sorted(
        scored,
        key=lambda pair: (
            -pair["taste_similarity"],
            pair["artist_a"]["name"],
            pair["artist_b"]["name"],
        ),
    )
    preferred = [ordered[0], ordered[len(ordered) // 2]]
    zero = next(
        (pair for pair in ordered if pair["taste_similarity"] == 0.0), None
    )
    preferred.append(zero or ordered[-1])
    selected = []
    used: set[str] = set()
    for pair in preferred:
        ids = {pair["artist_a"]["id"], pair["artist_b"]["id"]}
        if ids & used:
            continue
        selected.append(pair)
        used |= ids
        if len(selected) == limit:
            return selected
    for pair in ordered:
        if len(selected) == limit:
            break
        ids = {pair["artist_a"]["id"], pair["artist_b"]["id"]}
        if ids & used:
            continue
        selected.append(pair)
        used |= ids
    return selected[:limit]


async def _depth_sensitivity(
    client,
    selected: list[dict],
    records_by_id: dict,
    scoring_by_id: dict,
    profile_cache: TTLCache,
    record_cache: TTLCache,
    take: int,
    depth_take: int,
    broad: set,
    generic: set,
    secret: str | None,
    calls: dict,
) -> dict:
    rows = []
    try:
        for pair in selected:
            ids = [pair["artist_a"]["id"], pair["artist_b"]["id"]]
            shallow_profiles = {}
            shallow_sections = {}
            for artist_id in ids:
                record = records_by_id[artist_id]
                entity_id = record["resolution"]["selected_entity_id"]
                profile, _hit = await _load_profile(
                    client,
                    profile_cache,
                    record_cache,
                    entity_id,
                    depth_take,
                    secret,
                    calls,
                )
                shallow_sections[artist_id] = _profile_section(
                    profile, record["resolution"]
                )
                shallow_profiles[artist_id] = _scoring_profile(
                    {**record, "profile": shallow_sections[artist_id]}
                )
            shallow_pair = sim.pair_similarity(
                shallow_profiles[ids[0]], shallow_profiles[ids[1]], broad, generic
            )
            deep_score = pair["taste_similarity"]
            shallow_score = shallow_pair["taste_similarity"]
            delta = (
                None
                if deep_score is None or shallow_score is None
                else round(deep_score - shallow_score, 4)
            )
            rows.append(
                {
                    "pair": [pair["artist_a"]["name"], pair["artist_b"]["name"]],
                    "artist_ids": ids,
                    "deep": {
                        "take": take,
                        "taste_similarity": deep_score,
                        "genre_similarity": pair["genre_similarity"],
                        "combined_similarity": pair["combined_similarity"],
                        "shared_tag_count": pair["shared_tag_count"],
                        "low_confidence": pair["low_confidence"],
                    },
                    "shallow": {
                        "take": depth_take,
                        "taste_similarity": shallow_score,
                        "genre_similarity": shallow_pair["genre_similarity"],
                        "combined_similarity": shallow_pair["combined_similarity"],
                        "shared_tag_count": shallow_pair["shared_tag_count"],
                        "low_confidence": shallow_pair["low_confidence"],
                        "missing": shallow_pair["missing"],
                        "missing_reason": shallow_pair["missing_reason"],
                    },
                    "delta_taste_deep_minus_shallow": delta,
                    "abs_taste_delta": None if delta is None else round(abs(delta), 4),
                    "material": (
                        delta is not None
                        and abs(delta) >= DEPTH_MATERIAL_DELTA
                    ),
                    "tag_counts_deep": {
                        side: records_by_id[side]["profile"]["tag_counts"]
                        for side in ids
                    },
                    "tag_counts_shallow": {
                        side: shallow_sections[side]["tag_counts"] for side in ids
                    },
                    "genre_counts_deep": {
                        side: records_by_id[side]["profile"]["genre_namespace"]
                        for side in ids
                    },
                    "genre_counts_shallow": {
                        side: shallow_sections[side]["genre_namespace"]
                        for side in ids
                    },
                    "profile_sources_shallow": {
                        side: shallow_sections[side]["source"] for side in ids
                    },
                    "insights_errors": [
                        shallow_sections[side]["note"]
                        for side in ids
                        if shallow_sections[side]["note"]
                        and INSIGHTS_ERROR_MARKER in shallow_sections[side]["note"]
                    ],
                }
            )
    except ProbeAborted as exc:
        return {
            "enabled": True,
            "take_deep": take,
            "take_shallow": depth_take,
            "material_delta_threshold": DEPTH_MATERIAL_DELTA,
            "pairs_requested": len(selected),
            "pairs_checked": len(rows),
            "error": exc.message,
            "rows": rows,
        }
    deltas = [
        row["abs_taste_delta"]
        for row in rows
        if row["abs_taste_delta"] is not None
    ]
    return {
        "enabled": True,
        "take_deep": take,
        "take_shallow": depth_take,
        "material_delta_threshold": DEPTH_MATERIAL_DELTA,
        "pairs_requested": len(selected),
        "pairs_checked": len(rows),
        "pairs_with_comparable_scores": len(deltas),
        "material_pairs": sum(1 for row in rows if row["material"]),
        "max_abs_taste_delta": max(deltas) if deltas else None,
        "mean_abs_taste_delta": (
            round(statistics.fmean(deltas), 4) if deltas else None
        ),
        "rows": rows,
        "note": (
            "Selected pairs are the highest-scoring pair, the median-scoring pair "
            "and a zero-score pair with distinct artists. Delta is deep take minus "
            f"shallow take; a change of at least {DEPTH_MATERIAL_DELTA} is called "
            "material for this probe, a descriptive cutoff rather than a "
            "significance test."
        ),
    }


# --- run ---

async def run_probe_v2(
    *,
    dataset_path: str | Path | None = None,
    client=None,
    take: int = DEFAULT_TAKE,
    depth_take: int = DEFAULT_DEPTH_TAKE,
    depth_pairs: int = DEFAULT_DEPTH_PAIRS,
    delay: float = DEFAULT_DELAY,
    cache_dir: str | Path | None = None,
    refresh: bool = False,
    secret: str | None = None,
    now: datetime | None = None,
) -> dict:
    if not 1 <= take <= MAX_TAKE:
        raise ValueError(f"take must be between 1 and {MAX_TAKE}")
    if depth_pairs < 0:
        raise ValueError("depth_pairs must be >= 0")
    if depth_pairs and not 1 <= depth_take < take:
        raise ValueError("depth_take must be between 1 and take-1")
    if delay < 0:
        raise ValueError("delay must be >= 0")

    dataset = load_dataset(dataset_path)
    secret = config.QLOO_API_KEY if secret is None else secret
    real_transport = client is None
    if real_transport:
        client = CachedQlooClient(
            cache_dir or DEFAULT_CACHE_DIR, delay=delay, refresh=refresh
        )
        if not client.configured:
            raise ProbeConfigError(
                "QLOO_API_KEY is not set. Add a rotated key to backend/.env, "
                "restart the shell, then run this probe with --live."
            )
    else:
        delay = 0.0

    record_cache = TTLCache(ttl_seconds=3600)
    profile_cache = TTLCache(ttl_seconds=3600)
    calls = {"search": 0, "insights": 0}
    profile_cache_hits = 0
    usable_profiles = 0
    searches_succeeded = 0
    insights_succeeded = 0
    provider_errors: list[dict] = []
    records: list[dict] = []
    aborted = None
    warnings: list[str] = []

    for artist in dataset["artists"]:
        try:
            resolution, best = await _resolve_artist(
                client, artist, record_cache, secret, calls
            )
            if resolution["status"] != "api_error":
                searches_succeeded += 1
            else:
                provider_errors.append(
                    {
                        "artist_id": artist["id"],
                        "stage": "search",
                        "message": resolution.get("error"),
                    }
                )

            profile = None
            if (
                resolution["status"] == "matched"
                and best is not None
                and best.get("entity_id")
            ):
                profile, hit = await _load_profile(
                    client,
                    profile_cache,
                    record_cache,
                    best["entity_id"],
                    take,
                    secret,
                    calls,
                )
                if hit:
                    profile_cache_hits += 1
                else:
                    error_note = _insights_error(profile)
                    if error_note:
                        provider_errors.append(
                            {
                                "artist_id": artist["id"],
                                "stage": "insights",
                                "message": error_note,
                            }
                        )
                    else:
                        insights_succeeded += 1
                if not profile.get("missing"):
                    usable_profiles += 1
            records.append(_artist_record(artist, resolution, profile))
        except ProbeAborted as exc:
            aborted = {
                "stage": exc.stage,
                "artist_id": exc.artist_id,
                "reason": exc.message,
            }
            records.append(
                _artist_record(
                    artist,
                    {
                        "status": "api_error",
                        "raw_status": RAW_STATUS["api_error"],
                        "query": artist["query"],
                        "selected_entity_id": None,
                        "top_candidate_entity_id": None,
                        "ambiguous": False,
                        "candidate_count": 0,
                        "candidates": [],
                        "error": exc.message,
                    },
                    None,
                )
            )
            warnings.append(
                f"run aborted at {artist['name']}: the provider rejected the "
                "credentials or another stage failed fatally"
            )
            break

    main_insights_calls = calls["insights"]
    scoring_profiles = [_scoring_profile(record) for record in records]
    broad = sim.lineup_broad_tags(scoring_profiles)
    generic = sim.lineup_generic_tags(scoring_profiles)
    raw_pairs = sim.similarity_matrix(scoring_profiles)
    pairs = []
    for pair, (left, right) in zip(
        raw_pairs, itertools.combinations(records, 2)
    ):
        enriched = dict(pair)
        for side, record in (("artist_a", left), ("artist_b", right)):
            enriched[side] = {
                "id": record["id"],
                "name": record["name"],
                "scene": record["scene"],
                "resolution_status": record["resolution"]["status"],
                "profile_source": record["profile"]["source"],
            }
        pairs.append(enriched)

    scored = [pair for pair in pairs if not pair["missing"]]
    scored.sort(
        key=lambda pair: (
            -pair["taste_similarity"],
            -(pair["genre_similarity"] if pair["genre_similarity"] is not None else -1),
            pair["artist_a"]["name"],
            pair["artist_b"]["name"],
        )
    )
    for rank, pair in enumerate(scored, 1):
        pair["rank"] = rank

    sorted_scores = sorted(pair["taste_similarity"] for pair in scored)
    percentiles = {
        frozenset((pair["artist_a"]["id"], pair["artist_b"]["id"])): (
            percentile_values(sorted_scores, pair["taste_similarity"])
        )
        for pair in scored
    }
    thresholds = score_thresholds(sorted_scores)
    coverage = sim.coverage(scoring_profiles, pairs)

    selected = _select_depth_pairs(scored, depth_pairs)
    if depth_pairs and selected:
        depth = await _depth_sensitivity(
            client,
            selected,
            {record["id"]: record for record in records},
            {record["id"]: _scoring_profile(record) for record in records},
            profile_cache,
            record_cache,
            take,
            depth_take,
            broad,
            generic,
            secret,
            calls,
        )
    elif depth_pairs:
        depth = {
            "enabled": True,
            "take_deep": take,
            "take_shallow": depth_take,
            "material_delta_threshold": DEPTH_MATERIAL_DELTA,
            "pairs_requested": 0,
            "pairs_checked": 0,
            "rows": [],
            "note": "No scored pair was available for a depth comparison.",
        }
    else:
        depth = {
            "enabled": False,
            "note": "Depth sensitivity was disabled for this run.",
        }
    depth_insights_calls = calls["insights"] - main_insights_calls

    pairs_by_key = {
        frozenset((pair["artist_a"]["id"], pair["artist_b"]["id"])): pair
        for pair in pairs
    }
    analysis = {
        "resolution": _resolution_summary(records),
        "profile_coverage": _profile_coverage(records, coverage),
        "matrix": _matrix_summary(pairs, scored, thresholds),
        "confidence": _confidence_breakdown(scored),
        "shared_tag_frequency": _shared_tag_frequency(
            scoring_profiles, scored, generic, broad
        ),
        "generic_dominance": _generic_dominance(scored, generic),
        "highest_nonzero_pairs": [
            _pair_brief(pair, percentiles)
            for pair in scored
            if pair["taste_similarity"] > 0
        ][:5],
        "lowest_nonzero_pairs": [
            _pair_brief(pair, percentiles)
            for pair in list(
                reversed(
                    [pair for pair in scored if pair["taste_similarity"] > 0][-5:]
                )
            )
        ],
        "insufficient_coverage": _insufficient_coverage(records),
        "sanity_checks": _sanity_checks(
            dataset, records, pairs_by_key, thresholds, percentiles
        ),
        "diagnosis": _diagnosis(scored, coverage),
        "depth_sensitivity": depth,
    }

    generated = now or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    generated = generated.astimezone(timezone.utc)
    run_id = generated.strftime("%Y%m%dT%H%M%SZ")
    generated_at = generated.isoformat(timespec="seconds").replace("+00:00", "Z")

    is_evidence = bool(real_transport and usable_profiles and not aborted)
    if not real_transport:
        evidence_note = (
            "Injected client (test double): these numbers exercise the probe "
            "pipeline and are not evidence about Qloo or the artists."
        )
    elif aborted:
        evidence_note = (
            "The run aborted after a provider or credential failure; coverage is "
            "partial and no complete finding is supported."
        )
    elif not usable_profiles:
        evidence_note = (
            "No artist carried usable Qloo tags in this run; no similarity finding "
            "is supported, even if searches resolved entities."
        )
    else:
        evidence_note = (
            "Live Qloo responses, possibly served from the probe's disk cache on "
            "reruns. Scores are tag-affinity proxies, not audience overlap."
        )

    cache_stats = (
        dict(client.stats)
        if isinstance(client, CachedQlooClient)
        else {"enabled": False}
    )
    logical_requests = calls["search"] + calls["insights"]
    transport = {
        "kind": "live" if real_transport else "test-double",
        "client": type(client).__name__,
        "search_requests": calls["search"],
        "main_insights_requests": main_insights_calls,
        "depth_insights_requests": depth_insights_calls,
        "logical_requests": logical_requests,
        "searches_succeeded": searches_succeeded,
        "insights_succeeded": insights_succeeded,
        "profile_cache_hits": profile_cache_hits,
        "profiles_usable": usable_profiles,
        "cache": cache_stats,
    }
    request_parameters = {
        "search": {
            "method": "GET",
            "path": "/search",
            "query": "<artist name>",
            "types": "urn:entity:artist",
        },
        "insights": {
            "method": "GET",
            "path": "/v2/insights",
            "filter.type": "urn:tag",
            "signal.interests.entities": "<selected entity id>",
            "take": take,
        },
        "pagination": {
            "used": False,
            "reason": (
                "No pagination parameter is documented for /v2/insights and "
                "app.qloo.QlooClient implements none; no cursor, page or offset "
                "parameter was sent."
            ),
        },
        "take_depth": {
            "value": take,
            "production_default": PRODUCTION_TAKE,
            "largest_documented_accepted": MAX_TAKE,
            "documented_rejection": {
                "value": 100,
                "status": 400,
                "observed_on": "2026-10-23",
            },
            "source": (
                "README Qloo configuration notes; the endpoint accepted 30 and 50 "
                "on 2026-10-23 and rejected 100 with HTTP 400."
            ),
        },
        "depth_sensitivity": {
            "enabled": bool(depth_pairs),
            "take": depth_take,
            "pairs": depth_pairs,
        },
        "timeout_seconds": config.QLOO_TIMEOUT_SECONDS,
        "delay_seconds": delay,
        "sequential": True,
    }
    meta = {
        "name": "ClashDoctor live Qloo probe v2",
        "probe_version": PROBE_VERSION,
        "run_id": run_id,
        "mode": "live" if real_transport else "test-double",
        "generated_at": generated_at,
        "dataset": {
            "path": str(Path(dataset_path or DEFAULT_DATASET)),
            "sha256": dataset_digest(dataset_path),
            "artist_count": len(dataset["artists"]),
            "sanity_check_count": len(dataset["sanity_checks"]),
        },
        "qloo": {
            "base_url": getattr(client, "base_url", "synthetic"),
            "search_type": "urn:entity:artist",
        },
        "request_parameters": request_parameters,
        "scoring": {
            "engine": "app.similarity",
            "objective_method": sim.OBJECTIVE_METHOD,
            "weights": sim.CATEGORY_WEIGHTS,
            "methods": sim.METHODS,
            "confidence_rules": {
                "min_categories": sim.MIN_CATEGORIES_FOR_CONFIDENT_SCORE,
                "min_union_tags": sim.MIN_UNION_TAGS_FOR_CONFIDENT_SCORE,
                "min_shared_tags": sim.MIN_SHARED_TAGS_FOR_CONFIDENT_SCORE,
                "generic_lineup_share": sim.GENERIC_TAG_LINEUP_SHARE,
                "min_generic_artists": sim.MIN_GENERIC_TAG_ARTISTS,
                "min_profiles_for_generic": sim.MIN_PROFILES_FOR_GENERIC_TAGS,
            },
            "note": (
                "The probe reuses the shipped scorer and changes no similarity, "
                "confidence or canonicalization rule."
            ),
        },
        "transport": transport,
        "evidence": {
            "is_evidence": is_evidence,
            "note": evidence_note,
        },
        "aborted": aborted,
        "partial": bool(aborted),
        "warnings": warnings,
        "provider_errors": len(provider_errors),
    }
    return {
        "probe": meta,
        "observed": {
            "artists": records,
            "provider_errors": provider_errors,
        },
        "computed": {
            "pairs": pairs,
            "coverage": coverage,
            "analysis": analysis,
        },
        "limitations": LIMITATIONS,
    }


# --- CLI ---

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m probe.v2",
        description=(
            "Live Qloo probe for 30 fixed established artists. Resolves names, "
            "fetches take=50 profiles, scores every pair with the production "
            "pipeline, and writes timestamped evidence artifacts."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="required: call the real Qloo API (QLOO_API_KEY must be in backend/.env)",
    )
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET,
        help=f"probe dataset JSON (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help=f"artifact directory (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=None,
        help=f"raw-response cache (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--take", type=int, default=DEFAULT_TAKE,
        help=f"tags per insights call, 1-{MAX_TAKE} (default: {DEFAULT_TAKE})",
    )
    parser.add_argument(
        "--depth-take", type=int, default=DEFAULT_DEPTH_TAKE,
        help=f"shallow take for the depth subset (default: {DEFAULT_DEPTH_TAKE})",
    )
    parser.add_argument(
        "--depth-pairs", type=int, default=DEFAULT_DEPTH_PAIRS,
        help=f"pairs compared at both depths, 0 disables (default: {DEFAULT_DEPTH_PAIRS})",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"seconds between live requests (default: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="ignore the disk cache and fetch every response again",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not args.live:
        parser.error("--live is required; probe v2 has no mock mode")
    if not 1 <= args.take <= MAX_TAKE:
        parser.error(f"--take must be between 1 and {MAX_TAKE}")
    if args.depth_pairs < 0:
        parser.error("--depth-pairs must be >= 0")
    if args.depth_pairs and not 1 <= args.depth_take < args.take:
        parser.error("--depth-take must be between 1 and --take minus 1")
    if args.delay < 0:
        parser.error("--delay must be >= 0")


def _prepare_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _summary(report: dict, paths: dict) -> str:
    meta = report["probe"]
    observed = report["observed"]
    analysis = report["computed"]["analysis"]
    matrix = analysis["matrix"]
    resolution = analysis["resolution"]["counts"]
    coverage = analysis["profile_coverage"]
    depth = analysis["depth_sensitivity"]
    lines = [
        "ClashDoctor live Qloo probe v2",
        f"run: {meta['run_id']}",
        f"evidence: {'yes' if meta['evidence']['is_evidence'] else 'no'} "
        f"({meta['mode']})",
        "resolution: " + ", ".join(f"{key} {value}" for key, value in resolution.items()),
        "coverage: "
        f"{coverage['usable']}/{coverage['profiles_total']} artists with usable tags; "
        f"{coverage['genre_artists']} with genre",
        "matrix: "
        f"{matrix['pairs_scored']}/{matrix['pairs_total']} pairs scored "
        f"({matrix['pairs_missing']} excluded); "
        f"{matrix['zero_count']} zero ({matrix['zero_share']:.1%})",
        "distribution: "
        f"min {matrix['distribution']['min']}, q1 {matrix['distribution']['q1']}, "
        f"median {matrix['distribution']['median']}, "
        f"q3 {matrix['distribution']['q3']}, max {matrix['distribution']['max']}",
        "confidence: "
        f"{analysis['confidence']['sufficient_evidence']} sufficient, "
        f"{analysis['confidence']['low_confidence']} low, "
        f"{analysis['confidence']['genre_backed']} genre-backed",
        f"diagnosis: {analysis['diagnosis']['likely_cause']}",
    ]
    top = analysis["highest_nonzero_pairs"]
    if top:
        lines.append(
            "top nonzero pair: "
            f"{top[0]['pair'][0]} / {top[0]['pair'][1]} "
            f"taste {top[0]['taste_similarity']}"
        )
    if depth.get("enabled") and not depth.get("error"):
        lines.append(
            "depth: "
            f"{depth['pairs_checked']} pair(s) at take {depth['take_shallow']} vs "
            f"{depth['take_deep']}; material {depth.get('material_pairs', 0)}, "
            f"max |delta| {depth.get('max_abs_taste_delta')}"
        )
    cache = meta["transport"].get("cache") or {}
    if cache.get("enabled"):
        lines.append(
            "cache: "
            f"{cache['cache_hits']} hit(s), {cache['cache_misses']} miss(es), "
            f"{cache['network_attempts']} network attempt(s)"
        )
    if meta.get("aborted"):
        aborted = meta["aborted"]
        lines.append(
            f"ABORTED at {aborted['stage']} for {aborted['artist_id']}: "
            f"{aborted['reason']}"
        )
    lines.append("reports:")
    for kind, path in paths.items():
        lines.append(f"  {kind}: {path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _prepare_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    out_dir = args.out or DEFAULT_OUTPUT_ROOT
    try:
        report = asyncio.run(
            run_probe_v2(
                dataset_path=args.dataset,
                take=args.take,
                depth_take=args.depth_take,
                depth_pairs=args.depth_pairs,
                delay=args.delay,
                cache_dir=args.cache_dir,
                refresh=args.refresh,
            )
        )
    except ProbeDatasetError as exc:
        print(f"dataset error: {exc}", file=sys.stderr)
        return 1
    except ProbeConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    paths = write_v2_reports(report, out_dir)
    print(_summary(report, paths))
    if not report["probe"]["evidence"]["is_evidence"]:
        print(f"note: {report['probe']['evidence']['note']}")
    return 2 if report["probe"]["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
