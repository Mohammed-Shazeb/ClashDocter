"""Tests for the clash objective and the constraint-preserving optimizer."""
import pytest

from app import demo_data
from app import optimizer as opt
from app import similarity
from app.models import Act, Slot, Stage


def make_schedule(stages, slots, acts):
    stage_models = [Stage(id=sid, name=sid) for sid in stages]
    slot_models = [Slot(id=tid, label=tid, start=s, end=e) for tid, s, e in slots]
    act_models = [Act(**act) for act in acts]
    return opt.Schedule.from_payload(stage_models, slot_models, act_models)


BASIC_STAGES = ["main", "pulse"]
BASIC_SLOTS = [
    ("t1", "17:00", "18:00"),
    ("t2", "18:00", "19:00"),
]

def _pair(entity_a: str, tags_a: list, entity_b: str, tags_b: list) -> dict:
    return similarity.pair_similarity(
        {"entity_id": entity_a, "source": "test", "missing": False, "genre_tags": tags_a},
        {"entity_id": entity_b, "source": "test", "missing": False, "genre_tags": tags_b},
    )


# Two shared of four union genre tags -> 0.5 similarity on every metric.
SIM = {
    tuple(sorted(("e-a", "e-b"))): _pair("e-a", ["a", "b", "c"], "e-b", ["a", "b", "d"]),
}


def act(pid, name, entity, stage, slot, fixed=False, duration=60, **extra):
    return {"id": pid, "name": name, "entity_id": entity, "stage_id": stage,
            "slot_id": slot, "fixed": fixed, "duration_min": duration, **extra}


# --- time parsing ---

def test_parse_hhmm_accepts_2400_end_of_day():
    assert opt.parse_hhmm("24:00") == 24 * 60


def test_parse_hhmm_rejects_2401():
    with pytest.raises(opt.ScheduleError):
        opt.parse_hhmm("24:01")


def test_assign_supports_slot_ending_at_midnight():
    stages = [{"id": "s1", "name": "Main"}]
    slots = [{"id": "late", "label": "23:00", "start": "23:00", "end": "24:00"}]
    acts = [{"id": "a1", "name": "Alpha", "entity_id": "E1", "stage_id": "", "slot_id": ""}]
    result = opt.assign_schedule(
        [Stage(**s) for s in stages], [Slot(**s) for s in slots], [Act(**a) for a in acts]
    )
    assert result["acts"][0].slot_id == "late"


# --- objective ---

def test_similar_acts_simultaneously_clash():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t1")],
    )
    cost, clashes, excluded = schedule.cost_and_clashes(schedule.acts, SIM)
    assert cost == pytest.approx(0.5)
    assert len(clashes) == 1
    assert excluded == []


def test_similar_acts_in_separate_slots_do_not_clash():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t2")],
    )
    cost, clashes, _ = schedule.cost_and_clashes(schedule.acts, SIM)
    assert cost == 0.0
    assert clashes == []


def test_same_stage_same_slot_is_invalid_not_a_clash():
    with pytest.raises(opt.ScheduleError, match="double-booked"):
        make_schedule(
            BASIC_STAGES, BASIC_SLOTS,
            [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "main", "t1")],
        )


def test_missing_similarity_pairs_are_excluded():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t1")],
    )
    cost, clashes, excluded = schedule.cost_and_clashes(schedule.acts, {})
    assert cost == 0.0
    assert clashes == []
    assert len(excluded) == 1


def test_excluded_pairs_name_the_kind_of_missing_data():
    """"No profile" and "tags in different categories" must not read the same."""
    disjoint = similarity.pair_similarity(
        {"entity_id": "e-1", "source": "test", "missing": False, "genre_tags": ["metal"]},
        {"entity_id": "e-2", "source": "test", "missing": False, "audience_tags": ["chill"]},
    )
    no_profile = similarity.pair_similarity(
        {"entity_id": "e-1", "source": "test", "missing": False, "genre_tags": ["metal"]},
        {"entity_id": "e-3", "source": "test", "missing": True},
    )
    assert disjoint["missing_kind"] == "disjoint_categories"
    assert no_profile["missing_kind"] == "profile_data"

    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "One", "e-1", "main", "t1"),
         act("2", "Two", "e-2", "pulse", "t1"),
         act("3", "Three", "e-4", "pulse", "t2"),
         act("4", "Four", "e-3", "main", "t2")],
    )
    result = opt.optimize_schedule(schedule, {
        tuple(sorted(("e-1", "e-2"))): disjoint,
        tuple(sorted(("e-1", "e-3"))): no_profile,
    })
    reasons = {frozenset((e["a_name"], e["b_name"])): e["reason"]
               for e in result["excluded_pairs"]}
    assert any("different categories" in text for text in reasons.values())
    assert any("Missing taste profile" in text for text in reasons.values())
    assert result["initial_cost"] == 0.0, "uncomparable pairs add no cost"


