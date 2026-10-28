"""Similarity scoring between artist taste profiles.

Primary metric ("taste blend"): the weighted average of per-category Jaccard
scores, computed only over the tag categories BOTH artists actually have. A
category present on one side only is skipped and its weight is renormalized
over the categories that remain, so absent data never registers as
disagreement and an artist is never penalised for a dimension Qloo did not
return for it.

Two reference scores are reported unchanged so the blend stays auditable:
- genre_similarity:    Jaccard over music-genre tags only (baseline)
- combined_similarity: Jaccard over every tag both artists carry, all categories pooled

Weights (documented, not fitted): genre .55, audience .20, style .15,
other-music .10. Genre dominates because it is the only category Qloo returns
for most artists; the rest refine it where they exist.

All scores are 0-1 estimates of taste affinity from Qloo tags. They are not
verified audience overlap, shared-fan percentages, or attendance forecasts.
A pair with no comparable category is reported as missing, never as zero.

Evidence checks never change the score. A pair's positive score is marked
low-confidence when its support is thin or when every shared tag is generic in
this lineup. Generic is lineup-local: a tag carried by at least a quarter of the
tagged acts (minimum 3 artists and 6 tagged acts) identifies a broad category,
not a specific affinity. The stricter "broad" annotation (at least half the
lineup) and its share are still reported alongside it.
"""
import logging
import math
from collections import Counter

logger = logging.getLogger("clashdoctor.similarity")

CATEGORIES = ("genre", "audience", "style", "music")
CATEGORY_WEIGHTS = {"genre": 0.55, "audience": 0.20, "style": 0.15, "music": 0.10}
CATEGORY_LABELS = {
    "genre": "music genre",
    "audience": "audience",
    "style": "style",
    "music": "other music",
}

# A blend built from one category, or from very few tags, is arithmetically
# valid but thin evidence; the UI marks it instead of hiding it.
MIN_CATEGORIES_FOR_CONFIDENT_SCORE = 2
MIN_UNION_TAGS_FOR_CONFIDENT_SCORE = 6
# A positive score from one shared tag is not corroborated affinity, even when
# the two profiles have many unshared tags in other categories.
MIN_SHARED_TAGS_FOR_CONFIDENT_SCORE = 2
# "Broad" and "generic" are judged within the current lineup, never against a
# fitted corpus. Six tagged profiles is the smallest set where a majority (or a
# quarter with at least three carriers) is meaningful.
MIN_PROFILES_FOR_BROAD_TAGS = 6
BROAD_TAG_LINEUP_SHARE = 0.5
MIN_PROFILES_FOR_GENERIC_TAGS = 6
GENERIC_TAG_LINEUP_SHARE = 0.25
MIN_GENERIC_TAG_ARTISTS = 3

METHODS = {
    "taste_blend": (
        "Estimated taste similarity: weighted average of per-category Jaccard scores "
        "over genre .55 / audience .20 / style .15 / other music .10, renormalized "
        "across only the categories both artists have."
    ),
    "genre": "Baseline: Jaccard over music-genre tags only.",
    "combined": "Reference: Jaccard over every tag both artists carry, all categories pooled.",
    "evidence": (
        "Evidence checks never change the score. A positive score is low-confidence "
        "when fewer than 2 categories are compared, fewer than 6 tags are available "
        "across both artists, fewer than 2 tags are shared, or every shared tag is "
        "generic in this lineup. A tag is generic when at least a quarter of the "
        "tagged profiles carry it, with at least 3 carriers and 6 tagged profiles; "
        "generic_share is the share of a pair's shared tags that are generic. A tag "
        "is broad, a stricter annotation, when at least half of the tagged profiles "
        "carry it; broad_share reports that share separately."
    ),
}

OBJECTIVE_METHOD = "taste_blend"


def jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _round(score: float | None, digits: int = 4) -> float | None:
    return None if score is None else round(score, digits)


def _tags(profile: dict, key: str) -> set:
    return set(profile.get(key) or [])


def category_tags(profile: dict, category: str) -> set:
    if category == "genre":
        canonical = profile.get("canonical_genre_tags")
        if canonical:
            return set(canonical)
    return _tags(profile, f"{category}_tags")


