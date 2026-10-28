"""Unit tests for the similarity engine."""
import pytest

from app import similarity


def make_profile(entity_id="x", genre=None, audience=None, style=None, music=None, missing=False):
    return {
        "entity_id": entity_id,
        "source": "test",
        "missing": missing,
        "genre_tags": genre or [],
        "audience_tags": audience or [],
        "style_tags": style or [],
        "music_tags": music or [],
    }


def make_canonical_profile(entity_id, raw_genres, canonical_genres, **kwargs):
    profile = make_profile(entity_id, genre=raw_genres, **kwargs)
    profile["canonical_genre_tags"] = canonical_genres
    return profile


def test_jaccard_basics():
    assert similarity.jaccard({"a"}, {"a"}) == 1.0
    assert similarity.jaccard({"a", "b"}, {"b", "c"}) == 1 / 3
    assert similarity.jaccard({"a"}, {"b"}) == 0.0
    assert similarity.jaccard(set(), set()) == 0.0


def test_genre_only_jaccard_matches_brief_example():
    # Taylor Swift - Beyonce style overlap: 1 shared of 3 union tags
    a = make_profile(genre=["pop", "country"], audience=["loyal"])
    b = make_profile(genre=["pop", "rnb"], style=["powerful"])
    pair = similarity.pair_similarity(a, b)
    assert pair["genre_similarity"] == pytest.approx(1 / 3, abs=1e-4)
    assert pair["shared_genre_tags"] == ["pop"]
    # combined uses all tag categories -> wider union, separately labelled
    assert pair["combined_similarity"] == pytest.approx(1 / 5, abs=1e-4)


def test_empty_profiles_are_missing_not_zero():
    a = make_profile("a", missing=True)
    b = make_profile("b", missing=True)
    pair = similarity.pair_similarity(a, b)
    assert pair["missing"] is True
    assert pair["genre_similarity"] is None
    assert pair["combined_similarity"] is None
    assert "missing" in pair["missing_reason"]


def test_one_sided_missing_is_missing():
    a = make_profile("a", genre=["rock"])
    b = make_profile("b", missing=True)
    pair = similarity.pair_similarity(a, b)
    assert pair["missing"] is True
    assert pair["genre_similarity"] is None


def test_genre_only_when_other_categories_present():
    # genre unavailable on one side -> genre score None, combined still computed
    a = make_profile("a", genre=[], audience=["loyal"])
    b = make_profile("b", genre=["rock"], audience=["loyal"])
    pair = similarity.pair_similarity(a, b)
    assert pair["genre_similarity"] is None
    assert pair["combined_similarity"] == pytest.approx(0.5)
    assert pair["missing"] is False


def test_matrix_covers_all_pairs():
    profiles = [make_profile(str(i), genre=["rock"]) for i in range(4)]
    pairs = similarity.similarity_matrix(profiles)
    assert len(pairs) == 6
    keys = {tuple(sorted((p["a"], p["b"]))) for p in pairs}
    assert len(keys) == 6


def test_objective_metric_is_the_taste_blend():
    pair = similarity.pair_similarity(
        make_profile("a", genre=["rock"], audience=["loyal"]),
        make_profile("b", genre=["rock", "pop"], audience=["loyal"]),
    )
    assert similarity.objective_similarity(pair) == pair["taste_similarity"]
    assert similarity.objective_method(pair) == "taste_blend"
    missing_pair = {"taste_similarity": None, "missing": True}
    assert similarity.objective_similarity(missing_pair) is None


def test_scores_bounded_and_rounded():
    a = make_profile(genre=["rock", "electronic"])
    b = make_profile(genre=["rock"])
    pair = similarity.pair_similarity(a, b)
    assert 0.0 <= pair["genre_similarity"] <= 1.0
    assert pair["genre_similarity"] == 0.5
    assert 0.0 <= pair["taste_similarity"] <= 1.0


# --- multi-signal blend: absent categories are skipped, never disagreement ---