def test_adjacent_slots_do_not_overlap():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t2")],
    )
    pairs = schedule.overlapping_pairs(schedule.acts)
    assert pairs == []


def test_acts_too_long_for_slot_are_invalid():
    with pytest.raises(opt.ScheduleError, match="does not fit"):
        make_schedule(
            BASIC_STAGES, BASIC_SLOTS,
            [act("1", "A", "e-a", "main", "t1", duration=90)],
        )


def test_unknown_stage_or_slot_is_invalid():
    with pytest.raises(opt.ScheduleError, match="unknown stage"):
        make_schedule(BASIC_STAGES, BASIC_SLOTS, [act("1", "A", "e-a", "nope", "t1")])
    with pytest.raises(opt.ScheduleError, match="unknown slot"):
        make_schedule(BASIC_STAGES, BASIC_SLOTS, [act("1", "A", "e-a", "main", "nope")])


def test_same_stage_overlapping_slots_are_invalid_not_a_clash():
    """Two distinct cells on one stage can still double-book it in time."""
    slots = [("t1", "17:00", "18:00"), ("t2", "17:30", "18:30")]
    with pytest.raises(opt.ScheduleError, match="overlapping sets") as excinfo:
        make_schedule(
            ["main"], slots,
            [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "main", "t2")],
        )
    assert "double-booked" not in str(excinfo.value), (
        "overlap is its own failure, not the same-cell error"
    )


def test_validate_schedule_reports_same_stage_overlap_separately_from_membership():
    result = opt.validate_schedule(
        [Stage(id="main", name="Main")],
        [Slot(id="t1", label="17:00", start="17:00", end="18:00"),
         Slot(id="t2", label="17:30", start="17:30", end="18:30")],
        [Act(id="1", name="A", entity_id="e-a", stage_id="main", slot_id="t1"),
         Act(id="2", name="B", entity_id="e-b", stage_id="main", slot_id="t2")],
    )
    assert result["valid"] is False
    assert any("overlapping sets" in issue for issue in result["issues"])
    assert not any("double-booked" in issue for issue in result["issues"])


def test_can_place_refuses_to_stack_overlapping_sets_on_one_stage():
    schedule = make_schedule(
        ["main", "pulse"],
        [("t1", "17:00", "18:00"), ("t2", "17:30", "18:30"), ("t3", "19:00", "20:00")],
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t3")],
    )
    movers = {entry.id: entry for entry in schedule.acts}
    occupied = {(entry.stage_id, entry.slot_id) for entry in schedule.acts}
    assert opt._can_place(
        schedule, movers["2"], "main", "t2", occupied, schedule.acts
    ) is False, "t2 overlaps t1 on the same stage"
    assert opt._can_place(
        schedule, movers["2"], "pulse", "t2", occupied, schedule.acts
    ) is True


# --- optimizer ---

def build_demo_similarities():
    profiles = []
    for entity_id, profile in demo_data.DEMO_PROFILES.items():
        profiles.append(profile)
    sims = {}
    for pair in similarity.similarity_matrix(profiles):
        sims[tuple(sorted((pair["a"], pair["b"])))] = pair
    return sims


def demo_schedule():
    return opt.Schedule.from_payload(
        [Stage(**s) for s in demo_data.DEMO_FESTIVAL["stages"]],
        [Slot(**s) for s in demo_data.DEMO_FESTIVAL["slots"]],
        [Act(**a) for a in demo_data.DEMO_FESTIVAL["acts"]],
    )


def test_multi_pass_optimization_keeps_every_cell_unique():
    """Regression: a stale act lookup after an earlier move could double-book."""
    schedule = demo_schedule()
    result = opt.optimize_schedule(schedule, build_demo_similarities())
    cells = [(a.stage_id, a.slot_id) for a in result["optimized_acts"]]
    assert len(result["moves"]) > 1, "multi-pass run expected for this regression"
    assert len(cells) == len(set(cells))
    assert len(result["optimized_acts"]) == len(schedule.acts)
    fixed_before = {a.id: (a.stage_id, a.slot_id) for a in schedule.acts if a.fixed}
    after = {a.id: (a.stage_id, a.slot_id) for a in result["optimized_acts"]}
    assert all(after[act_id] == cell for act_id, cell in fixed_before.items())