def all_tags(profile: dict) -> set:
    return set().union(*(category_tags(profile, c) for c in CATEGORIES))


def lineup_broad_tags(profiles: list[dict]) -> set:
    """Tags carried by at least half of the tagged profiles in this lineup.

    This is a lineup-local, explainable breadth check, not a tuned model. It
    returns nothing for lineups younger than the documented minimum so a
    two-act lineup never labels its only shared genre as broad.
    """
    tagged = [profile for profile in profiles if all_tags(profile)]
    if len(tagged) < MIN_PROFILES_FOR_BROAD_TAGS:
        return set()
    counts = Counter(tag for profile in tagged for tag in all_tags(profile))
    threshold = max(3, math.ceil(len(tagged) * BROAD_TAG_LINEUP_SHARE))
    return {tag for tag, count in counts.items() if count >= threshold}


def tag_counts(profile: dict) -> dict:
    """Tags per category for one profile — the evidence behind its scores."""
    return {c: len(category_tags(profile, c)) for c in CATEGORIES}


def lineup_generic_tags(profiles: list[dict]) -> set:
    """Tags carried by at least a quarter of the tagged profiles in this lineup.

    A generic tag marks a broad category (electronic, popular_music, a regional
    catch-all) rather than a specific affinity. The rule is lineup-local and
    explainable, not fitted: at least 3 artists must carry the tag and at least
    6 profiles must have data, so a small lineup never labels its only shared
    genre generic. This never changes a similarity score.
    """
    tagged = [profile for profile in profiles if all_tags(profile)]
    if len(tagged) < MIN_PROFILES_FOR_GENERIC_TAGS:
        return set()
    counts = Counter(tag for profile in tagged for tag in all_tags(profile))
    threshold = max(
        MIN_GENERIC_TAG_ARTISTS, math.ceil(len(tagged) * GENERIC_TAG_LINEUP_SHARE)
    )
    return {tag for tag, count in counts.items() if count >= threshold}