def test_absent_category_is_skipped_and_weight_renormalized():
    """A has no audience tags; the blend must use genre only, not genre+0 audience."""
    a = make_profile("a", genre=["shoegaze", "dream pop"])
    b = make_profile("b", genre=["shoegaze", "dream pop"], audience=["late night"])
    pair = similarity.pair_similarity(a, b)
    assert pair["categories_compared"] == ["genre"]
    assert pair["taste_similarity"] == pytest.approx(1.0)
    assert pair["skipped_categories"][0]["category"] == "audience"
    assert "only b has audience tags" == pair["skipped_categories"][0]["reason"]


def test_disjoint_categories_are_missing_not_zero():
    """Tags that never overlap in category cannot be compared — report missing."""
    a = make_profile("a", genre=["metal"])
    b = make_profile("b", audience=["late night"])
    pair = similarity.pair_similarity(a, b)
    assert pair["missing"] is True
    assert pair["taste_similarity"] is None
    # the pooled reference score still exists, but it is not used as evidence
    assert pair["combined_similarity"] == 0.0
    assert pair["missing_kind"] == "disjoint_categories"
    assert "no tag category is available for both artists" in pair["missing_reason"]


def test_signals_explain_which_shared_tags_produced_the_score():
    a = make_profile("a", genre=["electronic"], audience=["festival goers"], style=["energetic"])
    b = make_profile("b", genre=["electronic", "house"], audience=["festival goers"])
    pair = similarity.pair_similarity(a, b)
    by_category = {s["category"]: s for s in pair["signals"]}
    assert by_category["genre"]["shared_tags"] == ["electronic"]
    assert by_category["audience"]["shared_tags"] == ["festival goers"]
    assert "style" not in by_category  # only a has style tags
    # contributions are the weighted parts and must sum to the blend
    assert sum(s["contribution"] for s in pair["signals"]) == pytest.approx(
        pair["taste_similarity"], abs=1e-4
    )
    assert sum(s["normalized_weight"] for s in pair["signals"]) == pytest.approx(1.0)
    assert pair["taste_similarity"] == pytest.approx(
        (0.55 * 0.5 + 0.20 * 1.0) / 0.75, abs=1e-4
    )


def test_shared_audience_signal_lifts_a_pair_with_identical_genres():
    """Same genre overlap, different audience overlap -> different scores."""
    base = make_profile("a", genre=["indie rock"], audience=["students"])
    same = make_profile("b", genre=["indie rock"], audience=["students"])
    different = make_profile("c", genre=["indie rock"], audience=["parents"])
    near = similarity.pair_similarity(base, same)
    far = similarity.pair_similarity(base, different)
    assert near["genre_similarity"] == far["genre_similarity"] == 1.0
    assert near["taste_similarity"] > far["taste_similarity"]


def test_low_confidence_marks_thin_evidence():
    single = similarity.pair_similarity(
        make_profile("a", genre=["rock"]), make_profile("b", genre=["rock", "metal"])
    )
    assert single["low_confidence"] is True
    assert "music genre" in single["confidence_note"]
    rich = similarity.pair_similarity(
        make_profile(
            "a",
            genre=["rock", "punk"],
            audience=["young", "students"],
            style=["energetic", "loud"],
        ),
        make_profile(
            "b",
            genre=["rock", "metal"],
            audience=["young", "festival goers"],
            style=["energetic", "aggressive"],
        ),
    )
    assert rich["low_confidence"] is False
    assert rich["confidence_note"] is None


