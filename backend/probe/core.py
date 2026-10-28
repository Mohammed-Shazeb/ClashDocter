"""Probe orchestration: resolve artists, build profiles, score, diagnose, report.

Reuse map:
- resolution: `app.qloo.QlooClient.search_artists` + `select_best_match` (the
  same heuristic the product uses when it auto-confirms a match)
- profiles: `app.qloo.fetch_profile` (insights, search-tag fallback, missing)
- caching: `app.cache.TTLCache`, scoped to one run
- similarity/coverage: `app.similarity`, the exact engine behind the optimizer
"""
from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import math
import statistics
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app import config
from app import similarity as sim
from app.cache import TTLCache
from app.qloo import QlooClient, QlooError, canonical_genre_tag, fetch_profile, select_best_match

from .mock import MockQloo, load_mock_cases

PROBE_VERSION = 1
DEFAULT_DATASET = Path(__file__).resolve().parent / "dataset.json"
CATEGORIES = sim.CATEGORIES
LABELS = ("established", "emerging")

# Diagnostics thresholds. These are heuristics for manual review, not tests.
GENERIC_DF_THRESHOLD = 0.25
GENERIC_PAIR_SHARE = 0.5
ARTIST_GENERIC_SHARE = 0.6
SIMILAR_SUPPORTED_PERCENTILE = 80
SIMILAR_MIXED_PERCENTILE = 50
DIFFERENT_SUPPORTED_PERCENTILE = 20
DIFFERENT_MIXED_PERCENTILE = 50
ACROSS_GROUP_PERCENTILE = 90
ZERO_INFLATED_SHARE = 0.5
MIN_DISTINCT_SCORES_FOR_RANKING = 3

LIMITATIONS = [
    "The 50 artists are handpicked. Counts and percentiles describe this set only; "
    "nothing here is a statistical validation of ClashDoctor.",
    "Qloo tags are a proxy for taste affinity, not measured audience overlap, shared "
    "fans, ticket demand or attendance.",
    "Tag coverage is bounded by the /v2/insights take value; a thin profile can "
    "look dissimilar simply because it is shallow.",
    "Genre tags are normalized across Qloo tag namespaces by prefix only. Distinct "
    "labels such as folk and indie_folk remain distinct and are never merged.",
    "Ambiguous names are resolved with the production heuristic. A wrong pick is "
    "possible and is reported as ambiguous rather than silently trusted.",
    "This is one point in time: Qloo data can change between runs.",
    "When many pairs tie (often at 0.0), the midrank percentile is not an even "
    "spread. The report qualifies verdicts whenever at least half of scored pairs "
    "tie at zero or fewer than three distinct scores exist.",
    "'Sufficient evidence' uses production's low-confidence rule (at least two "
    "compared categories, six tags in the union, and at least two shared tags). It "
    "does not require genre on both sides, so read the genre-backed count alongside it.",
    "Mock mode generates synthetic tags from human genre descriptions. It tests the "
    "pipeline and calculations; it is not evidence about Qloo or the artists.",
    "Expected similar/different pairs are editorial judgments, not ground truth; "
    "their verdicts are descriptive sanity checks, not hypothesis tests.",
]


class DatasetError(ValueError):
    """The probe dataset is missing, unreadable or invalid."""


class ProbeConfigError(RuntimeError):
    """Live mode was requested without a configured Qloo client."""


class ProbeAborted(RuntimeError):
    """A fatal provider failure (bad key) stopped the run."""

    def __init__(self, message: str, stage: str, artist_id: str):
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.artist_id = artist_id


# --- dataset ---