def pair_similarity(
    profile_a: dict,
    profile_b: dict,
    broad_tags: set | None = None,
    generic_tags: set | None = None,
) -> dict:
    """Similarity between two profiles; None means 'no data to compare'.

    ``broad_tags`` and ``generic_tags`` are optional lineup context used only
    for evidence annotations; they never change the score. When only
    ``broad_tags`` is supplied, broad tags are treated as the best available
    generic evidence.
    """
    genre_a = category_tags(profile_a, "genre")
    genre_b = category_tags(profile_b, "genre")
    tags_a = all_tags(profile_a)
    tags_b = all_tags(profile_b)

    genre_score = jaccard(genre_a, genre_b) if genre_a and genre_b else None
    combined_score = jaccard(tags_a, tags_b) if tags_a and tags_b else None

    signals = []
    skipped = []
    union_size = 0
    for category in CATEGORIES:
        ca = category_tags(profile_a, category)
        cb = category_tags(profile_b, category)
        if ca and cb:
            shared = ca & cb
            cat_union = ca | cb
            union_size += len(cat_union)
            signals.append(
                {
                    "category": category,
                    "label": CATEGORY_LABELS[category],
                    "weight": CATEGORY_WEIGHTS[category],
                    "jaccard": _round(jaccard(ca, cb)),
                    "shared_count": len(shared),
                    "union_count": len(cat_union),
                    "shared_tags": sorted(shared),
                }
            )
        elif ca or cb:
            holder = profile_a if ca else profile_b
            other = profile_b if ca else profile_a
            skipped.append(
                {
                    "category": category,
                    "label": CATEGORY_LABELS[category],
                    "reason": (
                        f"only {holder.get('name') or holder['entity_id']} has "
                        f"{CATEGORY_LABELS[category]} tags"
                    ),
                }
            )

    total_weight = sum(s["weight"] for s in signals)
    taste_score = None
    if total_weight:
        taste_score = sum(s["weight"] * s["jaccard"] for s in signals) / total_weight
        for signal in signals:
            signal["normalized_weight"] = _round(signal["weight"] / total_weight)
            signal["contribution"] = _round(
                signal["jaccard"] * signal["weight"] / total_weight
            )

    missing = taste_score is None
    reasons = []
    missing_kind = None
    if missing:
        empty_sides = 0
        for entity_id, profile in (
            (profile_a["entity_id"], profile_a),
            (profile_b["entity_id"], profile_b),
        ):
            if profile.get("missing"):
                reasons.append(f"{entity_id}: missing taste profile")
                empty_sides += 1
            elif not all_tags(profile):
                reasons.append(f"{entity_id}: no usable tags")
                empty_sides += 1
        # A pair can also be uncomparable with two perfectly good profiles that
        # simply carry tags in different dimensions.
        missing_kind = "profile_data" if empty_sides else "disjoint_categories"
        if not reasons:
            reasons.append(
                "no tag category is available for both artists "
                "(each has tags only where the other has none)"
            )
    elif genre_score is None:
        reasons.append("music-genre tags unavailable for at least one artist")

    shared_tags = sorted({tag for signal in signals for tag in signal["shared_tags"]})
    shared_tag_count = len(shared_tags)
    broad = set(broad_tags or ())
    # A broad tag is also generic, so callers that only pass broad context still
    # get a conservative generic classification.
    generic = set(generic_tags if generic_tags is not None else broad)
    shared_broad = [tag for tag in shared_tags if tag in broad]
    shared_generic = [tag for tag in shared_tags if tag in generic]
    shared_specific = [tag for tag in shared_tags if tag not in generic]
    broad_share = len(shared_broad) / shared_tag_count if shared_tag_count else 0.0
    generic_share = len(shared_generic) / shared_tag_count if shared_tag_count else 0.0
    genre_backed = genre_score is not None
    single_shared_tag = (
        taste_score is not None
        and taste_score > 0
        and shared_tag_count < MIN_SHARED_TAGS_FOR_CONFIDENT_SCORE
    )
    all_shared_generic = (
        taste_score is not None
        and shared_tag_count > 0
        and len(shared_generic) == shared_tag_count
    )

    low_confidence = (
        not missing
        and (
            len(signals) < MIN_CATEGORIES_FOR_CONFIDENT_SCORE
            or union_size < MIN_UNION_TAGS_FOR_CONFIDENT_SCORE
            or single_shared_tag
            or all_shared_generic
        )
    )
    confidence_note = None
    if low_confidence:
        if len(signals) < MIN_CATEGORIES_FOR_CONFIDENT_SCORE:
            confidence_note = (
                f"compared on {len(signals)} signal only "
                f"({signals[0]['label']}) — thin evidence"
            )
        elif union_size < MIN_UNION_TAGS_FOR_CONFIDENT_SCORE:
            confidence_note = (
                f"only {union_size} tag(s) available across both artists — thin evidence"
            )
        elif single_shared_tag:
            if shared_generic:
                confidence_note = (
                    "positive score rests on a single shared tag that is generic in "
                    "this lineup — one generic tag cannot corroborate affinity"
                )
            else:
                confidence_note = (
                    "positive score rests on a single shared tag — one tag cannot "
                    "corroborate affinity"
                )
        else:
            confidence_note = (
                f"all {shared_tag_count} shared tag(s) are generic in this lineup — "
                "they mark a broad category, not a specific affinity"
            )

    limitations = []
    if missing:
        if reasons:
            limitations.append("; ".join(reasons))
    else:
        if not genre_backed:
            limitations.append(
                "no music-genre category on both sides — the score relies only on "
                "non-genre tags"
            )
        if single_shared_tag:
            limitations.append(
                "only one shared tag across both artists; one tag cannot corroborate affinity"
            )
        if all_shared_generic:
            if single_shared_tag:
                limitations.append("the only shared tag is generic in this lineup")
            else:
                limitations.append(
                    f"{len(shared_generic)} of {shared_tag_count} shared tag(s) are "
                    "generic in this lineup"
                )
        if len(signals) < MIN_CATEGORIES_FOR_CONFIDENT_SCORE:
            limitations.append("only one tag category was compared")
        if union_size < MIN_UNION_TAGS_FOR_CONFIDENT_SCORE:
            limitations.append(f"only {union_size} tag(s) available across both artists")
        if skipped:
            limitations.append(
                f"{len(skipped)} category/categories present on one side only and skipped"
            )

    return {
        "a": profile_a["entity_id"],
        "b": profile_b["entity_id"],
        "taste_similarity": _round(taste_score),
        "genre_similarity": _round(genre_score),
        "combined_similarity": _round(combined_score),
        "signals": signals,
        "skipped_categories": skipped,
        "categories_compared": [s["category"] for s in signals],
        "low_confidence": low_confidence,
        "confidence_note": confidence_note,
        "shared_genre_tags": sorted(genre_a & genre_b) if genre_score is not None else [],
        "shared_tags": shared_tags,
        "shared_tag_count": shared_tag_count,
        "shared_generic_tags": shared_generic,
        "shared_generic_tag_count": len(shared_generic),
        "generic_share": _round(generic_share) or 0.0,
        "shared_specific_tags": shared_specific,
        "shared_specific_tag_count": len(shared_specific),
        "shared_broad_tags": shared_broad,
        "broad_share": _round(broad_share) or 0.0,
        "genre_backed": genre_backed,
        "profile_sources": {
            "a": profile_a.get("source"),
            "b": profile_b.get("source"),
        },
        "evidence_limitations": limitations,
        "missing": missing,
        "missing_kind": missing_kind,
        "missing_reason": "; ".join(reasons) if reasons else None,
    }