def test_coverage_reports_what_could_and_could_not_be_compared():
    profiles = [
        make_profile("a", genre=["rock"], audience=["young"]),
        make_profile("b", genre=["rock"]),
        make_profile("c", missing=True),
    ]
    pairs = similarity.similarity_matrix(profiles)
    stats = similarity.coverage(profiles, pairs)
    assert stats["profiles_total"] == 3
    assert stats["profiles_with_data"] == 2
    assert stats["profiles_missing"] == 1
    assert stats["pairs_total"] == 3
    assert stats["pairs_scored"] == 1
    assert stats["pairs_missing"] == 2
    assert stats["pairs_low_confidence"] == 1  # the one scored pair shares genre only
    assert stats["category_coverage"]["genre"]["artists"] == 2
    assert stats["category_coverage"]["genre"]["of"] == 3
    assert stats["category_coverage"]["audience"]["artists"] == 1
    assert "audience" in stats["thin_categories"]
    assert all(
        stats["category_coverage"][c]["weight"] == similarity.CATEGORY_WEIGHTS[c]
        for c in similarity.CATEGORIES
    )


def test_tag_counts_expose_the_evidence_per_artist():
    profile = make_profile("a", genre=["rock"], audience=["young"], style=["energetic"])
    assert similarity.tag_counts(profile) == {
        "genre": 1,
        "audience": 1,
        "style": 1,
        "music": 0,
    }


def test_method_strings_stay_documented_and_free_of_overlap_claims():
    text = " ".join(similarity.METHODS.values()).lower()
    for claim in ("shared fan", "fan overlap", "audience overlap", "attendance"):
        assert claim not in text


# --- canonical genre evidence (P1) ---

def test_canonical_genres_score_across_provider_namespaces():
    # insights profile vs search-fallback profile: same labels, different URIs.
    a = make_canonical_profile(
        "a",
        ["urn:tag:genre:music:folk", "urn:tag:genre:music:indie_folk"],
        ["urn:tag:genre:music:folk", "urn:tag:genre:music:indie_folk"],
        audience=["students", "record collectors", "indie"],
        style=["acoustic", "storytelling"],
    )
    b = make_canonical_profile(
        "b",
        ["urn:tag:genre:qloo:folk", "urn:tag:genre:qloo:indie_folk"],
        ["urn:tag:genre:music:folk", "urn:tag:genre:music:indie_folk"],
        audience=["students", "record collectors", "indie"],
        style=["acoustic", "storytelling"],
    )
    pair = similarity.pair_similarity(a, b)
    assert pair["genre_similarity"] == 1.0
    assert pair["shared_genre_tags"] == [
        "urn:tag:genre:music:folk",
        "urn:tag:genre:music:indie_folk",
    ]
    assert pair["genre_backed"] is True
    assert pair["low_confidence"] is False


def test_canonical_genres_do_not_merge_distinct_labels():
    a = make_canonical_profile(
        "a", ["urn:tag:genre:folk"], ["urn:tag:genre:music:folk"]
    )
    b = make_canonical_profile(
        "b", ["urn:tag:genre:qloo:indie_folk"], ["urn:tag:genre:music:indie_folk"]
    )
    pair = similarity.pair_similarity(a, b)
    assert pair["genre_similarity"] == 0.0
    assert pair["shared_genre_tags"] == []


def test_raw_genre_ids_are_ignored_when_canonical_ids_exist():
    # If category_tags fell back to the raw IDs these namespaces would never meet.
    a = make_canonical_profile(
        "a", ["urn:tag:genre:music:jazz"], ["urn:tag:genre:music:jazz"]
    )
    b = make_canonical_profile(
        "b", ["urn:tag:genre:jazz"], ["urn:tag:genre:music:jazz"]
    )
    pair = similarity.pair_similarity(a, b)
    assert pair["genre_similarity"] == 1.0


# --- evidence rules (P3/P4) ---

def test_one_shared_tag_is_low_confidence_even_with_multiple_categories():
    # Naezy/Nucleya shape: only `bollywood` overlaps; other categories are present
    # but disjoint, so the positive score rests on one shared tag.
    a = make_profile(
        "naezy",
        genre=["urn:tag:genre:music:bollywood"],
        audience=["desi", "youth", "street"],
        style=["raw", "political"],
    )
    b = make_profile(
        "nucleya",
        genre=["urn:tag:genre:music:bollywood"],
        audience=["club", "electronic", "festival"],
        style=["loud", "bass"],
    )
    pair = similarity.pair_similarity(a, b)
    assert pair["taste_similarity"] > 0
    assert pair["categories_compared"] == ["genre", "audience", "style"]
    assert pair["shared_tag_count"] == 1
    assert pair["low_confidence"] is True
    assert "single shared tag" in pair["confidence_note"]
    assert any(
        "only one shared tag" in limitation for limitation in pair["evidence_limitations"]
    )