def test_fixed_headliners_never_move():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [
            act("1", "Headliner A", "e-a", "main", "t1", fixed=True),
            act("2", "Headliner B", "e-b", "pulse", "t1", fixed=True),
        ],
    )
    result = opt.optimize_schedule(schedule, SIM)
    assert result["moves"] == []
    assert result["initial_cost"] == result["optimized_cost"] == pytest.approx(0.5)
    assert len(result["fixed_clashes"]) == 1


def test_unimprovable_schedule_returns_no_moves():
    # all acts fixed -> no legal moves, cost unchanged
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [
            act("1", "A", "e-a", "main", "t1", fixed=True),
            act("2", "B", "e-b", "pulse", "t2", fixed=True),
        ],
    )
    result = opt.optimize_schedule(schedule, SIM)
    assert result["moves"] == []
    assert result["improvement"] == 0.0


def test_optimizer_resolves_clash_by_moving_to_empty_cell():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [
            act("1", "A", "e-a", "main", "t1"),
            act("2", "B", "e-b", "pulse", "t1"),
        ],
    )
    result = opt.optimize_schedule(schedule, SIM)
    assert result["initial_cost"] == pytest.approx(0.5)
    assert result["optimized_cost"] == 0.0
    assert result["improvement"] == pytest.approx(0.5)
    assert len(result["moves"]) == 1
    assert result["moves"][0]["explanation"].startswith("Removes")
    assert result["optimized_clashes"] == []


def test_optimizer_respects_allowed_stages():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [
            act("1", "A", "e-a", "main", "t1", allowed_stages=["main"]),
            act("2", "B", "e-b", "pulse", "t1"),
        ],
    )
    result = opt.optimize_schedule(schedule, SIM)
    # A can only be on main; moving B to t2 resolves the clash
    assert result["optimized_cost"] == 0.0
    for optimized_act in result["optimized_acts"]:
        if optimized_act.id == "1":
            assert optimized_act.stage_id == "main"


def test_demo_festival_improves_and_preserves_constraints():
    schedule = demo_schedule()
    sims = build_demo_similarities()
    result = opt.optimize_schedule(schedule, sims)

    assert result["initial_cost"] > result["optimized_cost"]
    assert result["improvement"] > 0
    assert result["moves"], "demo festival should have improving moves"

    # hard constraints preserved
    initial_by_id = {a.id: a for a in schedule.acts}
    final_by_id = {a.id: a for a in result["optimized_acts"]}
    assert set(initial_by_id) == set(final_by_id)
    for act_id, initial in initial_by_id.items():
        final = final_by_id[act_id]
        if initial.fixed:
            assert (final.stage_id, final.slot_id) == (initial.stage_id, initial.slot_id)
        if initial.allowed_stages:
            assert final.stage_id in initial.allowed_stages
        assert final.duration_min == initial.duration_min
        assert final.stage_id in schedule.stages
        assert final.slot_id in schedule.slots
    occupied = set()
    for final in final_by_id.values():
        cell = (final.stage_id, final.slot_id)
        assert cell not in occupied, "no double booking after optimization"
        occupied.add(cell)

    # fixed headliner clash remains and is reported
    assert result["fixed_clashes"], "aurora-lane vs skyline should remain clashing"
    fixed_ids = {a.id for a in schedule.acts if a.fixed}
    for entry in result["fixed_clashes"]:
        assert entry["a"].id in fixed_ids and entry["b"].id in fixed_ids

    # missing-profile pair (Enigma Collective) is excluded, not scored
    assert any(
        "Enigma" in entry["a_name"] or "Enigma" in entry["b_name"]
        for entry in result["excluded_pairs"]
    )


def test_demo_festival_has_expected_initial_clashes():
    schedule = demo_schedule()
    sims = build_demo_similarities()
    cost, clashes, excluded = schedule.cost_and_clashes(schedule.acts, sims)
    assert cost > 1.0
    # the two fixed pop headliners clash at t6
    assert any(
        {a.name, b.name} == {"Aurora Lane", "Skyline"} for a, b, _, _ in clashes
    )
    # enigma excluded from every one of its overlaps
    assert any(
        {a.name, b.name} == {"Enigma Collective", "Grit & Groove"}
        for a, b, _ in excluded
    )


