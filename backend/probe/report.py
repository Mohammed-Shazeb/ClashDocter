"""Render the probe's JSON, Markdown and similarity-matrix CSV."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .core import CATEGORIES


def _num(value, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _pct(value) -> str:
    return "-" if value is None else f"{value}%"


def _short_tag(tag: str) -> str:
    return tag.rsplit(":", 1)[-1].replace("_", " ")


def _tags(tags: list[str], limit: int = 6) -> str:
    if not tags:
        return "-"
    shown = ", ".join(_short_tag(tag) for tag in tags[:limit])
    if len(tags) > limit:
        shown += f" (+{len(tags) - limit})"
    return shown


def _row(*cells) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = [_row(*headers), "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend(_row(*row) for row in rows)
    return lines


def _coverage_table(coverage: dict, meta: dict) -> list[str]:
    return _table(
        ["Metric", "Value"],
        [
            ["Artists in matrix", coverage["profiles_total"]],
            ["Artists with usable tags", coverage["profiles_with_data"]],
            [
                "Unconfirmed names (subset below)",
                meta["transport"].get("names_unconfirmed", 0),
            ],
            [
                "Artists without usable tags (incl. unconfirmed)",
                coverage["profiles_missing"],
            ],
            ["Pairs total", coverage["pairs_total"]],
            ["Pairs scored", coverage["pairs_scored"]],
            ["Pairs excluded (no comparable data)", coverage["pairs_missing"]],
            ["Pairs low-confidence", coverage["pairs_low_confidence"]],
            [
                "Scored pairs with genre on both sides",
                coverage.get("pairs_with_genre_both", "-"),
            ],
            [
                "Sufficient-evidence pairs with genre on both sides",
                coverage.get("pairs_sufficient_with_genre", "-"),
            ],
        ],
    )


def _category_table(coverage: dict) -> list[str]:
    rows = []
    for category in CATEGORIES:
        stats = coverage["category_coverage"][category]
        thin = stats["artists"] < coverage["profiles_with_data"]
        rows.append(
            [
                stats["label"],
                stats["weight"],
                f"{stats['artists']} / {stats['of']}",
                "yes" if thin else "no",
            ]
        )
    return _table(["Dimension", "Weight", "Artists with tags", "Thin?"], rows)


def _label_table(report: dict) -> list[str]:
    rows = []
    for label in ("established", "emerging"):
        coverage = report["computed"]["coverage_by_label"][label]
        rows.append(
            [
                label,
                coverage["profiles_with_data"],
                coverage["profiles_missing"],
                coverage["pairs_total"],
                coverage["pairs_scored"],
                coverage["pairs_missing"],
                coverage["pairs_low_confidence"],
                coverage["pairs_with_sufficient_evidence"],
                coverage.get("pairs_sufficient_with_genre", "-"),
            ]
        )
    cross = report["computed"]["coverage_cross_label"]
    rows.append(
        [
            "cross-label",
            cross["profiles_with_data"],
            cross["profiles_missing"],
            cross["pairs_total"],
            cross["pairs_scored"],
            cross["pairs_missing"],
            cross["pairs_low_confidence"],
            cross["pairs_with_sufficient_evidence"],
            cross.get("pairs_sufficient_with_genre", "-"),
        ]
    )
    return _table(
        [
            "Set",
            "Profiles with tags",
            "Missing",
            "Pairs",
            "Scored",
            "Excluded",
            "Low-confidence",
            "Sufficient evidence",
            "Genre-backed suff.",
        ],
        rows,
    )


def _source_counts(records: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for record in records:
        section = record["profile"]
        if section["source"] in ("unresolved", "unconfirmed"):
            key = section["source"]
        elif section["missing"]:
            key = "entity resolved, no usable tags"
        else:
            key = section["source"]
        counts[key] = counts.get(key, 0) + 1
    return counts


def render_markdown(report: dict) -> str:
    meta = report["probe"]
    computed = report["computed"]
    observed = report["observed"]
    records = observed["artists"]
    mock = meta["mode"] == "mock"
    lines: list[str] = []

    lines.append("# ClashDoctor Qloo validation probe")
    lines.append("")
    if mock:
        lines.append(
            "> **MOCK MODE - synthetic fixture, not evidence.** Every tag below is "
            "generated from the dataset's human genre descriptions. The report exercises "
            "the pipeline and calculations; it says nothing about real Qloo coverage, "
            "and its similarity scores are not findings about the artists."
        )
    elif meta["evidence"]["is_evidence"]:
        unconfirmed = meta["transport"].get("names_unconfirmed", 0)
        unconfirmed_text = (
            f" {unconfirmed} unconfirmed name(s) are excluded from scoring."
            if unconfirmed
            else ""
        )
        lines.append(
            "> **LIVE MODE.** Profiles below come from Qloo responses observed in this "
            f"run ({meta['transport']['live_requests_succeeded']} successful requests, "
            f"{meta['transport']['profiles_with_usable_tags']} artist(s) with usable "
            "tags). Similarity is computed from tags; it is **not** measured audience "
            "overlap, shared fans, ticket demand or attendance."
            + unconfirmed_text
        )
    else:
        lines.append(
            "> **LIVE RUN - NO USABLE EVIDENCE.** The probe attempted "
            f"{meta['transport']['requests_attempted']} request(s); "
            f"{meta['transport']['live_requests_succeeded']} succeeded and "
            f"{meta['transport']['profiles_with_usable_tags']} artist(s) carried usable "
            "tags. Any scores below are pipeline output, not a finding about Qloo or "
            "the artists."
        )
    lines.append("")
    lines.extend(
        _table(
            ["Run", "Value"],
            [
                ["Mode", meta["mode"]],
                ["Generated (UTC)", meta["generated_at"]],
                [
                    "Dataset",
                    f"{meta['dataset']['artist_count']} artists "
                    f"({meta['dataset']['label_counts'].get('established', 0)} established, "
                    f"{meta['dataset']['label_counts'].get('emerging', 0)} emerging), "
                    f"sha256 {meta['dataset']['sha256'][:12]}",
                ],
                ["Qloo base URL", meta["qloo"]["base_url"]],
                ["Search entity type", meta["qloo"]["search_type"]],
                ["Insights take", meta["qloo"]["insights_take"]],
                *(
                    [["Mock calls", meta["transport"]["mock_calls"]]]
                    if mock
                    else [
                        [
                            "Search requests",
                            f"{meta['transport']['search_requests_attempted']} attempted, "
                            f"{meta['transport']['searches_succeeded']} succeeded",
                        ],
                        [
                            "Insights requests",
                            f"{meta['transport']['insights_requests_attempted']} attempted, "
                            f"{meta['transport']['insights_succeeded']} succeeded",
                        ],
                    ]
                ),
                [
                    "Evidence",
                    (
                        "no - synthetic fixtures"
                        if mock
                        else ("yes - live responses" if meta["evidence"]["is_evidence"] else "no - no usable live data")
                    ),
                ],
            ],
        )
    )
    lines.append("")
    if meta.get("aborted"):
        lines.append(
            f"> **ABORTED** at {meta['aborted']['stage']} for artist "
            f"`{meta['aborted']['artist_id']}`: {meta['aborted']['reason']} "
            "Coverage below is partial."
        )
        lines.append("")
    for warning in meta.get("warnings", []):
        lines.append(f"- Warning: {warning}")
    if meta.get("warnings"):
        lines.append("")

    resolution_counts: dict[str, int] = {}
    for record in records:
        status = record["resolution"]["status"]
        resolution_counts[status] = resolution_counts.get(status, 0) + 1
    lines.append("## 1. Observed - artist resolution")
    lines.append("")
    lines.append(
        "Search query per artist: the documented name, restricted to "
        "`urn:entity:artist` by the production client. Confirmed means the production "
        "heuristic found one clear candidate. Ambiguous means several candidates are "
        "plausible; the names are listed, but **no unconfirmed entity is profiled or "
        "scored** in this run."
    )
    lines.append("")
    lines.extend(
        _table(["Resolution", "Artists"], [[k, v] for k, v in sorted(resolution_counts.items())])
    )
    lines.append("")
    unresolved = [
        record
        for record in records
        if record["resolution"]["status"] != "matched"
    ]
    if unresolved:
        rows = []
        for record in unresolved:
            resolution = record["resolution"]
            candidates = resolution["candidates"][:3]
            candidate_text = (
                "; ".join(
                    f"{c['name']} ({c['entity_id']})" for c in candidates if c.get("name")
                )
                or "-"
            )
            rows.append(
                [
                    record["name"],
                    record["label"],
                    resolution["status"],
                    resolution.get("error") or candidate_text,
                ]
            )
        lines.extend(_table(["Artist", "Set", "Status", "Detail"], rows))
        lines.append("")

    coverage = computed["coverage"]
    lines.append("## 2. Observed - profiles and coverage")
    lines.append("")
    source_counts = _source_counts(records)
    lines.append(
        "Profile sources (artists with usable tags): "
        + ", ".join(
            f"{source} {count}"
            for source, count in sorted(source_counts.items())
            if source not in ("unresolved", "unconfirmed", "entity resolved, no usable tags")
        )
        + ". Source `qloo-search` means insights returned no usable tags and the tags "
        "embedded in search results were used. Excluded from scoring: "
        + (
            ", ".join(
                f"{source} {count}"
                for source, count in sorted(source_counts.items())
                if source in ("unresolved", "unconfirmed", "entity resolved, no usable tags")
            )
            or "none"
        )
        + "."
    )
    lines.append("")
    lines.append(
        "Genre ids are normalized across Qloo namespaces (`urn:tag:genre:music:`, "
        "`urn:tag:genre:qloo:`, `urn:tag:genre:`) by prefix only. Original ids remain "
        "in `observed.artists[].profile.tags`; `canonical_tags` is what scoring and "
        "diagnostics use. Distinct labels such as `folk` and `indie_folk` are not merged."
    )
    lines.append("")
    lines.extend(_coverage_table(coverage, meta))
    lines.append("")
    lines.extend(_category_table(coverage))
    lines.append("")
    lines.append("Coverage by set (cross-label rows compare only across the two sets):")
    lines.append("")
    lines.extend(_label_table(report))
    lines.append("")
    thin = coverage["thin_categories"]
    lines.append(
        "Thin dimensions (fewer artists than have any profile): "
        + (", ".join(thin) if thin else "none")
        + "."
    )
    lines.append("")

    missing = computed["missing_or_sparse"]
    lines.append("### Artists with missing, sparse or unconfirmed profiles")
    lines.append("")
    if missing:
        lines.extend(
            _table(
                ["Artist", "Set", "Kind", "Tags", "Reason"],
                [
                    [
                        row["name"],
                        row["label"],
                        row["kind"],
                        ", ".join(f"{c} {n}" for c, n in row["tag_counts"].items() if n) or "none",
                        (row["reason"] or "").replace("|", "/"),
                    ]
                    for row in missing
                ],
            )
        )
    else:
        lines.append("None: every artist resolved and carried at least two categories.")
    lines.append("")

    summary = computed["matrix_summary"]
    lines.append("## 3. Computed - ranked similarity")
    lines.append("")
    distribution = summary["score_distribution"]
    lines.append(
        f"{summary['pairs_scored']} of {summary['pairs_total']} pairs are scored "
        f"({summary['pairs_missing']} excluded for missing data, "
        f"{summary['pairs_low_confidence']} low-confidence, "
        f"{summary['pairs_with_sufficient_evidence']} with sufficient evidence). "
        f"{summary.get('pairs_with_genre_both', '-')} scored pairs have genre tags on "
        f"both sides; {summary.get('pairs_sufficient_with_genre', '-')} of the "
        "sufficient-evidence pairs are genre-backed. "
        f"Score distribution: mean {_num(distribution.get('mean'))}, "
        f"median {_num(distribution.get('median'))}, "
        f"p90 {_num(distribution.get('p90'))}, max {_num(summary['top_score'])}."
    )
    lines.append("")
    lines.append(summary["verdict_note"])
    lines.append("")
    lines.append("Top pairs (ranked by the documented taste blend):")
    lines.append("")
    top = computed["top_pairs"]
    rows = []
    for pair in top[:15]:
        shared = sorted(
            {tag for signal in pair["signals"] for tag in signal["shared_tags"]}
        )
        specific = pair.get("shared_specific_tags") or []
        rows.append(
            [
                pair.get("rank", "-"),
                f"{pair['artist_a']['name']} / {pair['artist_b']['name']}",
                f"{pair['artist_a']['label'][:4]}/{pair['artist_b']['label'][:4]}",
                _num(pair["taste_similarity"]),
                _num(pair["genre_similarity"]),
                "yes" if pair.get("genre_backed") else "no",
                ",".join(signal["category"] for signal in pair["signals"]),
                "low" if pair["low_confidence"] else "",
                _tags(shared, 4),
                f"{len(specific)}/{pair.get('shared_tag_count', len(shared))}",
                f"{pair.get('shared_generic_tag_count', 0)}/"
                f"{pair.get('shared_tag_count', len(shared))}",
                (
                    f"{pair.get('generic_share', 0):.0%}"
                    if pair.get("shared_tag_count")
                    else "-"
                ),
            ]
        )
    lines.extend(
        _table(
            [
                "#",
                "Pair",
                "Sets",
                "Taste",
                "Genre",
                "Genre-backed",
                "Signals",
                "Conf.",
                "Shared tags",
                "Specific/Shared",
                "Generic/Shared",
                "Generic share",
            ],
            rows,
        )
    )
    lines.append("")
    lines.append(
        "Generic here is lineup-local: a tag carried by at least a quarter of the "
        "tagged acts (minimum 3 acts and 6 tagged acts). The probe's separate "
        "set-aware generic flags are reported in section 4."
    )
    lines.append("")
    lines.append("Representative explanations (top 3):")
    lines.append("")
    for pair in top[:3]:
        lines.append(
            f"- **{pair['artist_a']['name']} / {pair['artist_b']['name']}** - "
            f"taste {_num(pair['taste_similarity'])}. " + "; ".join(
                f"{signal['label']} J={_num(signal['jaccard'])} "
                f"(weight {signal['normalized_weight']}) shared: "
                f"{_tags(signal['shared_tags'], 5)}"
                for signal in pair["signals"]
            )
        )
        for skipped in pair["skipped_categories"]:
            lines.append(f"  - excluded {skipped['label']}: {skipped['reason']}")
        if pair["missing_reason"]:
            lines.append(f"  - {pair['missing_reason']}")
        sources = pair.get("profile_sources") or {}
        lines.append(
            "  - evidence: "
            f"genre-backed {'yes' if pair.get('genre_backed') else 'no'}, "
            f"{pair.get('shared_generic_tag_count', 0)}/{pair.get('shared_tag_count', 0)} "
            "shared tag(s) generic, "
            f"{pair.get('shared_specific_tag_count', 0)}/{pair.get('shared_tag_count', 0)} "
            "specific, lineup generic share "
            f"{pair.get('generic_share', 0):.0%}, probe-set generic share "
            f"{pair.get('probe_generic_share', 0):.0%}; profile sources "
            f"{sources.get('a') or 'unknown'} / {sources.get('b') or 'unknown'}."
        )
        if pair.get("evidence_limitations"):
            lines.append(
                "  - limitations: " + "; ".join(pair["evidence_limitations"]) + "."
            )
    lines.append("")

    lines.append("## 4. Computed - evidence checks")
    lines.append("")
    if not summary.get("verdicts_informative", True):
        lines.append(f"> **Qualified verdicts.** {summary['verdict_note']}")
        lines.append("")
    lines.append("Expected-similar pairs (human judgment, sanity check only):")
    lines.append("")
    lines.extend(
        _table(
            ["Pair", "Taste", "Percentile", "Verdict", "Basis", "Low-conf."],
            [
                [
                    " / ".join(row["names"] or [row["a"], row["b"]]),
                    _num(row["taste_similarity"]),
                    _pct(row["percentile"]),
                    row["verdict"],
                    row.get("verdict_basis", "percentile"),
                    "yes" if row["low_confidence"] else "",
                ]
                for row in computed["expected_similar_checks"]
            ],
        )
    )
    lines.append("")
    lines.append("Expected-different pairs:")
    lines.append("")
    lines.extend(
        _table(
            ["Pair", "Taste", "Percentile", "Verdict", "Basis", "Low-conf."],
            [
                [
                    " / ".join(row["names"] or [row["a"], row["b"]]),
                    _num(row["taste_similarity"]),
                    _pct(row["percentile"]),
                    row["verdict"],
                    row.get("verdict_basis", "percentile"),
                    "yes" if row["low_confidence"] else "",
                ]
                for row in computed["expected_different_checks"]
            ],
        )
    )
    lines.append("")

    generic = computed["generic_tags"]
    lines.append(
        "Tag frequency (a tag is generic in this set at "
        f"{generic['threshold']:.0%} or more of the "
        f"{generic['profiles_with_data']} artists with profiles):"
    )
    lines.append("")
    if generic["top_tags"]:
        lines.extend(
            _table(
                ["Tag", "Artists", "Document frequency", "Generic?"],
                [
                    [
                        f"`{row['tag']}`",
                        f"{row['artists']} / {row['of']}",
                        row["document_frequency"],
                        "yes" if row["document_frequency"] >= generic["threshold"] else "no",
                    ]
                    for row in generic["top_tags"][:8]
                ],
            )
        )
    else:
        lines.append("No tags were available to measure.")
    lines.append("")

    label_generic = [
        section for section in generic.get("by_label", []) if section["generic_tags"]
    ]
    if label_generic:
        lines.append(
            "Tags that are generic within one set even when they fall below the "
            "overall threshold (a catch-all tag can inflate scores inside that set):"
        )
        lines.append("")
        for section in label_generic:
            lines.append(
                f"- {section['label']} ({section['profiles_with_data']} artists with profiles)"
            )
            lines.append("")
            lines.extend(
                _table(
                    ["Tag", "Artists", "Within-set frequency"],
                    [
                        [
                            f"`{row['tag']}`",
                            f"{row['artists']} / {row['of']}",
                            row["document_frequency"],
                        ]
                        for row in section["generic_tags"][:8]
                    ],
                )
            )
            lines.append("")

    if generic["pairs_flagged"]:
        lines.append(
            f"{generic['pairs_flagged_total']} high-scoring pair(s) have at least "
            "half of their shared tags flagged generic (overall or within a set); "
            "inspect these before reading them as affinity:"
        )
        lines.append("")
        lines.extend(
            _table(
                ["Pair", "Taste", "Generic share", "Generic tags", "Generic in"],
                [
                    [
                        " / ".join(row["pair"]),
                        _num(row["taste_similarity"]),
                        f"{row['generic_share']:.0%}",
                        _tags([tag["tag"] for tag in row["shared_tag_detail"]], 3),
                        ", ".join(
                            sorted(
                                {
                                    scope
                                    for tag in row["shared_tag_detail"]
                                    for scope in tag.get("scopes", [])
                                }
                            )
                        )
                        or "-",
                    ]
                    for row in generic["pairs_flagged"][:8]
                ],
            )
        )
        lines.append("")
    else:
        lines.append(
            "No high-scoring pair had at least half of its shared tags flagged generic."
        )
        lines.append("")

    sensitivity = computed["sensitivity"]
    genre = sensitivity["genre_only_vs_blend"]
    lines.append(
        f"Sensitivity: |taste blend - genre-only| mean {_num(genre.get('mean'))}, "
        f"max {_num(genre.get('max'))}, {genre.get('pairs_delta_above_0_1', 0)} pair(s) "
        "move by more than 0.1. Leave-one-category-out deltas:"
    )
    lines.append("")
    lines.extend(
        _table(
            ["Dropped category", "Pairs", "Mean abs delta", "Max abs delta"],
            [
                [category, stats.get("n", 0), _num(stats.get("mean")), _num(stats.get("max"))]
                for category, stats in sensitivity["leave_one_out"].items()
                if stats.get("n")
            ],
        )
    )
    lines.append("")
    high = sensitivity["high_sensitivity_pairs"]
    if high:
        lines.append(
            "Pairs most sensitive to dropping one category (the missing-data policy "
            "changes their score materially):"
        )
        lines.append("")
        for row in high[:5]:
            deltas = ", ".join(
                f"{category} {_num(delta)}" for category, delta in row["dropped_category_deltas"].items()
            )
            lines.append(
                f"- {row['pair'][0]} / {row['pair'][1]}: taste {_num(row['taste_similarity'])}, "
                f"max delta {_num(row['max_delta'])} ({deltas})"
            )
        lines.append("")

    suspicious = computed["suspicious_pairs"]
    lines.append("### Suspicious or counterintuitive pairs")
    lines.append("")
    if suspicious:
        lines.extend(
            _table(
                ["Kind", "Pair", "Taste", "Percentile", "Why"],
                [
                    [
                        row["kind"],
                        " / ".join(row["pair"]),
                        _num(row["taste_similarity"]),
                        _pct(row["percentile"]),
                        row["reason"].replace("|", "/"),
                    ]
                    for row in suspicious[:10]
                ],
            )
        )
    else:
        lines.append("None flagged by the heuristics below.")
    lines.append("")

    methods = computed["methods"]
    lines.append("## 5. Method (computed, not observed)")
    lines.append("")
    lines.append(f"- Taste blend: {methods['taste_blend']}")
    lines.append(f"- Genre reference: {methods['genre']}")
    lines.append(f"- Combined reference: {methods['combined']}")
    lines.append(
        "- A category is skipped when only one artist has it; remaining weights are "
        "renormalized, so missing data is never scored as disagreement."
    )
    thresholds = summary.get("score_thresholds") or {}
    threshold_text = ", ".join(
        f"{key} {_num(value)}" for key, value in thresholds.items()
    )
    lines.append(f"- Confidence: {methods['confidence']}.")
    lines.append(f"- Percentile: {methods['percentile']}.")
    lines.append(
        f"- Verdict thresholds: {methods['verdict_thresholds']} "
        f"This run: {threshold_text or 'no scored pairs'}."
    )
    lines.append(f"- Expected-similar verdicts: {methods['similar_verdicts']}.")
    lines.append(f"- Expected-different verdicts: {methods['different_verdicts']}.")
    lines.append("")
    lines.append(
        "No statistical validation is claimed. The dataset is handpicked and small; "
        "counts and percentiles describe this set only."
    )
    lines.append("")

    judgments = report["human_judgments"]
    lines.append("## 6. Human judgments (input, not observed)")
    lines.append("")
    if judgments.get("note"):
        lines.append(judgments["note"])
        lines.append("")
    for label, definition in (judgments.get("label_definitions") or {}).items():
        lines.append(f"- **{label}**: {definition}")
    lines.append("")
    lines.append("Expected similar pairs and rationale:")
    lines.append("")
    for entry in judgments["expected_similar_pairs"]:
        lines.append(f"- `{entry['a']}` / `{entry['b']}` ({entry.get('confidence', '-')}): {entry['rationale']}")
    lines.append("")
    lines.append("Expected different pairs and rationale:")
    lines.append("")
    for entry in judgments["expected_different_pairs"]:
        lines.append(f"- `{entry['a']}` / `{entry['b']}` ({entry.get('confidence', '-')}): {entry['rationale']}")
    lines.append("")

    lines.append("## 7. Limitations")
    lines.append("")
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")

    lines.append("## 8. Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("cd backend")
    lines.append(".venv/Scripts/python -m probe.run            # mock mode, no key needed")
    lines.append(".venv/Scripts/python -m probe.run --live     # real Qloo calls (QLOO_API_KEY required)")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_similarity_csv(report: dict, path: Path) -> None:
    headers = [
        "rank",
        "artist_a",
        "artist_b",
        "label_a",
        "label_b",
        "expected_group_a",
        "expected_group_b",
        "taste_similarity",
        "genre_similarity",
        "combined_similarity",
        "categories_compared",
        "shared_genre_tags",
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
        "low_confidence",
        "missing",
        "missing_kind",
        "missing_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for pair in report["computed"]["ranked_pairs"]:
            sources = pair.get("profile_sources") or {}
            writer.writerow(
                [
                    pair.get("rank", ""),
                    pair["artist_a"]["name"],
                    pair["artist_b"]["name"],
                    pair["artist_a"]["label"],
                    pair["artist_b"]["label"],
                    pair["artist_a"]["expected_group"],
                    pair["artist_b"]["expected_group"],
                    "" if pair["taste_similarity"] is None else pair["taste_similarity"],
                    "" if pair["genre_similarity"] is None else pair["genre_similarity"],
                    "" if pair["combined_similarity"] is None else pair["combined_similarity"],
                    "|".join(pair["categories_compared"]),
                    "|".join(pair["shared_genre_tags"]),
                    "|".join(pair.get("shared_tags") or []),
                    pair.get("shared_tag_count", 0),
                    "|".join(pair.get("shared_specific_tags") or []),
                    pair.get("shared_specific_tag_count", 0),
                    "|".join(pair.get("shared_generic_tags") or []),
                    pair.get("shared_generic_tag_count", 0),
                    pair.get("generic_share", 0),
                    (
                        ""
                        if pair.get("probe_generic_share") is None
                        else pair.get("probe_generic_share")
                    ),
                    "|".join(pair.get("probe_generic_shared_tags") or []),
                    "|".join(pair.get("probe_specific_shared_tags") or []),
                    "yes" if pair.get("genre_backed") else "no",
                    sources.get("a") or "",
                    sources.get("b") or "",
                    " | ".join(pair.get("evidence_limitations") or []),
                    "yes" if pair["low_confidence"] else "no",
                    "yes" if pair["missing"] else "no",
                    pair.get("missing_kind") or "",
                    (pair.get("missing_reason") or "").replace("\n", " "),
                ]
            )


def write_reports(report: dict, out_dir: str | Path) -> dict[str, str]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "report.json"
    markdown_path = target / "report.md"
    csv_path = target / "similarity_matrix.csv"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    write_similarity_csv(report, csv_path)
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "matrix_csv": str(csv_path),
    }
