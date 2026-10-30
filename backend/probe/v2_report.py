"""Render probe v2's timestamped JSON and Markdown artifacts."""
from __future__ import annotations

import json
from pathlib import Path


def _num(value, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _pct(value) -> str:
    return "-" if value is None else f"{value}%"


def _confidence_label(row: dict) -> str:
    if row.get("taste_similarity") is None:
        return "unscored"
    return "low" if row.get("low_confidence") else "passes"


def _cell(value) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _short_tag(tag: str) -> str:
    return tag.rsplit(":", 1)[-1].replace("_", " ")


def _tags(tags, limit: int = 6) -> str:
    if not tags:
        return "-"
    shown = ", ".join(_short_tag(tag) for tag in tags[:limit])
    if len(tags) > limit:
        shown += f" (+{len(tags) - limit})"
    return _cell(shown)


def _row(*cells) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = [_row(*headers), "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend(_row(*row) for row in rows)
    return lines


def _banner(report: dict) -> str:
    meta = report["probe"]
    transport = meta["transport"]
    if meta["mode"] == "test-double":
        return (
            "> **TEST DOUBLE - NOT EVIDENCE.** The client was injected by a test. "
            "Every number below exercises the probe pipeline and says nothing about "
            "real Qloo coverage or the artists."
        )
    if meta["evidence"]["is_evidence"]:
        cache = transport.get("cache") or {}
        cache_text = (
            f" {cache.get('cache_hits', 0)} response(s) were served from the disk "
            "cache on this run."
            if cache.get("enabled") and cache.get("cache_hits")
            else ""
        )
        text = (
            "> **LIVE.** Profiles come from Qloo responses observed in this run "
            f"({transport['searches_succeeded']} search(es) and "
            f"{transport['insights_succeeded']} insights request(s) succeeded; "
            f"{transport['profiles_usable']} artist(s) with usable tags). "
            "Similarity is tag affinity, **not** measured audience overlap, shared "
            "fans, ticket demand or attendance."
            + cache_text
        )
    else:
        text = (
            "> **LIVE RUN - NO USABLE EVIDENCE.** "
            f"{transport['logical_requests']} logical request(s) were issued; "
            f"{transport['profiles_usable']} artist(s) carried usable tags. Any "
            "scores below are pipeline output, not a finding about Qloo or the "
            "artists."
        )
    if meta.get("aborted"):
        aborted = meta["aborted"]
        text += (
            f" **ABORTED** at {aborted['stage']} for `{aborted['artist_id']}`: "
            f"{aborted['reason']} Coverage is partial."
        )
    return text


def _run_table(report: dict) -> list[str]:
    meta = report["probe"]
    transport = meta["transport"]
    params = meta["request_parameters"]
    cache = transport.get("cache") or {}
    rows = [
        ["Run id", meta["run_id"]],
        ["Generated (UTC)", meta["generated_at"]],
        ["Mode", meta["mode"]],
        ["Evidence", "yes - live responses" if meta["evidence"]["is_evidence"] else "no"],
        [
            "Dataset",
            f"{meta['dataset']['artist_count']} artists, "
            f"{meta['dataset']['sanity_check_count']} sanity checks, "
            f"sha256 {meta['dataset']['sha256'][:12]}",
        ],
        ["Qloo base URL", meta["qloo"]["base_url"]],
        ["Search request", f"{params['search']['method']} {params['search']['path']} "
         f"(types={params['search']['types']})"],
        ["Insights request", f"{params['insights']['method']} {params['insights']['path']} "
         f"(filter.type={params['insights']['filter.type']}, "
         f"take={params['insights']['take']})"],
        ["Pagination", "not used - see section 1"],
        ["Timeout", f"{params['timeout_seconds']} s"],
        ["Delay between requests", f"{params['delay_seconds']} s"],
        ["Logical requests", transport["logical_requests"]],
        [
            "Search / main insights / depth insights",
            f"{transport['search_requests']} / {transport['main_insights_requests']} / "
            f"{transport['depth_insights_requests']}",
        ],
    ]
    if cache.get("enabled"):
        rows.extend(
            [
                ["Cache hits", cache.get("cache_hits", 0)],
                ["Cache misses", cache.get("cache_misses", 0)],
                ["Network attempts", cache.get("network_attempts", 0)],
                ["Transient retries", cache.get("transient_retries", 0)],
                [
                    "Client-internal 429 retries",
                    cache.get("client_internal_retries", 0),
                ],
                ["Cache directory", cache.get("cache_dir")],
            ]
        )
    rows.extend(
        [
            ["Profile cache hits (in-memory)", transport["profile_cache_hits"]],
            ["Provider errors", meta["provider_errors"]],
        ]
    )
    return _table(["Run", "Value"], rows)


def _section_parameters(report: dict) -> list[str]:
    meta = report["probe"]
    params = meta["request_parameters"]
    depth = params["take_depth"]
    pagination = params["pagination"]
    lines = ["## 1. Request parameters and depth rationale", ""]
    lines.append(
        f"The main matrix uses **take={params['insights']['take']}** per "
        f"`/v2/insights` call. The production default is "
        f"{depth['production_default']}. The largest value documented as accepted "
        f"is {depth['largest_documented_accepted']}; the endpoint accepted 30 and 50 "
        "on 2026-10-23 and rejected 100 with HTTP 400 "
        f"({depth['source']}). This probe does not assume a higher value will work."
    )
    lines.append("")
    lines.append(
        "Pagination was **not used**. "
        + pagination["reason"]
        + " The same `take` was sent for every artist, so profile depth is "
        "consistent inside the main matrix."
    )
    lines.append("")
    d = params["depth_sensitivity"]
    if d["enabled"]:
        lines.append(
            f"Depth sensitivity re-fetches a small selected subset at take={d['take']} "
            f"for {d['pairs']} pair(s), using fresh cache keys. That subset compares "
            "the production default with the main depth; it is not a second full run."
        )
    else:
        lines.append("Depth sensitivity was disabled for this run.")
    lines.append("")
    lines.append(
        "Each search is `GET /search?query=<artist name>&types=urn:entity:artist`; "
        "each profile is `GET /v2/insights?filter.type=urn:tag&"
        "signal.interests.entities=<selected entity id>&take="
        f"{params['insights']['take']}`. Requests are sequential with a "
        f"{params['delay_seconds']} s delay and a {params['timeout_seconds']} s "
        "timeout. Only transient transport/timeout/5xx failures are retried once."
    )
    lines.append("")
    return lines


def _resolution_detail(record: dict) -> str:
    resolution = record["resolution"]
    status = resolution["status"]
    if status == "ambiguous":
        candidates = "; ".join(
            f"{candidate.get('name')} ({candidate.get('entity_id')})"
            for candidate in resolution["candidates"][:3]
            if candidate.get("entity_id")
        )
        return "Ambiguous candidates: " + (candidates or "-")
    if status == "api_error":
        return resolution.get("error") or "Qloo search failed"
    if status == "not_found":
        return "No artist entity returned"
    return resolution.get("selected_entity_id") or "-"


def _section_resolution(report: dict) -> list[str]:
    analysis = report["computed"]["analysis"]
    records = report["observed"]["artists"]
    resolution = analysis["resolution"]
    lines = ["## 2. Artist resolution", ""]
    lines.append(
        "Statuses are recorded separately. `ambiguous` means the production "
        "heuristic saw competing plausible candidates; the artist is not profiled "
        "or scored because no user confirmed an entity. `api_error` means the "
        "search call failed."
    )
    lines.append("")
    lines.extend(
        _table(
            ["Status", "Artists", "Names"],
            [
                [
                    status,
                    resolution["counts"].get(status, 0),
                    ", ".join(resolution["artists"].get(status, [])) or "-",
                ]
                for status in ("matched", "ambiguous", "not_found", "api_error")
            ],
        )
    )
    lines.append("")
    unmatched = [
        record
        for record in records
        if record["resolution"]["status"] != "matched"
    ]
    if unmatched:
        lines.extend(
            _table(
                ["Artist", "Status", "Detail"],
                [
                    [
                        record["name"],
                        record["resolution"]["status"],
                        _resolution_detail(record),
                    ]
                    for record in unmatched
                ],
            )
        )
        lines.append("")
    else:
        lines.append("Every name resolved to one confirmed artist entity.")
        lines.append("")
    return lines


def _profile_row(record: dict) -> list:
    section = record["profile"]
    counts = section["tag_counts"]
    raw = section["raw_tag_counts"]
    return [
        record["name"],
        record["scene"],
        record["resolution"]["status"],
        section["source"],
        f"{raw['genre']} / {counts['genre']}",
        counts["audience"],
        counts["style"],
        counts["music"],
        sum(1 for value in counts.values() if value),
        section["coverage_class"],
        _cell((section.get("note") or "-")[:120]),
    ]


def _section_profiles(report: dict) -> list[str]:
    analysis = report["computed"]["analysis"]
    coverage = analysis["profile_coverage"]
    records = report["observed"]["artists"]
    lines = ["## 3. Profiles and coverage", ""]
    lines.append(
        f"{coverage['usable']} of {coverage['profiles_total']} artists have a "
        f"usable profile; {coverage['genre_artists']} carry genre tags "
        f"({coverage['genre_share_of_usable']:.1%} of usable). Profile sources: "
        + ", ".join(
            f"{source} {count}" for source, count in coverage["source_counts"].items()
        )
        + ". Coverage classes: "
        + ", ".join(
            f"{klass} {count}"
            for klass, count in coverage["coverage_class_counts"].items()
        )
        + "."
    )
    lines.append("")
    lines.append(
        "`Genre raw / canonical` counts the ids returned by Qloo versus ids after "
        "namespace canonicalization. Canonical ids are what scoring uses; raw ids "
        "remain in the JSON. `Categories` is the number of non-empty dimensions "
        "among genre, audience, style and other music. `Sparse` means fewer than "
        "two categories or under three tags; `genre_thin` means usable tags but no "
        "genre dimension."
    )
    lines.append("")
    lines.extend(
        _table(
            [
                "Artist",
                "Scene",
                "Status",
                "Source",
                "Genre raw / canonical",
                "Audience",
                "Style",
                "Other music",
                "Categories",
                "Coverage",
                "Note",
            ],
            [_profile_row(record) for record in records],
        )
    )
    lines.append("")
    lines.append("Category coverage across usable profiles:")
    lines.append("")
    lines.extend(
        _table(
            ["Dimension", "Weight", "Artists with tags", "Thin?"],
            [
                [
                    stats["label"],
                    stats["weight"],
                    f"{stats['artists']} / {stats['of']}",
                    "yes" if stats["artists"] < coverage["usable"] else "no",
                ]
                for stats in coverage["category_coverage"].values()
            ],
        )
    )
    lines.append("")
    lines.append(f"Thin dimensions: {', '.join(coverage['thin_categories']) or 'none'}.")
    lines.append("")
    insufficient = analysis["insufficient_coverage"]
    lines.append("### Artists with missing, sparse or thin coverage")
    lines.append("")
    if insufficient:
        lines.extend(
            _table(
                ["Artist", "Status", "Coverage", "Tags", "Reason"],
                [
                    [
                        row["name"],
                        row["resolution_status"],
                        row["coverage_class"],
                        ", ".join(
                            f"{category} {count}"
                            for category, count in row["tag_counts"].items()
                            if count
                        )
                        or "none",
                        _cell(row["reason"]),
                    ]
                    for row in insufficient
                ],
            )
        )
    else:
        lines.append("None: every artist resolved and carried a non-thin profile.")
    lines.append("")
    return lines


def _distribution_table(distribution: dict) -> list[str]:
    return _table(
        [
            "n",
            "Min",
            "Q1",
            "Median",
            "Q3",
            "Mean",
            "Max",
            "P90",
            "Zeros",
            "Zero share",
        ],
        [
            [
                distribution["n"],
                _num(distribution["min"]),
                _num(distribution["q1"]),
                _num(distribution["median"]),
                _num(distribution["q3"]),
                _num(distribution["mean"]),
                _num(distribution["max"]),
                _num(distribution["p90"]),
                distribution["zeros"],
                f"{distribution['zero_share']:.1%}",
            ]
        ],
    )


def _section_matrix(report: dict) -> list[str]:
    analysis = report["computed"]["analysis"]
    matrix = analysis["matrix"]
    confidence = analysis["confidence"]
    lines = ["## 4. Pair matrix and score distribution", ""]
    lines.append(
        f"{matrix['pairs_scored']} of {matrix['pairs_total']} possible pairs are "
        f"scored ({matrix['pairs_missing']} excluded because at least one artist "
        f"had no usable or comparable profile). Of the scored pairs, "
        f"{matrix['zero_count']} ({matrix['zero_share']:.1%}) score exactly 0.000. "
        f"{matrix['pairs_with_genre_both']} scored pairs have genre tags on both "
        f"sides; {matrix['pairs_sufficient_with_genre']} sufficient-evidence pairs "
        "are genre-backed."
    )
    lines.append("")
    lines.extend(_distribution_table(matrix["distribution"]))
    lines.append("")
    lines.append(
        "Quartiles use linear interpolation (`statistics.quantiles`, inclusive); "
        "P90 is nearest-rank. The nonzero distribution is reported separately "
        "because zeros dominate many real tag sets."
    )
    lines.append("")
    lines.extend(_distribution_table(matrix["nonzero_distribution"]))
    lines.append("")
    lines.append(
        f"{confidence['sufficient_evidence']} scored pairs pass the production "
        f"confidence rule; {confidence['low_confidence']} are low-confidence. "
        "Low-confidence triggers (overlapping, not mutually exclusive): "
        + (
            ", ".join(
                f"{trigger} {count}"
                for trigger, count in confidence["low_confidence_trigger_counts"].items()
            )
            or "none"
        )
        + "."
    )
    lines.append("")
    lines.extend(
        _table(
            ["Categories compared", "Scored pairs"],
            [
                [count, pairs]
                for count, pairs in confidence[
                    "categories_compared_distribution"
                ].items()
            ],
        )
    )
    lines.append("")
    lines.append(matrix["verdict_note"])
    lines.append("")
    missing_kinds = matrix["missing_kinds"]
    if missing_kinds:
        lines.append(
            "Excluded-pair reasons: "
            + ", ".join(
                f"{kind or 'unknown'} {count}" for kind, count in missing_kinds.items()
            )
            + "."
        )
        lines.append("")
    return lines


def _pair_table(rows: list[dict]) -> list[str]:
    return _table(
        [
            "Rank",
            "Pair",
            "Taste",
            "Genre",
            "Pctl",
            "Confidence",
            "Genre-backed",
            "Shared tags",
            "Limitations",
        ],
        [
            [
                row["rank"],
                " / ".join(row["pair"]),
                _num(row["taste_similarity"]),
                _num(row["genre_similarity"]),
                _pct(row["percentile"]),
                _confidence_label(row),
                "yes" if row["genre_backed"] else "no",
                _tags(row["shared_tags"], 6),
                _cell("; ".join(row["evidence_limitations"]) or "-"),
            ]
            for row in rows
        ],
    )


def _section_extremes(report: dict) -> list[str]:
    analysis = report["computed"]["analysis"]
    high = analysis["highest_nonzero_pairs"]
    low = analysis["lowest_nonzero_pairs"]
    lines = ["## 5. Highest and lowest nonzero pairs", ""]
    lines.append(
        "Only pairs with a positive score are shown. A zero has no shared tag to "
        "display; it is not a bug and not proof of dissimilarity."
    )
    lines.append("")
    lines.append("### Highest nonzero")
    lines.append("")
    if high:
        lines.extend(_pair_table(high))
    else:
        lines.append("No pair scored above zero.")
    lines.append("")
    lines.append("### Lowest nonzero")
    lines.append("")
    if low:
        lines.extend(_pair_table(low))
    else:
        lines.append("No pair scored above zero.")
    lines.append("")
    return lines


def _section_shared_tags(report: dict) -> list[str]:
    analysis = report["computed"]["analysis"]
    frequency = analysis["shared_tag_frequency"]
    dominance = analysis["generic_dominance"]
    lines = ["## 6. Shared-tag frequency and generic dominance", ""]
    lines.append(
        f"Across {frequency['pairs_with_shared_tags']} scored pair(s) with shared "
        f"tags and {frequency['pairs_without_shared_tags']} without, there are "
        f"{frequency['distinct_shared_tags']} distinct shared tag(s). Tag frequency "
        "below is counted over scored pairs; artist frequency is over the "
        f"{analysis['profile_coverage']['usable']} usable profiles. The full list "
        "is in the JSON."
    )
    lines.append("")
    rows = frequency["rows"][:20]
    if rows:
        lines.extend(
            _table(
                [
                    "Tag",
                    "Categories",
                    "Artists (share)",
                    "Pairs (share)",
                    "Generic rule",
                    "Broad rule",
                ],
                [
                    [
                        f"`{row['tag']}`",
                        ", ".join(row["categories"]),
                        f"{row['artists']}/{row['of_artists']} "
                        f"({row['artist_share']:.0%})",
                        f"{row['pairs']}/{row['of_scored_pairs']} "
                        f"({row['pair_share']:.0%})",
                        "yes" if row["generic_rule"] else "no",
                        "yes" if row["broad_rule"] else "no",
                    ]
                    for row in rows
                ],
            )
        )
    else:
        lines.append("No shared tags were observed.")
    lines.append("")
    lines.append(
        f"Lineup-generic tags under the production rule: "
        f"{len(dominance['lineup_generic_tags'])}"
        + (
            " ("
            + _tags(dominance["lineup_generic_tags"], 10)
            + ")"
            if dominance["lineup_generic_tags"]
            else ""
        )
        + ". The rule is lineup-local and never changes a score."
    )
    lines.append("")
    lines.append(
        f"Among the top {dominance['top_pair_limit']} scored pairs, the mean "
        f"generic share is {dominance['top_mean_generic_share']:.1%}; "
        f"{dominance['top_pairs_all_generic']} pair(s) rest entirely on generic "
        f"tags and {dominance['top_pairs_majority_generic']} have a generic "
        f"majority. Across all scored pairs, "
        f"{dominance['scored_pairs_all_generic']} are entirely generic and "
        f"{dominance['scored_pairs_majority_generic']} have a generic majority "
        f"(mean score {_num(dominance['mean_score_majority_generic'])} versus "
        f"{_num(dominance['mean_score_majority_specific'])} for specific-majority "
        "pairs)."
    )
    lines.append("")
    if dominance["top_pairs"]:
        lines.extend(
            _table(
                [
                    "Rank",
                    "Pair",
                    "Taste",
                    "Shared",
                    "Generic",
                    "Generic share",
                    "Specific shared tags",
                ],
                [
                    [
                        row["rank"],
                        " / ".join(row["pair"]),
                        _num(row["taste_similarity"]),
                        row["shared_tag_count"],
                        row["shared_generic_tag_count"],
                        f"{row['generic_share']:.0%}",
                        _tags(row["shared_specific_tags"], 5),
                    ]
                    for row in dominance["top_pairs"]
                ],
            )
        )
    else:
        lines.append("No scored pairs to inspect.")
    lines.append("")
    return lines


def _sanity_evidence(row: dict) -> list[str]:
    lines = [
        f"**{row['id']}** - "
        f"{' / '.join(row['pair']) if row['pair'] else row['a'] + ' / ' + row['b']}"
    ]
    lines.append("")
    lines.append(f"- Hypothesis: {row['hypothesis']}")
    lines.append(
        f"- Verdict: **{row['verdict']}** ({row['verdict_basis']}). "
        f"Taste {_num(row['taste_similarity'])}; genre "
        f"{_num(row['genre_similarity'])}; percentile {_pct(row['percentile'])}; "
        f"confidence {_confidence_label(row)}."
    )
    if row["interpretation"]:
        lines.append(f"- Interpretation: {row['interpretation']}")
    if row["shared_evidence"]:
        for signal in row["shared_evidence"]:
            lines.append(
                f"- Shared {signal['category']} evidence: J={_num(signal['jaccard'])}, "
                f"weight {signal['weight']}, tags: {_tags(signal['shared_tags'], 8)}"
            )
    if row["skipped_categories"]:
        lines.append(
            "- Skipped categories: "
            + "; ".join(
                f"{item['label']} ({item['reason']})"
                for item in row["skipped_categories"]
            )
        )
    counts = row["profile_tag_counts"] or {}
    lines.append(
        "- Profile tag counts: "
        + "; ".join(
            f"{side}: {counts.get(side)}" for side in (row["a"], row["b"])
        )
    )
    if row["evidence_limitations"]:
        lines.append(
            "- Pair limitations: " + "; ".join(row["evidence_limitations"]) + "."
        )
    lines.append("")
    return lines


def _section_sanity(report: dict) -> list[str]:
    rows = report["computed"]["analysis"]["sanity_checks"]
    lines = ["## 7. Predeclared sanity checks", ""]
    lines.append(
        "These five pairs were declared before the run. Verdicts are descriptive: "
        "`similar` checks compare the score with the p80/p50 values of this set; "
        "the `lower` check compares it with p20/p50. They are not ground truth and "
        "do not measure audience overlap."
    )
    lines.append("")
    lines.extend(
        _table(
            [
                "Pair",
                "Expectation",
                "Taste",
                "Genre",
                "Pctl",
                "Verdict",
                "Confidence",
                "Shared tags",
            ],
            [
                [
                    " / ".join(row["pair"]) if row["pair"] else f"{row['a']} / {row['b']}",
                    row["expectation"],
                    _num(row["taste_similarity"]),
                    _num(row["genre_similarity"]),
                    _pct(row["percentile"]),
                    row["verdict"],
                    _confidence_label(row),
                    _tags(row["shared_tags"], 6),
                ]
                for row in rows
            ],
        )
    )
    lines.append("")
    for row in rows:
        lines.extend(_sanity_evidence(row))
    return lines


def _section_depth(report: dict) -> list[str]:
    depth = report["computed"]["analysis"]["depth_sensitivity"]
    lines = ["## 8. Depth sensitivity", ""]
    if not depth.get("enabled"):
        lines.append(depth.get("note") or "Depth sensitivity was disabled.")
        lines.append("")
        return lines
    if depth.get("error"):
        lines.append(
            f"The depth check failed after {depth.get('pairs_checked', 0)} pair(s): "
            f"{depth['error']}"
        )
        lines.append("")
    lines.append(
        f"Compared take={depth.get('take_deep')} with take={depth.get('take_shallow')} "
        f"on {depth.get('pairs_checked', 0)} selected pair(s). A change of at least "
        f"{depth.get('material_delta_threshold')} in the taste blend is called "
        "material for this probe - a descriptive cutoff, not a significance test."
    )
    lines.append("")
    if depth.get("pairs_with_comparable_scores") is not None:
        lines.append(
            f"{depth.get('pairs_with_comparable_scores')} pair(s) had comparable "
            f"scores; {depth.get('material_pairs', 0)} moved materially; max "
            f"|delta| {_num(depth.get('max_abs_taste_delta'))}, mean "
            f"{_num(depth.get('mean_abs_taste_delta'))}."
        )
        lines.append("")
    rows = depth.get("rows") or []
    if rows:
        table_rows = []
        for row in rows:
            deep_counts = row["tag_counts_deep"]
            shallow_counts = row["tag_counts_shallow"]
            ids = row["artist_ids"]
            table_rows.append(
                [
                    " / ".join(row["pair"]),
                    _num(row["deep"]["taste_similarity"]),
                    _num(row["shallow"]["taste_similarity"]),
                    _num(row["delta_taste_deep_minus_shallow"]),
                    "yes" if row["material"] else "no",
                    f"{sum(deep_counts[ids[0]].values())} / "
                    f"{sum(deep_counts[ids[1]].values())}",
                    f"{sum(shallow_counts[ids[0]].values())} / "
                    f"{sum(shallow_counts[ids[1]].values())}",
                    f"{row['profile_sources_shallow'][ids[0]]} / "
                    f"{row['profile_sources_shallow'][ids[1]]}",
                ]
            )
        lines.extend(
            _table(
                [
                    "Pair",
                    "Deep taste",
                    "Shallow taste",
                    "Delta (deep - shallow)",
                    "Material",
                    "Deep tags A/B",
                    "Shallow tags A/B",
                    "Shallow sources",
                ],
                table_rows,
            )
        )
        lines.append("")
        if any(row["insights_errors"] for row in rows):
            lines.append("Shallow-fetch insights errors:")
            lines.append("")
            for row in rows:
                for error in row["insights_errors"]:
                    lines.append(f"- {' / '.join(row['pair'])}: {error}")
            lines.append("")
    if depth.get("note"):
        lines.append(depth["note"])
        lines.append("")
    return lines


def _section_diagnosis(report: dict) -> list[str]:
    analysis = report["computed"]["analysis"]
    diagnosis = analysis["diagnosis"]
    matrix = analysis["matrix"]
    coverage = analysis["profile_coverage"]
    dominance = analysis["generic_dominance"]
    depth = analysis["depth_sensitivity"]
    lines = ["## 9. Diagnosis", ""]
    lines.append(f"**Likely cause:** {diagnosis['likely_cause']}")
    lines.append("")
    lines.append(f"**Basis:** {diagnosis['basis']}")
    lines.append("")
    lines.append(
        f"- Coverage: {coverage['usable']}/{coverage['profiles_total']} artists "
        f"usable, {coverage['genre_artists']} with genre. Thin dimensions: "
        f"{', '.join(coverage['thin_categories']) or 'none'}."
    )
    lines.append(
        f"- Zeros: {matrix['zero_count']} of {matrix['pairs_scored']} scored pairs "
        f"({matrix['zero_share']:.1%}). Of those, "
        f"{diagnosis['zero_pairs_with_genre_both']} had genre on both sides, "
        f"{diagnosis['zero_pairs_no_shared_tags']} had no shared tag in any compared "
        f"category, and {diagnosis['zero_pairs_without_genre_side']} lacked genre on "
        "at least one side."
    )
    lines.append(
        f"- Confidence: {analysis['confidence']['sufficient_evidence']} sufficient, "
        f"{analysis['confidence']['low_confidence']} low. "
        f"{analysis['confidence']['genre_backed']} scored pairs are genre-backed."
    )
    lines.append(
        f"- Generic tags: top-10 mean generic share "
        f"{dominance['top_mean_generic_share']:.1%}; "
        f"{dominance['top_pairs_all_generic']} top-10 pair(s) rest entirely on "
        "generic tags."
    )
    if depth.get("enabled") and not depth.get("error"):
        lines.append(
            f"- Depth: {depth.get('pairs_checked', 0)} pair(s) compared; "
            f"{depth.get('material_pairs', 0)} material, max |delta| "
            f"{_num(depth.get('max_abs_taste_delta'))}."
        )
    lines.append("")
    lines.append(
        "This diagnosis separates a scoring/pipeline failure from sparse or "
        "disjoint live vocabulary. It is not a statistical test, and no result "
        "here measures who attends which set."
    )
    lines.append("")
    return lines


def render_markdown(report: dict) -> str:
    meta = report["probe"]
    lines = [
        "# ClashDoctor live Qloo probe v2 - 30 established artists",
        "",
        _banner(report),
        "",
    ]
    lines.extend(_run_table(report))
    lines.append("")
    lines.extend(_section_parameters(report))
    lines.extend(_section_resolution(report))
    lines.extend(_section_profiles(report))
    lines.extend(_section_matrix(report))
    lines.extend(_section_extremes(report))
    lines.extend(_section_shared_tags(report))
    lines.extend(_section_sanity(report))
    lines.extend(_section_depth(report))
    lines.extend(_section_diagnosis(report))

    lines.append("## 10. Limitations")
    lines.append("")
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")

    lines.append("## 11. Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("cd backend")
    lines.append(
        ".venv/Scripts/python -m probe.v2 --live --take 50 --depth-take 20 "
        "--depth-pairs 3"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "The command is sequential, uses a "
        f"{meta['request_parameters']['timeout_seconds']} s timeout and a "
        f"{meta['request_parameters']['delay_seconds']} s delay, and retries only "
        "transient transport/timeout/5xx failures. Successful raw responses are "
        "cached under `probe/outputs/cache/v2/`; a rerun reuses them instead of "
        "repeating live calls. Use `--refresh` to fetch a new snapshot. Artifacts "
        "are written to `probe/outputs/live-v2/<run-id>-qloo-probe-v2.{json,md}`. "
        "Mock mode does not exist for this probe; the offline tests inject a fake "
        "client."
    )
    lines.append("")
    return "\n".join(lines)


def write_v2_reports(report: dict, out_dir: str | Path) -> dict[str, str]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    stem = f"{report['probe']['run_id']}-qloo-probe-v2"
    json_path = target / f"{stem}.json"
    markdown_path = target / f"{stem}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}