# --- priorities: what the user tells the search to care about ---

def make_sims(tags_by_entity):
    """Full pairwise table for a lineup, so nothing is silently excluded."""
    entities = list(tags_by_entity)
    sims = {}
    for index, entity_a in enumerate(entities):
        for entity_b in entities[index + 1:]:
            sims[tuple(sorted((entity_a, entity_b)))] = _pair(
                entity_a, tags_by_entity[entity_a], entity_b, tags_by_entity[entity_b]
            )
    return sims


# Every 3-of-4 tag subset is 0.5 similar to the others, so these three acts form
# a triangle of three 0.5 clashes; moving any one of them away saves 1.0.
TRIANGLE = {"e-n": ["a", "b", "c"], "e-p1": ["a", "b", "d"], "e-p2": ["a", "c", "d"]}
# Disjoint universe: 3 shared of 5 union = 0.6, and 0.0 against the triangle.
HEADLINERS = {"e-h1": ["m", "n", "o"], "e-h2": ["m", "n", "o", "p", "q"]}
PRIORITY_TAGS = TRIANGLE | HEADLINERS

PRIORITY_STAGES = ["main", "pulse", "grove"]
PRIORITY_SLOTS = [
    ("t1", "17:00", "18:00"),
    ("t2", "18:00", "19:00"),
    ("t3", "19:00", "20:00"),
]


def priority_schedule():
    """Two separable problems: a 1.0-sum triangle and one 0.6 headliner clash.

    allowed_slots keep the groups from swapping into each other's time slots, so
    the only single actions available are 'break the triangle' (-1.0) and
    'break the headliner clash' (-0.6 raw). That is what makes the weighting
    verdict observable.
    """
    return make_schedule(
        PRIORITY_STAGES, PRIORITY_SLOTS,
        [act("n", "N", "e-n", "main", "t1", allowed_slots=["t1", "t3"]),
         act("p1", "P1", "e-p1", "pulse", "t1", allowed_slots=["t1", "t3"]),
         act("p2", "P2", "e-p2", "grove", "t1", allowed_slots=["t1", "t3"]),
         act("h1", "H1", "e-h1", "main", "t2", allowed_slots=["t2", "t3"]),
         act("h2", "H2", "e-h2", "pulse", "t2", allowed_slots=["t2", "t3"])],
    )


# Similarity that counts as high affinity only once the threshold is raised.
HIGH = opt.Preferences(high_affinity_threshold=0.55, high_affinity_weight=3.0)


def test_neutral_preferences_make_the_objective_the_plain_sum():
    result = opt.optimize_schedule(priority_schedule(), make_sims(PRIORITY_TAGS))
    assert result["before"]["raw_cost"] == pytest.approx(2.1)
    assert result["before"]["weighted_cost"] == pytest.approx(2.1)
    assert result["before"]["objective"] == pytest.approx(2.1)
    assert result["before"]["penalty"] == 0.0
    assert result["before"]["churn"] == 0
    # counted as high affinity, but a 1x weight leaves the sum untouched
    assert result["before"]["high_affinity_clashes"] == 4
    assert result["preferences_description"].startswith("Plain sum")


def test_a_shortened_move_cap_is_never_described_as_uncapped():
    described = opt.Preferences(max_moves=3).describe()
    assert described.startswith("no pair is weighted")
    assert "at most 3 moves" in described
    assert "at most 3 moves" in opt.Preferences(
        high_affinity_threshold=0.55, high_affinity_weight=3.0, max_moves=3
    ).describe()
    assert opt.DEFAULT_PREFERENCES.describe().startswith("Plain sum")


def test_high_affinity_weighting_changes_which_clash_is_fixed_first():
    sims = make_sims(PRIORITY_TAGS)
    neutral = opt.optimize_schedule(priority_schedule(), sims)
    prioritized = opt.optimize_schedule(priority_schedule(), sims, HIGH)

    assert neutral["moves"][0]["act_id"] == "n", "three 0.5 clashes are the biggest plain sum"
    assert prioritized["moves"][0]["act_id"] == "h1", "one 0.6 clash at 3x outweighs them"

    assert prioritized["before"]["raw_cost"] == pytest.approx(2.1), "raw sum ignores priorities"
    assert prioritized["before"]["weighted_cost"] == pytest.approx(3.3)
    assert prioritized["before"]["objective"] == pytest.approx(3.3)
    assert prioritized["before"]["high_affinity_clashes"] == 1
    assert "3.0x" in prioritized["preferences_description"]
    assert "0.55" in prioritized["preferences_description"]