def test_lineup_broad_tags_are_judged_within_the_lineup_only():
    profiles = [
        make_profile(str(i), genre=["bollywood", f"specific_{i}"], audience=[f"aud_{i}"])
        for i in range(6)
    ]
    broad = similarity.lineup_broad_tags(profiles)
    assert "bollywood" in broad
    assert "specific_0" not in broad
    # Fewer than the documented minimum: no tag is called broad.
    assert similarity.lineup_broad_tags(profiles[:5]) == set()


def test_all_shared_tags_generic_is_low_confidence_without_changing_the_score():
    profiles = [
        make_profile(
            f"p{i}",
            genre=["bollywood", f"specific_{i}"],
            audience=["students", f"audience_{i}"],
        )
        for i in range(6)
    ]
    pairs = similarity.similarity_matrix(profiles)
    pair = next(p for p in pairs if {p["a"], p["b"]} == {"p0", "p1"})
    # p0 and p1 share only the two lineup-wide tags. Both are generic and broad.
    assert pair["shared_tags"] == ["bollywood", "students"]
    assert pair["shared_generic_tag_count"] == 2
    assert pair["generic_share"] == 1.0
    assert pair["shared_specific_tag_count"] == 0
    assert pair["broad_share"] == 1.0
    assert pair["low_confidence"] is True
    assert "generic in this lineup" in pair["confidence_note"]

    without_context = similarity.pair_similarity(profiles[0], profiles[1])
    assert without_context["taste_similarity"] == pair["taste_similarity"]
    # Without lineup context the same score looks confident: the guard is evidence,
    # not a silently reweighted score.
    assert without_context["low_confidence"] is False


# --- generic-tag evidence (follow-up) ---

def generic_lineup():
    """11 tagged acts; bollywood/desi are generic but not broad (4/11, 3/11)."""
    profiles = [
        make_profile(
            f"p{i}",
            genre=(["bollywood", f"genre_{i}"] if i < 3 else [f"genre_{i}"]),
            audience=(["desi", f"aud_{i}"] if i < 3 else [f"aud_{i}"]),
            style=[f"style_{i}"],
        )
        for i in range(8)
    ]
    profiles.append(
        make_profile(
            "q",
            genre=["bollywood", "other"],
            audience=["x", "y"],
            style=["s1", "s2"],
        )
    )
    profiles.append(
        make_profile(
            "s0",
            genre=["free_jazz", "jazz_0"],
            audience=["aud_s0"],
            style=["modal", "style_s0"],
        )
    )
    profiles.append(
        make_profile(
            "s1",
            genre=["free_jazz", "jazz_1"],
            audience=["aud_s1"],
            style=["modal", "style_s1"],
        )
    )
    return profiles


def test_lineup_generic_tags_are_separate_from_broad_and_lineup_local():
    profiles = generic_lineup()
    generic = similarity.lineup_generic_tags(profiles)
    assert "bollywood" in generic  # 4/11
    assert "desi" in generic  # 3/11
    assert "free_jazz" not in generic  # 2/11: a specific genre stays specific
    assert "style_0" not in generic
    # Broad means at least half the lineup; none of these tags qualify.
    assert similarity.lineup_broad_tags(profiles) == set()
    # Fewer than the documented minimum: no tag is called generic.
    assert similarity.lineup_generic_tags(profiles[:5]) == set()