def similarity_matrix(profiles: list[dict]) -> list[dict]:
    """All pairwise similarities for a list of profiles."""
    broad = lineup_broad_tags(profiles)
    generic = lineup_generic_tags(profiles)
    pairs = []
    for i in range(len(profiles)):
        for j in range(i + 1, len(profiles)):
            pairs.append(
                pair_similarity(
                    profiles[i], profiles[j], broad_tags=broad, generic_tags=generic
                )
            )
    return pairs


def coverage(profiles: list[dict], pairs: list[dict]) -> dict:
    """How much of this lineup can actually be compared, and where it is thin."""
    with_data = [p for p in profiles if all_tags(p)]
    category_coverage = {}
    for category in CATEGORIES:
        artists = sum(1 for p in with_data if category_tags(p, category))
        category_coverage[category] = {
            "label": CATEGORY_LABELS[category],
            "artists": artists,
            "of": len(profiles),
            "weight": CATEGORY_WEIGHTS[category],
        }
    scored = [p for p in pairs if not p["missing"]]
    genre_backed = sum(1 for p in scored if p.get("genre_backed"))
    return {
        "profiles_total": len(profiles),
        "profiles_with_data": len(with_data),
        "profiles_missing": len(profiles) - len(with_data),
        "category_coverage": category_coverage,
        "pairs_total": len(pairs),
        "pairs_scored": len(scored),
        "pairs_missing": len(pairs) - len(scored),
        "pairs_low_confidence": sum(1 for p in scored if p["low_confidence"]),
        "pairs_genre_backed": genre_backed,
        "pairs_without_genre": len(scored) - genre_backed,
        "pairs_single_shared_tag": sum(
            1 for p in scored if p.get("shared_tag_count") == 1
        ),
        # A pair whose entire positive support is generic (including a single
        # generic tag) is the case the generic-evidence rule is meant to expose.
        "pairs_generic_only": sum(
            1
            for p in scored
            if p.get("shared_tag_count")
            and p.get("shared_generic_tag_count") == p.get("shared_tag_count")
        ),
        # Thin means an artist that has *some* tags is missing this dimension; an
        # artist with no tags at all is already counted in profiles_missing.
        "thin_categories": [
            CATEGORY_LABELS[c]
            for c, stats in category_coverage.items()
            if stats["artists"] < len(with_data)
        ],
    }


def objective_similarity(pair: dict) -> float | None:
    """Metric used by the clash objective: the documented multi-signal blend."""
    return pair["taste_similarity"]


def objective_method(pair: dict) -> str:
    return OBJECTIVE_METHOD