def test_move_penalty_suppresses_a_change_that_costs_more_than_it_saves():
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t1")],
    )
    result = opt.optimize_schedule(schedule, SIM, opt.Preferences(move_penalty=0.6))
    assert result["moves"] == []
    assert result["improved"] is False
    assert result["improvement"] == 0.0
    assert result["after"]["penalty"] == 0.0
    assert result["after"]["raw_cost"] == pytest.approx(0.5), "the clash is still there"
    # two movable acts, and separating them would cost more than it saves
    assert {entry["kind"] for entry in result["unresolved"]} == {"local_optimum"}


def test_objective_and_raw_sum_are_reported_separately():
    """The raw clash sum can fall by more than the objective — both are printed."""
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1"), act("2", "B", "e-b", "pulse", "t1")],
    )
    result = opt.optimize_schedule(schedule, SIM, opt.Preferences(move_penalty=0.4))
    move = result["moves"][0]
    assert move["raw_cost_saved"] == pytest.approx(0.5)
    assert move["objective_delta"] == pytest.approx(-0.1)
    assert result["initial_cost"] == pytest.approx(0.5)
    assert result["optimized_cost"] == 0.0
    assert result["after"]["churn"] == 1
    assert result["after"]["penalty"] == pytest.approx(0.4)
    assert result["after"]["objective"] == pytest.approx(0.4)
    assert result["improvement"] == pytest.approx(0.1), "improvement follows the objective"
    assert result["improved"] is True
    assert result["percent_improvement"] == pytest.approx(0.2)


def test_a_swap_is_charged_for_both_acts_it_moves():
    result = opt.optimize_schedule(full_grid_schedule(), make_sims(SWAP_TAGS))
    assert result["before"]["raw_cost"] == pytest.approx(1.0)
    move = result["moves"][0]
    assert move["kind"] == "swap"
    assert set(move["moved_act_ids"]) == {"a", "c"}
    assert len(result["moved_acts"]) == 2
    assert result["after"]["churn"] == 2
    assert result["optimized_cost"] == 0.0
    assert len(result["moves"]) == 1, "this swap separates both clashing pairs at once"
    assert {entry["act_id"] for entry in result["moved_acts"]} == {"a", "c"}


def test_churn_penalty_can_be_why_a_clash_survives_a_full_grid():
    sims = make_sims(SWAP_TAGS)
    blocked = opt.optimize_schedule(full_grid_schedule(), sims, opt.Preferences(move_penalty=0.6))
    assert blocked["moves"] == []
    assert blocked["improved"] is False
    assert blocked["after"]["raw_cost"] == pytest.approx(1.0)
    # no relocation exists on a full grid, so only a 2-act swap could help
    assert {entry["kind"] for entry in blocked["unresolved"]} == {"local_optimum"}

    worth_it = opt.optimize_schedule(full_grid_schedule(), sims, opt.Preferences(move_penalty=0.2))
    assert len(worth_it["moves"]) == 1
    assert worth_it["after"]["churn"] == 2
    assert worth_it["after"]["penalty"] == pytest.approx(0.4)
    assert worth_it["improvement"] == pytest.approx(0.6)


def test_move_limit_stops_early_and_says_an_improving_move_remains():
    result = opt.optimize_schedule(
        priority_schedule(), make_sims(PRIORITY_TAGS), opt.Preferences(max_moves=1)
    )
    assert len(result["moves"]) == 1
    assert result["limit_reached"] is True
    assert result["after"]["raw_cost"] > 0
    assert {entry["kind"] for entry in result["unresolved"]} == {"move_limit"}
    assert all("an improving move still exists" in entry["reason"] for entry in result["unresolved"])


def test_zero_move_limit_proposes_nothing():
    result = opt.optimize_schedule(
        priority_schedule(), make_sims(PRIORITY_TAGS), opt.Preferences(max_moves=0)
    )
    assert result["moves"] == []
    assert result["limit_reached"] is True
    assert result["improved"] is False
    assert result["after"] == result["before"]