def test_one_generic_shared_tag_is_low_confidence_and_reports_counts():
    profiles = generic_lineup()
    generic = similarity.lineup_generic_tags(profiles)
    p0 = next(p for p in profiles if p["entity_id"] == "p0")
    q = next(p for p in profiles if p["entity_id"] == "q")
    pair = similarity.pair_similarity(p0, q, generic_tags=generic)
    assert pair["shared_tags"] == ["bollywood"]
    assert pair["shared_generic_tag_count"] == 1
    assert pair["shared_generic_tags"] == ["bollywood"]
    assert pair["shared_specific_tag_count"] == 0
    assert pair["generic_share"] == 1.0
    assert pair["low_confidence"] is True
    assert "single shared tag that is generic" in pair["confidence_note"]
    assert "the only shared tag is generic in this lineup" in pair["evidence_limitations"]


def test_multiple_generic_shared_tags_are_low_confidence_without_broad_tags():
    profiles = generic_lineup()
    pairs = similarity.similarity_matrix(profiles)
    pair = next(p for p in pairs if {p["a"], p["b"]} == {"p0", "p1"})
    assert pair["shared_tags"] == ["bollywood", "desi"]
    assert pair["shared_generic_tag_count"] == 2
    assert pair["shared_specific_tag_count"] == 0
    assert pair["generic_share"] == 1.0
    # Neither tag is broad; the generic rule alone is what downgrades the pair.
    assert pair["broad_share"] == 0.0
    assert pair["low_confidence"] is True
    assert "all 2 shared tag(s) are generic" in pair["confidence_note"]

    without_context = similarity.pair_similarity(profiles[0], profiles[1])
    assert without_context["taste_similarity"] == pair["taste_similarity"]
    assert without_context["low_confidence"] is False


def test_specific_shared_tags_are_not_misclassified_as_generic():
    profiles = generic_lineup()
    pairs = similarity.similarity_matrix(profiles)
    pair = next(p for p in pairs if {p["a"], p["b"]} == {"s0", "s1"})
    assert pair["shared_tags"] == ["free_jazz", "modal"]
    assert pair["shared_generic_tag_count"] == 0
    assert pair["shared_specific_tag_count"] == 2
    assert pair["shared_specific_tags"] == ["free_jazz", "modal"]
    assert pair["generic_share"] == 0.0
    assert pair["low_confidence"] is False


def test_missing_genre_evidence_still_applies_the_generic_rule():
    profiles = [
        make_profile(
            f"m{i}",
            audience=["desi", "students", f"aud_{i}"],
            style=[f"style_{i}"],
            music=[f"music_{i}"],
        )
        for i in range(8)
    ]
    pairs = similarity.similarity_matrix(profiles)
    pair = next(p for p in pairs if {p["a"], p["b"]} == {"m0", "m1"})
    assert pair["genre_similarity"] is None
    assert pair["genre_backed"] is False
    assert pair["shared_generic_tag_count"] == 2
    assert pair["shared_specific_tag_count"] == 0
    assert pair["low_confidence"] is True
    assert "generic in this lineup" in pair["confidence_note"]
    assert any("no music-genre category" in item for item in pair["evidence_limitations"])


def test_coverage_counts_generic_only_pairs():
    profiles = generic_lineup()
    pairs = similarity.similarity_matrix(profiles)
    stats = similarity.coverage(profiles, pairs)
    assert stats["pairs_generic_only"] == sum(
        1
        for pair in pairs
        if not pair["missing"]
        and pair["shared_tag_count"]
        and pair["shared_generic_tag_count"] == pair["shared_tag_count"]
    )
    assert stats["pairs_generic_only"] >= 1


def test_coverage_separates_genre_backed_from_other_signal_only_pairs():
    profiles = [
        make_profile("a", genre=["rock"], audience=["young", "students"]),
        make_profile("b", genre=["rock"], audience=["young", "parents"]),
        make_profile("c", audience=["young", "club"]),
    ]
    pairs = similarity.similarity_matrix(profiles)
    stats = similarity.coverage(profiles, pairs)
    assert stats["pairs_scored"] == 3
    assert stats["pairs_genre_backed"] == 1
    assert stats["pairs_without_genre"] == 2
    assert stats["pairs_single_shared_tag"] == 2