def load_dataset(path: str | Path | None = None) -> dict:
    target = Path(path or DEFAULT_DATASET)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetError(f"cannot read dataset {target}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatasetError(f"dataset {target} is not valid JSON: {exc}") from exc
    errors = validate_dataset(data)
    if errors:
        raise DatasetError("dataset invalid:\n- " + "\n- ".join(errors))
    return data


def validate_dataset(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["top level must be a JSON object"]
    artists = data.get("artists")
    if not isinstance(artists, list) or not artists:
        return ["'artists' must be a non-empty list"]

    seen_ids: set[str] = set()
    for index, artist in enumerate(artists):
        where = f"artists[{index}]"
        if not isinstance(artist, dict):
            errors.append(f"{where} must be an object")
            continue
        artist_id = artist.get("id")
        if not isinstance(artist_id, str) or not artist_id:
            errors.append(f"{where} needs a string 'id'")
        elif artist_id in seen_ids:
            errors.append(f"duplicate artist id {artist_id!r}")
        else:
            seen_ids.add(artist_id)
        for field in ("name", "origin", "expected_group", "why_selected"):
            if not isinstance(artist.get(field), str) or not artist.get(field, "").strip():
                errors.append(f"{where} needs a non-empty {field!r}")
        if artist.get("label") not in LABELS:
            errors.append(f"{where} label must be one of {LABELS}")
        genres = artist.get("genres")
        if not isinstance(genres, list) or not genres or not all(
            isinstance(g, str) and g.strip() for g in genres
        ):
            errors.append(f"{where} needs a non-empty list of genre strings")

    seen_pairs: dict[frozenset, str] = {}
    for kind in ("expected_similar_pairs", "expected_different_pairs"):
        pairs = data.get(kind)
        if not isinstance(pairs, list):
            errors.append(f"{kind!r} must be a list")
            continue
        for index, pair in enumerate(pairs):
            where = f"{kind}[{index}]"
            if not isinstance(pair, dict):
                errors.append(f"{where} must be an object")
                continue
            a, b = pair.get("a"), pair.get("b")
            if a not in seen_ids or b not in seen_ids:
                errors.append(f"{where} references an unknown artist ({a!r}, {b!r})")
                continue
            if a == b:
                errors.append(f"{where} pairs an artist with itself")
            key = frozenset((a, b))
            if key in seen_pairs:
                errors.append(
                    f"{where} repeats pair {a}/{b} already in {seen_pairs[key]}"
                )
            else:
                seen_pairs[key] = kind
            if not isinstance(pair.get("rationale"), str) or not pair["rationale"].strip():
                errors.append(f"{where} needs a rationale")
    return errors


def dataset_warnings(data: dict) -> list[str]:
    warnings = []
    counts = Counter(artist["label"] for artist in data["artists"])
    if len(data["artists"]) != 50:
        warnings.append(
            f"dataset has {len(data['artists'])} artists; the shipped set has 50"
        )
    for label in LABELS:
        if counts.get(label, 0) == 0:
            warnings.append(f"dataset has no {label} artists")
    return warnings


def dataset_digest(path: str | Path | None = None) -> str:
    target = Path(path or DEFAULT_DATASET)
    return hashlib.sha256(target.read_bytes()).hexdigest()


# --- helpers ---

def redact(text: str | None, secret: str | None) -> str | None:
    if not text or not secret:
        return text
    return text.replace(secret, "[redacted]")


def is_auth_failure(message: str) -> bool:
    return "HTTP 401" in message or "rejected the API key" in message


def pair_key(pair: dict) -> frozenset:
    return frozenset((pair["artist_a"]["id"], pair["artist_b"]["id"]))


def percentile_values(sorted_scores: list[float], score: float) -> int:
    """Midrank percentile in 0-100. Ties share the midpoint of their band."""
    if not sorted_scores:
        return 0
    below = bisect_left(sorted_scores, score)
    equal = bisect_right(sorted_scores, score) - below
    return round(100 * (below + 0.5 * equal) / len(sorted_scores))


def percentile_value(sorted_scores: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile value: the smallest score in the top (1-fraction).

    Used for verdicts because ties should count: with many pairs at 0.0, only a
    threshold *value* lets a zero score be correctly called low.
    """
    if not sorted_scores:
        return None
    index = math.ceil(fraction * len(sorted_scores)) - 1
    return sorted_scores[min(max(index, 0), len(sorted_scores) - 1)]


def score_thresholds(sorted_scores: list[float]) -> dict[str, float | None]:
    return {
        "p80": percentile_value(sorted_scores, SIMILAR_SUPPORTED_PERCENTILE / 100),
        "p50": percentile_value(sorted_scores, 0.5),
        "p20": percentile_value(sorted_scores, DIFFERENT_SUPPORTED_PERCENTILE / 100),
    }


def similar_verdict(score: float | None, p80: float | None, p50: float | None) -> str:
    """Compare a score with the set's percentile values (ties count as met)."""
    if score is None:
        return "unscored"
    # A non-zero score is required so an all-zero set cannot "support" similarity.
    if score > 0 and p80 is not None and score >= p80:
        return "supported"
    if score > 0 and p50 is not None and score > p50:
        return "mixed"
    return "not_supported"


def different_verdict(score: float | None, p20: float | None, p50: float | None) -> str:
    """Compare a score with the set's percentile values (ties count as met)."""
    if score is None:
        return "unscored"
    # p20/p50 of 1.0 means the set is saturated at the top; it cannot show difference.
    if p20 is not None and p20 < 1 and score <= p20:
        return "supported"
    if p50 is not None and p50 < 1 and score < p50:
        return "mixed"
    return "not_supported"


def leave_one_out(pair: dict) -> dict[str, float]:
    """Blend recomputed without each compared category, weights renormalized."""
    signals = pair.get("signals") or []
    if len(signals) < 2 or pair.get("taste_similarity") is None:
        return {}
    scores = {}
    for skipped in signals:
        remaining = [s for s in signals if s["category"] != skipped["category"]]
        weight = sum(s["weight"] for s in remaining)
        if not weight:
            continue
        value = sum(s["weight"] * s["jaccard"] for s in remaining) / weight
        scores[skipped["category"]] = round(value, 4)
    return scores


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "p90": round(ordered[int(round(0.9 * (len(ordered) - 1)))], 4),
        "max": round(ordered[-1], 4),
    }


def _tag_count(tags: dict) -> int:
    return sum(len(v) for v in tags.values())


def _profile_tags(record: dict) -> dict:
    """Canonical sets for diagnostics; falls back for legacy/synthetic records."""
    section = record["profile"]
    return section.get("canonical_tags") or section["tags"]


# --- provider steps ---

async def _resolve_artist(
    client, artist: dict, cache: TTLCache, max_candidates: int, secret: str | None, calls: dict
) -> tuple[dict, dict | None]:
    query = artist["name"]
    calls["search"] += 1
    try:
        results = await client.search_artists(query, record_cache=cache)
    except QlooError as exc:
        message = redact(str(exc), secret) or "Qloo search failed"
        if is_auth_failure(message):
            raise ProbeAborted(message, "search", artist["id"]) from exc
        return (
            {
                "status": "error",
                "query": query,
                "selected_entity_id": None,
                "ambiguous": False,
                "candidate_count": 0,
                "candidates": [],
                "error": message,
            },
            None,
        )

    best, ambiguous = select_best_match(results, query)
    status = "no_match" if best is None else ("ambiguous" if ambiguous else "matched")
    candidates = []
    for item in results[:max_candidates]:
        properties = item.get("properties") or {}
        candidates.append(
            {
                "name": item.get("name"),
                "entity_id": item.get("entity_id"),
                "types": item.get("types") or [],
                "popularity": item.get("popularity"),
                "disambiguation": item.get("disambiguation"),
                "short_description": properties.get("short_description"),
            }
        )
    return (
        {
            "status": status,
            "query": query,
            "selected_entity_id": best.get("entity_id") if best else None,
            "ambiguous": bool(ambiguous),
            "candidate_count": len(results),
            "candidates": candidates,
            "error": None,
        },
        best,
    )


async def _load_profile(
    client,
    profile_cache: TTLCache,
    record_cache: TTLCache,
    entity_id: str,
    take: int | None,
    secret: str | None,
    calls: dict,
) -> tuple[dict, bool]:
    cached = profile_cache.get(entity_id)
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
    # An outage is not remembered as a missing profile, mirroring the API.
    if not profile.get("provider_failed"):
        profile_cache.set(entity_id, profile)
    return profile, False


def _profile_section(profile: dict | None, resolution: dict) -> dict:
    if profile is None:
        tags = {category: [] for category in CATEGORIES}
        status = resolution.get("status")
        if status == "ambiguous":
            source = "unconfirmed"
            reason = "Name matched only ambiguous candidates; a user must confirm an entity"
        elif status == "error":
            source = "unresolved"
            reason = resolution.get("error") or "Qloo search failed"
        elif status == "no_match":
            source = "unresolved"
            reason = "No Qloo artist entity selected"
        else:
            source = "unresolved"
            reason = "No Qloo entity selected"
        return {
            "source": source,
            "missing": True,
            "provider_failed": False,
            "note": f"{reason}; excluded from similarity.",
            "tags": tags,
            "canonical_tags": {category: [] for category in CATEGORIES},
            "tag_counts": {category: 0 for category in CATEGORIES},
            "raw_tag_counts": {category: 0 for category in CATEGORIES},
            "provenance": {category: None for category in CATEGORIES},
        }
    tags = {
        category: sorted(profile.get(f"{category}_tags") or [])
        for category in CATEGORIES
    }
    canonical_genre = sorted(
        profile.get("canonical_genre_tags")
        or {canonical_genre_tag(tag) for tag in tags["genre"]}
    )
    canonical_tags = {**tags, "genre": canonical_genre}
    source = profile.get("source")
    return {
        "source": source,
        "missing": bool(profile.get("missing")),
        "provider_failed": bool(profile.get("provider_failed")),
        "note": profile.get("note"),
        # Raw ids preserve provider provenance; canonical ids are what scoring uses.
        "tags": tags,
        "canonical_tags": canonical_tags,
        "tag_counts": {
            category: len(values) for category, values in canonical_tags.items()
        },
        "raw_tag_counts": {
            category: len(values) for category, values in tags.items()
        },
        "provenance": {
            category: (source if values else None)
            for category, values in canonical_tags.items()
        },
    }


def _artist_record(artist: dict, resolution: dict, profile: dict | None) -> dict:
    return {
        "id": artist["id"],
        "name": artist["name"],
        "label": artist["label"],
        "origin": artist["origin"],
        "genres": artist["genres"],
        "expected_group": artist["expected_group"],
        "why_selected": artist["why_selected"],
        "resolution": resolution,
        "profile": _profile_section(profile, resolution),
    }


def _scoring_profile(record: dict) -> dict:
    section = record["profile"]
    entity_id = (
        record["resolution"].get("selected_entity_id")
        if record["resolution"]["status"] == "matched"
        else f"unresolved:{record['id']}"
    )
    return {
        "entity_id": entity_id,
        "name": record["name"],
        "source": section["source"],
        "missing": section["missing"],
        "genre_tags": section["tags"]["genre"],
        "canonical_genre_tags": section["canonical_tags"]["genre"],
        "audience_tags": section["canonical_tags"]["audience"],
        "style_tags": section["canonical_tags"]["style"],
        "music_tags": section["canonical_tags"]["music"],
    }


def _enrich_pair(pair: dict, left: dict, right: dict) -> dict:
    enriched = dict(pair)
    for side, record in (("artist_a", left), ("artist_b", right)):
        enriched[side] = {
            "id": record["id"],
            "name": record["name"],
            "label": record["label"],
            "expected_group": record["expected_group"],
        }
    return enriched


# --- diagnostics ---

def _generic_diagnostics(records: list[dict], pairs: list[dict]) -> dict:
    with_data = [
        r for r in records if not r["profile"]["missing"] and _tag_count(_profile_tags(r))
    ]
    total = len(with_data)
    document_frequency = Counter()
    for record in with_data:
        for values in _profile_tags(record).values():
            document_frequency.update(set(values))

    generic_tags = {
        tag
        for tag, count in document_frequency.items()
        if total and count / total >= GENERIC_DF_THRESHOLD
    }
    top_tags = [
        {
            "tag": tag,
            "artists": count,
            "of": total,
            "document_frequency": round(count / total, 3) if total else 0.0,
        }
        for tag, count in sorted(
            document_frequency.items(), key=lambda item: (-item[1], item[0])
        )[:15]
    ]

    # A tag can be broad inside one set while staying under the overall
    # threshold, which hides label-specific inflation (for example a catch-all
    # regional genre tag on nearly every artist in that set).
    label_generic: dict[str, set[str]] = {}
    label_sections = []
    for label in LABELS:
        subset = [record for record in with_data if record["label"] == label]
        of = len(subset)
        label_df = Counter()
        for record in subset:
            for values in _profile_tags(record).values():
                label_df.update(set(values))
        label_generic[label] = {
            tag
            for tag, count in label_df.items()
            if of and count / of >= GENERIC_DF_THRESHOLD
        }
        label_sections.append(
            {
                "label": label,
                "profiles_with_data": of,
                "generic_tags": [
                    {
                        "tag": tag,
                        "artists": label_df[tag],
                        "of": of,
                        "document_frequency": round(label_df[tag] / of, 3),
                    }
                    for tag in sorted(
                        label_generic[label],
                        key=lambda tag: (-label_df[tag], tag),
                    )
                ],
            }
        )

    def tag_scopes(tag: str, labels: set[str]) -> list[str]:
        scopes = []
        if tag in generic_tags:
            scopes.append("overall")
        scopes.extend(sorted(label for label in labels if tag in label_generic[label]))
        return scopes

    artist_flags = []
    for record in with_data:
        own = set().union(*_profile_tags(record).values())
        own_generic = generic_tags | label_generic.get(record["label"], set())
        share = len(own & own_generic) / len(own) if own else 0.0
        if share >= ARTIST_GENERIC_SHARE:
            artist_flags.append(
                {
                    "artist_id": record["id"],
                    "name": record["name"],
                    "label": record["label"],
                    "tags_total": len(own),
                    "generic_tags": len(own & own_generic),
                    "generic_share": round(share, 3),
                }
            )
    artist_flags.sort(key=lambda row: (-row["generic_share"], row["name"]))

    pair_flags = []
    for pair in pairs:
        if pair["missing"]:
            continue
        shared = sorted(
            {tag for signal in pair["signals"] for tag in signal["shared_tags"]}
        )
        labels = {pair["artist_a"]["label"], pair["artist_b"]["label"]}
        generic_shared = [
            tag for tag in shared if tag_scopes(tag, labels)
        ]
        share = len(generic_shared) / len(shared) if shared else 0.0
        # Annotate every scored pair so the report and CSV can show whether a
        # score rests on specific tags even when the pair is not flagged.
        pair["probe_generic_share"] = round(share, 3)
        pair["probe_generic_shared_tags"] = generic_shared
        pair["probe_specific_shared_tags"] = [
            tag for tag in shared if tag not in generic_shared
        ]
        if not shared or share < GENERIC_PAIR_SHARE:
            continue
        document_frequency_rows = [
            {
                "tag": tag,
                "artists": document_frequency[tag],
                "of": total,
                "document_frequency": round(document_frequency[tag] / total, 3),
                "scopes": tag_scopes(tag, labels),
            }
            for tag in sorted(generic_shared, key=lambda tag: (-document_frequency[tag], tag))
        ]
        pair_flags.append(
            {
                "pair": [pair["artist_a"]["name"], pair["artist_b"]["name"]],
                "artist_ids": [pair["artist_a"]["id"], pair["artist_b"]["id"]],
                "labels": [pair["artist_a"]["label"], pair["artist_b"]["label"]],
                "taste_similarity": pair["taste_similarity"],
                "shared_tags": len(shared),
                "generic_shared_tags": len(generic_shared),
                "generic_share": round(share, 3),
                "shared_tag_detail": document_frequency_rows,
            }
        )
    pair_flags.sort(key=lambda row: (-row["generic_share"], -(row["taste_similarity"] or 0)))
    return {
        "method": (
            "A tag is 'generic in this probe set' when it appears on at least "
            f"{GENERIC_DF_THRESHOLD:.0%} of all artists with a profile, or on that "
            "share of artists within either label (a label-specific catch-all). Pair "
            f"flags inspect the highest-scoring pairs and mark those where at least "
            f"{GENERIC_PAIR_SHARE:.0%} of shared tags are generic; these are requests "
            "for manual review, not score adjustments."
        ),
        "threshold": GENERIC_DF_THRESHOLD,
        "profiles_with_data": total,
        "top_tags": top_tags,
        "by_label": label_sections,
        "pairs_flagged": pair_flags[:20],
        "pairs_flagged_total": len(pair_flags),
        "artists_dominated_by_generic_tags": artist_flags[:20],
    }


def _sensitivity(scored: list[dict]) -> dict:
    genre_deltas = [
        abs(pair["taste_similarity"] - pair["genre_similarity"])
        for pair in scored
        if pair["genre_similarity"] is not None
    ]
    by_category = {category: [] for category in CATEGORIES}
    per_pair = []
    for pair in scored:
        dropped = leave_one_out(pair)
        if not dropped:
            continue
        deltas = {
            category: round(abs(pair["taste_similarity"] - value), 4)
            for category, value in dropped.items()
        }
        for category, delta in deltas.items():
            by_category[category].append(delta)
        per_pair.append(
            {
                "pair": [pair["artist_a"]["name"], pair["artist_b"]["name"]],
                "taste_similarity": pair["taste_similarity"],
                "dropped_category_deltas": deltas,
                "max_delta": max(deltas.values()),
            }
        )
    per_pair.sort(key=lambda row: -row["max_delta"])
    return {
        "method": (
            "Genre-only delta is |taste_blend - genre_similarity|. Leave-one-out "
            "recomputes the blend without one compared category, renormalizing the "
            "remaining weights; a large delta means the missing-data policy matters "
            "for that pair."
        ),
        "genre_only_vs_blend": {
            **_stats(genre_deltas),
            "pairs_delta_above_0_1": sum(1 for value in genre_deltas if value > 0.1),
        },
        "leave_one_out": {
            category: _stats(values) for category, values in by_category.items()
        },
        "high_sensitivity_pairs": per_pair[:10],
    }


def _suspicious_pairs(
    scored: list[dict],
    percentiles: dict[frozenset, int],
    expected_similar: set[frozenset],
    expected_different: set[frozenset],
    generic_flags: list[dict],
) -> list[dict]:
    flagged = []

    def add(kind: str, pair: dict, reason: str):
        flagged.append(
            {
                "kind": kind,
                "pair": [pair["artist_a"]["name"], pair["artist_b"]["name"]],
                "artist_ids": [pair["artist_a"]["id"], pair["artist_b"]["id"]],
                "labels": [pair["artist_a"]["label"], pair["artist_b"]["label"]],
                "expected_groups": [
                    pair["artist_a"]["expected_group"],
                    pair["artist_b"]["expected_group"],
                ],
                "taste_similarity": pair["taste_similarity"],
                "percentile": percentiles.get(pair_key(pair)),
                "low_confidence": pair["low_confidence"],
                "reason": reason,
            }
        )

    for pair in scored:
        key = pair_key(pair)
        percentile = percentiles.get(key)
        if percentile is None:
            continue
        if key in expected_similar and percentile < SIMILAR_MIXED_PERCENTILE:
            add(
                "expected_similar_scored_low",
                pair,
                "Editorially similar pair lands below the median of this set; the tags "
                "returned may be too thin or too different from the human description.",
            )
        if key in expected_different and percentile > SIMILAR_SUPPORTED_PERCENTILE:
            add(
                "expected_different_scored_high",
                pair,
                "Editorially different pair lands in the top fifth; check for generic "
                "tag inflation or an ambiguous resolution.",
            )
        if (
            percentile >= ACROSS_GROUP_PERCENTILE
            and key not in expected_similar
            and key not in expected_different
            and pair["artist_a"]["expected_group"] != pair["artist_b"]["expected_group"]
        ):
            add(
                "high_score_across_expected_groups",
                pair,
                "High score across groups that were expected to differ; inspect the "
                "shared tags before trusting the affinity.",
            )
        if pair["low_confidence"] and percentile >= SIMILAR_SUPPORTED_PERCENTILE:
            add(
                "thin_evidence_high_score",
                pair,
                "Score rests on thin evidence (one category or very few tags) yet "
                "ranks near the top; do not treat it as a strong signal.",
            )
    for flag in generic_flags:
        flagged.append(
            {
                "kind": "generic_tag_driven",
                "pair": flag["pair"],
                "artist_ids": flag["artist_ids"],
                "labels": flag.get("labels"),
                "expected_groups": [None, None],
                "taste_similarity": flag["taste_similarity"],
                "percentile": percentiles.get(frozenset(flag["artist_ids"])),
                "low_confidence": None,
                "reason": (
                    f"{flag['generic_shared_tags']} of {flag['shared_tags']} shared tags "
                    "are generic in this set; the pair may be inflated by broad vocabulary."
                ),
            }
        )
    seen: set[tuple] = set()
    unique = []
    for row in flagged:
        key = (row["kind"], tuple(row["artist_ids"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:40]


def _missing_or_sparse(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        section = record["profile"]
        status = record["resolution"]["status"]
        counts = section["tag_counts"]
        categories = sum(1 for value in counts.values() if value)
        total = sum(counts.values())
        if section["missing"]:
            if status == "ambiguous":
                kind = "unconfirmed"
                reason = (
                    "Ambiguous name with no user-confirmed entity; candidates are listed "
                    "above but none was scored"
                )
            else:
                kind = "unresolved" if status in ("error", "no_match") else "missing"
                reason = section["note"] or record["resolution"].get("error") or "no usable tags"
        elif categories < 2 or total < 3:
            kind = "sparse"
            reason = (
                f"{categories} categor{'y' if categories == 1 else 'ies'}, {total} tag(s); "
                "scores involving this artist are low-confidence"
            )
        else:
            continue
        rows.append(
            {
                "artist_id": record["id"],
                "name": record["name"],
                "label": record["label"],
                "kind": kind,
                "resolution_status": status,
                "tag_counts": counts,
                "reason": reason,
            }
        )
    return rows


# --- run ---

async def run_probe(
    *,
    mode: str = "mock",
    dataset_path: str | Path | None = None,
    client=None,
    delay: float = 0.0,
    take: int | None = None,
    top_pairs: int = 20,
    max_candidates: int = 5,
    secret: str | None = None,
) -> dict:
    if mode not in ("mock", "live"):
        raise ValueError("mode must be 'mock' or 'live'")
    path = Path(dataset_path or DEFAULT_DATASET)
    dataset = load_dataset(path)
    warnings = dataset_warnings(dataset)
    secret = config.QLOO_API_KEY if secret is None else secret

    if mode == "mock":
        client = client or MockQloo(dataset, load_mock_cases())
    else:
        client = client or QlooClient()
        if not getattr(client, "configured", False):
            raise ProbeConfigError(
                "QLOO_API_KEY is not set. Add a rotated key to backend/.env, restart, "
                "then run the probe with --live. Mock mode needs no key."
            )

    effective_take = config.QLOO_INSIGHTS_TAKE if take is None else take
    record_cache = TTLCache(ttl_seconds=3600)
    profile_cache = TTLCache(ttl_seconds=3600)
    calls = {"search": 0, "insights": 0}
    cache_stats = {"profile_hits": 0, "profiles_fetched": 0}
    successful_searches = 0
    successful_insights = 0
    usable_profiles = 0
    records: list[dict] = []
    provider_errors: list[dict] = []
    aborted = None

    for index, artist in enumerate(dataset["artists"]):
        if delay and index:
            await asyncio.sleep(delay)
        try:
            resolution, best = await _resolve_artist(
                client, artist, record_cache, max_candidates, secret, calls
            )
            if resolution["status"] != "error":
                successful_searches += 1
            else:
                provider_errors.append(
                    {
                        "artist_id": artist["id"],
                        "stage": "search",
                        "message": resolution["error"],
                    }
                )

            profile = None
            # Only a confirmed match may be scored: an unconfirmed pick could attach
            # another artist's catalogue, so ambiguous names stay missing data.
            if (
                resolution["status"] == "matched"
                and best is not None
                and best.get("entity_id")
            ):
                entity_id = best["entity_id"]
                profile, hit = await _load_profile(
                    client, profile_cache, record_cache, entity_id, take, secret, calls
                )
                if hit:
                    cache_stats["profile_hits"] += 1
                else:
                    cache_stats["profiles_fetched"] += 1
                    if not profile.get("provider_failed"):
                        successful_insights += 1
                if profile.get("provider_failed"):
                    provider_errors.append(
                        {
                            "artist_id": artist["id"],
                            "stage": "insights",
                            "message": profile.get("note"),
                        }
                    )
                # Search-tag fallback still counts as observed Qloo data.
                if not profile.get("missing"):
                    usable_profiles += 1
            records.append(_artist_record(artist, resolution, profile))
        except ProbeAborted as exc:
            aborted = {
                "stage": exc.stage,
                "artist_id": artist["id"],
                "reason": exc.message,
            }
            records.append(
                _artist_record(
                    artist,
                    {
                        "status": "error",
                        "query": artist["name"],
                        "selected_entity_id": None,
                        "ambiguous": False,
                        "candidate_count": 0,
                        "candidates": [],
                        "error": exc.message,
                    },
                    None,
                )
            )
            warnings.append(
                f"run aborted at {artist['name']}: the provider rejected the credentials"
            )
            break

    scoring_profiles = [_scoring_profile(record) for record in records]
    raw_pairs = sim.similarity_matrix(scoring_profiles)
    pairs = [
        _enrich_pair(pair, left, right)
        for pair, (left, right) in zip(raw_pairs, itertools.combinations(records, 2))
    ]

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
    missing_pairs = [pair for pair in pairs if pair["missing"]]
    missing_pairs.sort(
        key=lambda pair: (pair["artist_a"]["name"], pair["artist_b"]["name"])
    )
    ranked = scored + missing_pairs

    sorted_scores = sorted(pair["taste_similarity"] for pair in scored)
    percentiles = {
        pair_key(pair): percentile_values(sorted_scores, pair["taste_similarity"])
        for pair in scored
    }
    thresholds = score_thresholds(sorted_scores)
    zero_count = sum(1 for score in sorted_scores if score == 0.0)
    zero_share = zero_count / len(sorted_scores) if sorted_scores else 0.0
    distinct_scores = len(set(sorted_scores))
    verdicts_informative = bool(
        sorted_scores
        and zero_share < ZERO_INFLATED_SHARE
        and distinct_scores >= MIN_DISTINCT_SCORES_FOR_RANKING
    )
    if not sorted_scores:
        verdict_note = "No scored pairs; no verdict can be computed."
    elif verdicts_informative:
        verdict_note = (
            f"Ranked verdicts are informative: {zero_share:.1%} of scored pairs tie at "
            f"0.000 and there are {distinct_scores} distinct score values."
        )
    else:
        verdict_note = (
            f"Percentile verdicts are qualified: {zero_share:.1%} of {len(sorted_scores)} "
            f"scored pairs tie at 0.000 ({distinct_scores} distinct score value(s)). "
            "Read every verdict as a zero-vs-nonzero check, not a graded ranking."
        )

    def add_evidence_counts(target: dict, pair_list: list[dict]) -> None:
        scored_pairs = [pair for pair in pair_list if not pair["missing"]]
        sufficient = [pair for pair in scored_pairs if not pair["low_confidence"]]
        target["pairs_with_sufficient_evidence"] = len(sufficient)
        target["pairs_with_genre_both"] = sum(
            1 for pair in scored_pairs if pair["genre_similarity"] is not None
        )
        target["pairs_sufficient_with_genre"] = sum(
            1 for pair in sufficient if pair["genre_similarity"] is not None
        )

    coverage = sim.coverage(scoring_profiles, pairs)
    add_evidence_counts(coverage, pairs)
    by_label = {}
    for label in LABELS:
        label_records = [record for record in records if record["label"] == label]
        label_profiles = [_scoring_profile(record) for record in label_records]
        label_pairs = [
            pair
            for pair in pairs
            if pair["artist_a"]["label"] == label and pair["artist_b"]["label"] == label
        ]
        by_label[label] = sim.coverage(label_profiles, label_pairs)
        add_evidence_counts(by_label[label], label_pairs)
    cross_pairs = [
        pair
        for pair in pairs
        if pair["artist_a"]["label"] != pair["artist_b"]["label"]
    ]
    cross_label = sim.coverage(scoring_profiles, cross_pairs)
    cross_label["pair_scope"] = "cross-label pairs only"
    add_evidence_counts(cross_label, cross_pairs)

    expected_similar_keys = {
        frozenset((entry["a"], entry["b"]))
        for entry in dataset["expected_similar_pairs"]
    }
    expected_different_keys = {
        frozenset((entry["a"], entry["b"]))
        for entry in dataset["expected_different_pairs"]
    }
    pair_by_key = {pair_key(pair): pair for pair in pairs}

    def expected_rows(entries: list[dict], checker) -> list[dict]:
        rows = []
        for entry in entries:
            key = frozenset((entry["a"], entry["b"]))
            pair = pair_by_key.get(key)
            percentile = percentiles.get(key)
            score = pair["taste_similarity"] if pair else None
            rows.append(
                {
                    "a": entry["a"],
                    "b": entry["b"],
                    "names": [pair["artist_a"]["name"], pair["artist_b"]["name"]] if pair else None,
                    "labels": (
                        [pair["artist_a"]["label"], pair["artist_b"]["label"]] if pair else None
                    ),
                    "rationale": entry["rationale"],
                    "confidence": entry.get("confidence"),
                    "taste_similarity": score,
                    "genre_similarity": pair["genre_similarity"] if pair else None,
                    "percentile": percentile,
                    "verdict": checker(score),
                    "verdict_basis": (
                        "unscored"
                        if score is None
                        else ("percentile" if verdicts_informative else "zero-vs-nonzero")
                    ),
                    "percentile_informative": verdicts_informative,
                    "missing_reason": pair["missing_reason"] if pair and pair["missing"] else None,
                    "low_confidence": pair["low_confidence"] if pair else None,
                    "genre_backed": pair["genre_backed"] if pair else None,
                    "shared_tag_count": pair["shared_tag_count"] if pair else None,
                    "probe_generic_share": pair.get("probe_generic_share") if pair else None,
                }
            )
        return rows

    expected_similar = expected_rows(
        dataset["expected_similar_pairs"],
        lambda score: similar_verdict(score, thresholds["p80"], thresholds["p50"]),
    )
    expected_different = expected_rows(
        dataset["expected_different_pairs"],
        lambda score: different_verdict(score, thresholds["p20"], thresholds["p50"]),
    )

    generic = _generic_diagnostics(records, scored)
    sensitivity = _sensitivity(scored)
    suspicious = _suspicious_pairs(
        scored,
        percentiles,
        expected_similar_keys,
        expected_different_keys,
        generic["pairs_flagged"],
    )
    missing_or_sparse = _missing_or_sparse(records)

    live = mode == "live"
    transport = {
        "kind": "mock" if mode == "mock" else "live",
        "search_requests_attempted": calls["search"],
        "insights_requests_attempted": calls["insights"],
        "requests_attempted": (calls["search"] + calls["insights"]) if live else 0,
        "searches_succeeded": successful_searches if live else 0,
        "insights_succeeded": successful_insights if live else 0,
        "live_requests_succeeded": (
            (successful_searches + successful_insights) if live else 0
        ),
        "profiles_with_usable_tags": usable_profiles,
        "names_unconfirmed": sum(
            1 for record in records if record["resolution"]["status"] == "ambiguous"
        ),
        "mock_calls": 0 if live else sum(calls.values()),
    }
    is_evidence = bool(live and usable_profiles and not aborted)
    if not live:
        evidence_note = (
            "Synthetic mock fixtures: these tags, scores and diagnostics test the probe "
            "pipeline and must not be cited as findings about Qloo or the artists."
        )
    elif aborted:
        evidence_note = (
            "The run aborted after a provider or credential failure; coverage is partial "
            "and no complete similarity finding is supported."
        )
    elif not usable_profiles:
        evidence_note = (
            "No artist carried usable Qloo tags in this run; no similarity finding is "
            "supported, even if searches returned entities."
        )
    else:
        evidence_note = (
            "Scores are computed from Qloo tag responses observed in this run. They are "
            "proxies for taste affinity, not audience overlap or attendance."
        )
    evidence = {
        "is_evidence": is_evidence,
        "live_requests_succeeded": transport["live_requests_succeeded"],
        "note": evidence_note,
    }
    meta = {
        "name": "ClashDoctor Qloo coverage & taste-signal probe",
        "probe_version": PROBE_VERSION,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "dataset": {
            "path": str(path),
            "sha256": dataset_digest(path),
            "artist_count": len(dataset["artists"]),
            "label_counts": dict(Counter(artist["label"] for artist in dataset["artists"])),
        },
        "qloo": {
            "base_url": getattr(client, "base_url", "synthetic"),
            "search_type": "urn:entity:artist",
            "search_type_source": "app.qloo.QlooClient.search_artists",
            "insights_take": effective_take,
            "requests_sequential": True,
            "delay_seconds": delay,
        },
        "calls": calls,
        "cache": {**cache_stats, "scope": "single run"},
        "transport": transport,
        "evidence": evidence,
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
            "methods": {
                **sim.METHODS,
                "category_weights": sim.CATEGORY_WEIGHTS,
                "confidence": (
                    "low_confidence when fewer than 2 categories are compared, the "
                    f"union of both tag sets is under {sim.MIN_UNION_TAGS_FOR_CONFIDENT_SCORE} "
                    f"tags, fewer than {sim.MIN_SHARED_TAGS_FOR_CONFIDENT_SCORE} tags are "
                    "shared, or every shared tag is generic in this lineup (a tag on at "
                    f"least {sim.GENERIC_TAG_LINEUP_SHARE:.0%} of tagged profiles, with at "
                    f"least {sim.MIN_GENERIC_TAG_ARTISTS} carriers and "
                    f"{sim.MIN_PROFILES_FOR_GENERIC_TAGS} tagged profiles)"
                ),
                "percentile": (
                    "midrank over scored pairs in this dataset: 100*(below + ties/2)/n"
                ),
                "verdict_reliability": (
                    "Verdicts are qualified when at least "
                    f"{ZERO_INFLATED_SHARE:.0%} of scored pairs tie at 0.000 or fewer "
                    f"than {MIN_DISTINCT_SCORES_FOR_RANKING} distinct scores exist; in "
                    "that case they compare zero with nonzero, not a graded ranking."
                ),
                "verdict_thresholds": (
                    "nearest-rank percentile values of the scored pairs: p20/p50/p80. "
                    "Verdicts compare the score with these values so ties at the "
                    "threshold count as meeting it."
                ),
                "similar_verdicts": (
                    f"supported when score >= p{SIMILAR_SUPPORTED_PERCENTILE} value, "
                    "mixed when above the p50 value, else not_supported"
                ),
                "different_verdicts": (
                    f"supported when score <= p{DIFFERENT_SUPPORTED_PERCENTILE} value, "
                    "mixed when below the p50 value, else not_supported"
                ),
            },
            "coverage": coverage,
            "coverage_by_label": by_label,
            "coverage_cross_label": cross_label,
            "matrix_summary": {
                "pairs_total": len(pairs),
                "pairs_scored": len(scored),
                "pairs_missing": len(missing_pairs),
                "pairs_low_confidence": sum(1 for pair in scored if pair["low_confidence"]),
                "pairs_with_sufficient_evidence": sum(
                    1 for pair in scored if not pair["low_confidence"]
                ),
                "pairs_with_genre_both": sum(
                    1 for pair in scored if pair["genre_similarity"] is not None
                ),
                "pairs_sufficient_with_genre": sum(
                    1
                    for pair in scored
                    if not pair["low_confidence"] and pair["genre_similarity"] is not None
                ),
                "score_distribution": _stats([pair["taste_similarity"] for pair in scored]),
                "score_thresholds": thresholds,
                "zero_low_share": round(zero_share, 4),
                "distinct_scores": distinct_scores,
                "verdicts_informative": verdicts_informative,
                "verdict_note": verdict_note,
                "top_score": scored[0]["taste_similarity"] if scored else None,
            },
            "top_pairs": scored[:top_pairs],
            "ranked_pairs": ranked,
            "expected_similar_checks": expected_similar,
            "expected_different_checks": expected_different,
            "generic_tags": generic,
            "sensitivity": sensitivity,
            "suspicious_pairs": suspicious,
            "missing_or_sparse": missing_or_sparse,
        },
        "human_judgments": {
            "note": dataset.get("human_judgment_note"),
            "label_definitions": dataset.get("label_definitions"),
            "expected_groups": {
                group: sorted(
                    artist["name"]
                    for artist in dataset["artists"]
                    if artist["expected_group"] == group
                )
                for group in sorted({a["expected_group"] for a in dataset["artists"]})
            },
            "expected_similar_pairs": dataset["expected_similar_pairs"],
            "expected_different_pairs": dataset["expected_different_pairs"],
        },
        "limitations": LIMITATIONS,
    }


__all__ = [
    "DatasetError",
    "ProbeAborted",
    "ProbeConfigError",
    "dataset_digest",
    "dataset_warnings",
    "different_verdict",
    "is_auth_failure",
    "leave_one_out",
    "load_dataset",
    "pair_key",
    "percentile_value",
    "percentile_values",
    "redact",
    "run_probe",
    "similar_verdict",
    "validate_dataset",
]