def test_limit_reached_when_the_last_pass_accepts_the_final_allowed_move(monkeypatch):
    """The search may spend its whole move budget on the final pass.

    `MAX_PASSES` and the largest move cap are the same number, so the top-of-pass
    cap check never runs in that case. The report must still say the cap stopped it.
    """
    monkeypatch.setattr(opt, "MAX_PASSES", 2)
    result = opt.optimize_schedule(
        demo_schedule(), build_demo_similarities(), opt.Preferences(max_moves=2)
    )
    assert len(result["moves"]) == 2, "the demo has more improving moves than this budget"
    assert result["limit_reached"] is True
    assert result["preferences"]["max_moves"] == 2


def test_move_cap_rejects_the_move_past_the_limit(monkeypatch):
    monkeypatch.setattr(opt, "MAX_PASSES", 5)
    sims = build_demo_similarities()
    capped = opt.optimize_schedule(demo_schedule(), sims, opt.Preferences(max_moves=2))
    assert len(capped["moves"]) == 2
    assert capped["limit_reached"] is True
    # The same lineup has a third improving move; it must not sneak past the cap.
    wider = opt.optimize_schedule(demo_schedule(), sims, opt.Preferences(max_moves=3))
    assert len(wider["moves"]) == 3


def test_out_of_range_preferences_are_clamped_and_echoed():
    result = opt.optimize_schedule(
        priority_schedule(),
        make_sims(PRIORITY_TAGS),
        opt.Preferences(
            high_affinity_threshold=5.0,
            high_affinity_weight=50.0,
            move_penalty=-2.0,
            max_moves=99_999,
        ),
    )
    assert result["preferences"] == {
        "high_affinity_threshold": 1.0,
        "high_affinity_weight": 10.0,
        "move_penalty": 0.0,
        "max_moves": opt.MAX_PASSES,
    }


def test_unresolved_clashes_name_the_side_that_is_locked():
    both_fixed = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1", fixed=True),
         act("2", "B", "e-b", "pulse", "t1", fixed=True)],
    )
    result = opt.optimize_schedule(both_fixed, SIM)
    entry = result["unresolved"][0]
    assert entry["kind"] == "both_fixed"
    assert entry["similarity"] == pytest.approx(0.5)
    assert entry["high_affinity"] is True, "0.5 is at or above the default threshold"
    assert "locked headliner" in entry["reason"]

    pinned = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "A", "e-a", "main", "t1", fixed=True),
         act("2", "B", "e-b", "pulse", "t1", allowed_stages=["pulse"], allowed_slots=["t1"])],
    )
    result = opt.optimize_schedule(pinned, SIM)
    entry = result["unresolved"][0]
    assert entry["kind"] == "no_legal_cell"
    assert (entry["fixed_act"], entry["movable_act"]) == ("1", "2")
    assert "B" in entry["reason"] and "A" in entry["reason"]


def test_a_headliner_clash_that_is_priced_out_says_a_move_was_available():
    """Separating them was legal — the priorities said it was not worth it."""
    schedule = make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("1", "Headliner", "e-a", "main", "t1", fixed=True),
         act("2", "Support", "e-b", "pulse", "t1")],
    )
    result = opt.optimize_schedule(schedule, SIM, opt.Preferences(move_penalty=0.6))
    entry = result["unresolved"][0]
    assert entry["kind"] == "worse_objective"
    assert (entry["fixed_act"], entry["movable_act"]) == ("1", "2")
    assert "separate these two" in entry["reason"]


# --- validation ---

SWAP_TAGS = {
    "e-a": ["a", "b", "c"],
    "e-b": ["a", "b", "d"],
    "e-c": ["m", "n", "o"],
    "e-d": ["m", "n", "p"],
}


def full_grid_schedule():
    """Every cell taken: relocations are impossible, only swaps remain."""
    return make_schedule(
        BASIC_STAGES, BASIC_SLOTS,
        [act("a", "A", "e-a", "main", "t1"),
         act("b", "B", "e-b", "pulse", "t1"),
         act("c", "C", "e-c", "main", "t2"),
         act("d", "D", "e-d", "pulse", "t2")],
    )


def demo_models():
    return (
        [Stage(**stage) for stage in demo_data.DEMO_FESTIVAL["stages"]],
        [Slot(**slot) for slot in demo_data.DEMO_FESTIVAL["slots"]],
        [Act(**entry) for entry in demo_data.DEMO_FESTIVAL["acts"]],
    )