# --- does the scoring behave sensibly on a varied lineup? ---

VARIED = {
    "radiohead": make_profile(
        "radiohead",
        genre=["art rock", "alternative rock", "electronic"],
        audience=["record collectors", "students"],
        style=["experimental", "melancholic"],
    ),
    "slowdive": make_profile(
        "slowdive",
        genre=["shoegaze", "dream pop", "alternative rock"],
        audience=["record collectors"],
        style=["dreamy", "lush"],
    ),
    "my blood valve": make_profile(
        "my blood valve",
        genre=["shoegaze", "noise pop", "alternative rock"],
        audience=["record collectors", "young"],
        style=["lush", "loud"],
    ),
    "slayer": make_profile(
        "slayer",
        genre=["thrash metal", "metal"],
        audience=["mosh pit"],
        style=["aggressive", "loud"],
    ),
    "beyonce": make_profile(
        "beyonce",
        genre=["r&b", "pop", "dance"],
        audience=["stadium crowds", "families"],
        style=["powerful", "polished"],
    ),
    "taylor swift": make_profile(
        "taylor swift",
        genre=["pop", "country"],
        audience=["stadium crowds", "young"],
        style=["polished", "storytelling"],
    ),
    "bts": make_profile(
        "bts",
        genre=["k-pop", "pop", "hip hop"],
        audience=["stadium crowds", "young"],
        style=["polished", "energetic"],
    ),
    "buena vista": make_profile(
        "buena vista social club",
        genre=["son cubano", "latin jazz"],
        audience=["seniors", "dancers"],
        style=["acoustic", "nostalgic"],
    ),
    "no profile": make_profile("no-profile", missing=True),
}


def sim(a: str, b: str) -> float:
    pair = similarity.pair_similarity(VARIED[a], VARIED[b])
    assert pair["missing"] is False, f"{a} vs {b} unexpectedly has no data"
    return pair["taste_similarity"]


def test_varied_lineup_orders_similar_acts_above_dissimilar_ones():
    # same scene beats same-era-but-different-scene
    assert sim("slowdive", "my blood valve") > sim("radiohead", "slayer")
    # shared audience pulls pop acts together even when genres differ
    assert sim("taylor swift", "bts") > sim("taylor swift", "buena vista")
    assert sim("beyonce", "bts") > sim("beyonce", "slayer")
    # metal vs dream pop is the weakest non-missing link in the set
    weakest = min(sim(a, b) for a in VARIED for b in VARIED if a < b and not ({"no profile"} & {a, b}))
    assert weakest == sim("slowdive", "slayer") or weakest < 0.1


def test_varied_lineup_shares_nothing_with_missing_profiles():
    """An act without tags is excluded from every pair, never scored as zero."""
    for other, profile in VARIED.items():
        pair = similarity.pair_similarity(VARIED["no profile"], profile)
        assert pair["missing"] is True
        assert pair["missing_kind"] == "profile_data"
        assert pair["taste_similarity"] is None
        assert pair["combined_similarity"] is None or other == "no profile"


def test_varied_lineup_explanations_name_real_shared_signals():
    pair = similarity.pair_similarity(VARIED["radiohead"], VARIED["my blood valve"])
    assert pair["categories_compared"] == ["genre", "audience", "style"]
    assert pair["genre_similarity"] == pytest.approx(1 / 5, abs=1e-4)
    by_category = {s["category"]: s for s in pair["signals"]}
    assert by_category["genre"]["shared_tags"] == ["alternative rock"]
    assert by_category["audience"]["shared_tags"] == ["record collectors"]
    assert by_category["style"]["shared_tags"] == []  # no style overlap, still compared
    assert len(pair["signals"]) == 3
    assert sum(s["contribution"] for s in pair["signals"]) == pytest.approx(
        pair["taste_similarity"], abs=1e-3
    )
    # the blend must not be dominated by a single thin category
    assert max(s["normalized_weight"] for s in pair["signals"]) < 0.75