def test_from_payload_reports_every_problem_at_once():
    with pytest.raises(opt.ScheduleError) as excinfo:
        make_schedule(
            ["main", "main"],
            [("t1", "17:00", "18:00"), ("t2", "18:00", "17:00"), ("t3", "99:00", "20:00")],
            [act("1", "A", "e-a", "nope", "t1"),
             act("1", "B", "e-b", "main", "t1"),
             act("2", "C", "e-c", "main", "t1", duration=90, allowed_stages=["ghost"])],
        )
    issues = excinfo.value.issues
    assert str(excinfo.value) == issues[0]
    assert len(issues) >= 6
    for needle in (
        "Duplicate stage id",
        "must end after it starts",
        "Invalid time",
        "unknown stage",
        "Duplicate act id",
        "does not fit",
        "double-booked",
        "unknown allowed stage",
    ):
        assert any(needle in text for text in issues), needle


def test_validate_schedule_checks_without_moving_or_scoring():
    stages, slots, acts = demo_models()
    result = opt.validate_schedule(stages, slots, acts)
    assert result["valid"] is True
    assert result["issues"] == []
    assert result["acts"] == 20
    assert result["fixed_acts"], "the demo festival locks its headliners"
    assert result["overlapping_pairs"] > 0
    assert result["constraints_checked"] == list(opt.HARD_CONSTRAINTS)
    assert set(result) == {
        "valid", "issues", "acts", "fixed_acts", "overlapping_pairs", "constraints_checked"
    }, "validation reports constraints, not scores"


def test_validate_schedule_collects_problems_from_a_broken_lineup():
    result = opt.validate_schedule(
        [Stage(id="main", name="Main")],
        [Slot(id="t1", label="17:00", start="17:00", end="18:00")],
        [Act(id="1", name="A", entity_id="e-a", stage_id="main", slot_id="t1", duration_min=90),
         Act(id="2", name="B", entity_id="e-b", stage_id="main", slot_id="t1")],
    )
    assert result["valid"] is False
    assert result["acts"] == 2
    assert len(result["issues"]) == 2
    assert any("does not fit" in text for text in result["issues"])
    assert any("double-booked" in text for text in result["issues"])


def test_validate_schedule_rejects_a_move_that_breaks_allowed_stages():
    result = opt.validate_schedule(
        [Stage(id="main", name="Main"), Stage(id="tent", name="Tent")],
        [Slot(id="t1", label="17:00", start="17:00", end="18:00")],
        [Act(id="1", name="A", entity_id="e-a", stage_id="tent", slot_id="t1",
             allowed_stages=["tent"])],
    )
    assert result["valid"] is True

    result = opt.validate_schedule(
        [Stage(id="main", name="Main"), Stage(id="tent", name="Tent")],
        [Slot(id="t1", label="17:00", start="17:00", end="18:00")],
        [Act(id="1", name="A", entity_id="e-a", stage_id="main", slot_id="t1",
             allowed_stages=["tent"])],
    )
    assert result["valid"] is False
    assert result["issues"] == ["Stage 'main' is not allowed for 'A'."]


def test_optimized_proposal_passes_standalone_validation():
    """Even with aggressive priorities, the proposal is a legal festival."""
    stages, slots, acts = demo_models()
    result = opt.optimize_schedule(demo_schedule(), build_demo_similarities(), HIGH)
    proposed = [Act(**act.__dict__) for act in result["optimized_acts"]]

    check = opt.validate_schedule(stages, slots, proposed)
    assert check["valid"] is True, check["issues"]
    assert result["improved"] is True
    assert result["after"]["objective"] < result["before"]["objective"]

    fixed_before = {act.id: (act.stage_id, act.slot_id) for act in acts if act.fixed}
    cells = {entry.id: (entry.stage_id, entry.slot_id) for entry in proposed}
    assert all(cells[act_id] == cell for act_id, cell in fixed_before.items())
    for original, entry in zip(acts, proposed):
        if original.allowed_stages:
            assert entry.stage_id in original.allowed_stages
        if original.allowed_slots:
            assert entry.slot_id in original.allowed_slots


def test_preferences_describe_only_what_is_active():
    assert opt.Preferences().describe().startswith("Plain sum")
    text = opt.Preferences(high_affinity_weight=2.0, move_penalty=0.25).describe()
    assert "2.0x" in text and "0.25" in text and "at most" in text
    assert "Plain sum" not in text
