"""Schedule clash analysis and a greedy/local-search optimizer.

Objective (what the search minimizes) is configurable through `Preferences`:

    objective(schedule) = Σ  w(p) · similarity(p)  +  move_penalty · acts_moved
                          over overlapping pairs on different stages

where `w(p)` is `high_affinity_weight` for a pair whose similarity is at or
above `high_affinity_threshold` and 1 otherwise. `acts_moved` counts acts whose
(stage, slot) differs from the schedule we started from, so asking for few
changes makes the optimizer spend a change only when it buys more than it costs.

The raw similarity sum (no weighting, no penalty) is always reported next to the
objective, so the effect of the priorities is inspectable rather than baked into
one opaque number.

Hard constraints preserved:
- Each act has exactly one (stage, slot) assignment.
- At most one act per (stage, slot) cell.
- An act's duration must fit inside its slot.
- Fixed acts never move.
- Optional per-act allowed_stages / allowed_slots are respected.

Optimization is steepest-descent local search over single relocations and
pairwise swaps; it never silently changes hard constraints, and it reports the
measured objective before and after instead of claiming progress.
"""
import logging
from dataclasses import dataclass, field

from . import similarity as similarity_engine

logger = logging.getLogger("clashdoctor.optimizer")

OBJECTIVE_DESCRIPTION = (
    "Estimated taste similarity (documented multi-signal blend; genre .55 / "
    "audience .20 / style .15 / other music .10, renormalized over the tag "
    "categories both artists have) summed over pairs of artists performing "
    "during overlapping intervals on different stages. Pairs with no comparable "
    "category are excluded from the objective and reported as missing data."
)


MAX_PASSES = 200  # also the largest number of moves the search may propose


@dataclass
class Preferences:
    """User-settable optimization priorities. Every field is echoed in the report.

    Defaults are neutral (no weighting, no penalty, no effective move cap) so a
    request without preferences behaves exactly like a plain similarity sum.
    """

    high_affinity_threshold: float = 0.4  # pairs at or above this are "high affinity"
    high_affinity_weight: float = 1.0  # how much those pairs count for
    move_penalty: float = 0.0  # objective cost of moving one act
    max_moves: int = MAX_PASSES  # how many changes the search may propose

    def describe(self) -> str:
        # The cap is a real part of the objective the user asked for, so a
        # shortened search must never be described as plain and uncapped.
        capped = self.max_moves != MAX_PASSES
        if self.high_affinity_weight == 1.0 and self.move_penalty == 0.0 and not capped:
            return (
                "Plain sum of estimated similarity: no pair is weighted above "
                "another and moving an act costs nothing."
            )
        parts = []
        if self.high_affinity_weight != 1.0:
            parts.append(
                f"pairs with similarity >= {self.high_affinity_threshold} count "
                f"{self.high_affinity_weight}x"
            )
        if self.move_penalty:
            parts.append(f"each moved act costs {self.move_penalty} of the objective")
        if not parts:
            parts.append("no pair is weighted above another and moving an act costs nothing")
        parts.append(f"at most {self.max_moves} moves")
        return "; ".join(parts) + "."

    def clamp(self) -> "Preferences":
        """Keep out-of-range values sane rather than failing the request silently."""
        return Preferences(
            high_affinity_threshold=min(max(self.high_affinity_threshold, 0.0), 1.0),
            high_affinity_weight=min(max(self.high_affinity_weight, 1.0), 10.0),
            move_penalty=min(max(self.move_penalty, 0.0), 1.0),
            max_moves=min(max(int(self.max_moves), 0), MAX_PASSES),
        )


DEFAULT_PREFERENCES = Preferences()


class ScheduleError(ValueError):
    """Invalid schedule supplied by the caller.

    Carries every problem found, not just the first, so a validation report can
    list them all without re-running the checks one by one.
    """

    def __init__(self, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.issues = issues or [message]


def parse_hhmm(value: str) -> int:
    """Parse 'HH:MM' (24h) into minutes since midnight. '24:00' is end-of-day."""
    try:
        hours, minutes = value.strip().split(":")
        parsed = int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError) as exc:
        raise ScheduleError(f"Invalid time '{value}'; expected HH:MM.") from exc
    if hours == "24" and minutes == "00":
        return 24 * 60
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        raise ScheduleError(f"Invalid time '{value}'; expected HH:MM (24h).")
    return parsed


@dataclass
class SlotState:
    id: str
    label: str
    start_min: int
    end_min: int

    @property
    def duration_min(self) -> int:
        return self.end_min - self.start_min


@dataclass
class ActState:
    id: str
    name: str
    entity_id: str
    stage_id: str
    slot_id: str
    duration_min: int = 60
    fixed: bool = False
    allowed_stages: list | None = None
    allowed_slots: list | None = None


@dataclass
class Schedule:
    stages: dict = field(default_factory=dict)  # id -> name
    slots: dict = field(default_factory=dict)  # id -> SlotState
    acts: list = field(default_factory=list)  # list[ActState]

    @classmethod
    def from_payload(cls, payload_stages, payload_slots, payload_acts) -> "Schedule":
        issues: list[str] = []
        stages = {}
        for stage in payload_stages:
            if stage.id in stages:
                issues.append(f"Duplicate stage id '{stage.id}'.")
            stages[stage.id] = stage.name
        slots = {}
        for slot in payload_slots:
            if slot.id in slots:
                issues.append(f"Duplicate slot id '{slot.id}'.")
                continue
            try:
                start = parse_hhmm(slot.start)
                end = parse_hhmm(slot.end)
            except ScheduleError as exc:
                issues.append(str(exc))
                continue
            if end <= start:
                issues.append(f"Slot '{slot.id}' must end after it starts.")
                continue
            slots[slot.id] = SlotState(slot.id, slot.label or slot.id, start, end)

        seen_ids: set = set()
        occupied: set = set()
        acts = []
        for act in payload_acts:
            if act.id in seen_ids:
                issues.append(f"Duplicate act id '{act.id}'.")
            seen_ids.add(act.id)
            slot = slots.get(act.slot_id)
            if act.stage_id not in stages:
                issues.append(
                    f"Act '{act.name}' references unknown stage '{act.stage_id}'."
                )
            if slot is None:
                issues.append(f"Act '{act.name}' references unknown slot '{act.slot_id}'.")
            elif act.duration_min > slot.duration_min:
                issues.append(
                    f"Act '{act.name}' ({act.duration_min} min) does not fit in slot "
                    f"'{act.slot_id}' ({slot.duration_min} min)."
                )
            if act.stage_id in stages and slot is not None:
                cell = (act.stage_id, act.slot_id)
                if cell in occupied:
                    issues.append(
                        f"Stage '{act.stage_id}' slot '{act.slot_id}' is double-booked "
                        f"(stage can host one act per slot)."
                    )
                occupied.add(cell)
            for stage_id in act.allowed_stages or []:
                if stage_id not in stages:
                    issues.append(f"Act '{act.name}' lists unknown allowed stage '{stage_id}'.")
            for slot_id in act.allowed_slots or []:
                if slot_id not in slots:
                    issues.append(f"Act '{act.name}' lists unknown allowed slot '{slot_id}'.")
            acts.append(ActState(**act.model_dump()))

        if issues:
            raise ScheduleError(issues[0], issues)
        schedule = cls(stages, slots, acts)
        schedule.validate_assignment(acts)
        return schedule

    def validate_assignment(self, acts) -> None:
        """Re-check assignment validity for a candidate set of acts."""
        issues: list[str] = []
        occupied: set = set()
        for act in acts:
            slot = self.slots.get(act.slot_id)
            if act.stage_id not in self.stages:
                issues.append(
                    f"Act '{act.name}' references unknown stage '{act.stage_id}'."
                )
            if slot is None:
                issues.append(f"Act '{act.name}' references unknown slot '{act.slot_id}'.")
            elif act.duration_min > slot.duration_min:
                issues.append(
                    f"Act '{act.name}' ({act.duration_min} min) does not fit in slot "
                    f"'{act.slot_id}' ({slot.duration_min} min)."
                )
            cell = (act.stage_id, act.slot_id)
            if cell in occupied:
                issues.append(f"Stage '{act.stage_id}' slot '{act.slot_id}' is double-booked.")
            occupied.add(cell)
            if act.allowed_stages is not None and act.stage_id not in act.allowed_stages:
                issues.append(f"Stage '{act.stage_id}' is not allowed for '{act.name}'.")
            if act.allowed_slots is not None and act.slot_id not in act.allowed_slots:
                issues.append(f"Slot '{act.slot_id}' is not allowed for '{act.name}'.")
        # Different slots can still overlap in time. On different stages that is
        # the clash the app is about; on one stage it is a double booking even
        # though each act owns a distinct cell.
        by_stage: dict = {}
        for act in acts:
            if act.stage_id in self.stages and act.slot_id in self.slots:
                by_stage.setdefault(act.stage_id, []).append(act)
        for stage_id, stage_acts in by_stage.items():
            for index, act_a in enumerate(stage_acts):
                for act_b in stage_acts[index + 1:]:
                    if act_a.slot_id == act_b.slot_id:
                        continue  # already reported as the same double-booked cell
                    start_a, end_a = self.interval(act_a)
                    start_b, end_b = self.interval(act_b)
                    if start_a < end_b and start_b < end_a:
                        issues.append(
                            f"Stage '{stage_id}' has overlapping sets: '{act_a.name}' "
                            f"(slot '{act_a.slot_id}') and '{act_b.name}' "
                            f"(slot '{act_b.slot_id}') play at the same time."
                        )
        if issues:
            raise ScheduleError(issues[0], issues)

    def interval(self, act: ActState) -> tuple[int, int]:
        slot = self.slots[act.slot_id]
        start = slot.start_min
        end = min(slot.end_min, start + act.duration_min)
        return start, end

    def overlapping_pairs(self, acts: list[ActState]) -> list[tuple[ActState, ActState]]:
        """All pairs on different stages with overlapping time intervals."""
        pairs = []
        intervals = [(act, *self.interval(act)) for act in acts]
        for i in range(len(intervals)):
            act_a, start_a, end_a = intervals[i]
            for j in range(i + 1, len(intervals)):
                act_b, start_b, end_b = intervals[j]
                if act_a.stage_id == act_b.stage_id:
                    continue
                if start_a < end_b and start_b < end_a:
                    pairs.append((act_a, act_b))
        return pairs

    def cost_and_clashes(self, acts, similarities: dict) -> tuple[float, list, list]:
        """(cost, clashing pairs, excluded pairs) for a candidate assignment.

        Clashes are overlapping pairs with similarity > 0; zero-similarity
        overlaps contribute nothing and are not reported as clashes. A pair is
        excluded only when no tag category is available on both sides — absence
        of data is never scored as zero affinity.
        """
        cost = 0.0
        clashes = []
        excluded = []
        for act_a, act_b in self.overlapping_pairs(acts):
            pair = similarities.get(self.pair_key(act_a.entity_id, act_b.entity_id))
            if pair is None or pair["taste_similarity"] is None:
                excluded.append((act_a, act_b, pair))
                continue
            value = similarity_engine.objective_similarity(pair)
            method = similarity_engine.objective_method(pair)
            cost += value
            if value > 1e-9:
                clashes.append((act_a, act_b, value, method))
        return cost, clashes, excluded

    def measure(
        self, acts, similarities: dict, prefs: Preferences, initial_cells: dict
    ) -> dict:
        """Every number the report needs for one assignment, under one set of priorities.

        `raw_cost` is the plain similarity sum; `weighted_cost` applies the
        high-affinity multiplier; `objective` adds the penalty for moved acts.
        Reporting all three keeps the priorities auditable.
        """
        raw_cost, clashes, excluded = self.cost_and_clashes(acts, similarities)
        weighted = 0.0
        high_affinity = 0
        for _a, _b, value, _method in clashes:
            if value >= prefs.high_affinity_threshold:
                weighted += value * prefs.high_affinity_weight
                high_affinity += 1
            else:
                weighted += value
        churn = self.churn(acts, initial_cells)
        return {
            "raw_cost": raw_cost,
            "weighted_cost": weighted,
            "churn": churn,
            "penalty": prefs.move_penalty * churn,
            "objective": weighted + prefs.move_penalty * churn,
            "clashes": clashes,
            "high_affinity_clashes": high_affinity,
            "excluded": excluded,
        }

    @staticmethod
    def churn(acts, initial_cells: dict) -> int:
        """Acts that are no longer in the cell they started in."""
        return sum(
            1
            for act in acts
            if initial_cells.get(act.id) != (act.stage_id, act.slot_id)
        )

    @staticmethod
    def pair_key(entity_a: str, entity_b: str) -> tuple:
        return tuple(sorted((entity_a, entity_b)))


def _can_place(
    schedule: Schedule,
    act: ActState,
    stage_id: str,
    slot_id: str,
    occupied: set,
    acts=None,
) -> bool:
    if act.allowed_stages is not None and stage_id not in act.allowed_stages:
        return False
    if act.allowed_slots is not None and slot_id not in act.allowed_slots:
        return False
    if (stage_id, slot_id) in occupied:
        return False
    if act.duration_min > schedule.slots[slot_id].duration_min:
        return False
    if acts is not None:
        probe = ActState(**{**act.__dict__, "stage_id": stage_id, "slot_id": slot_id})
        start, end = schedule.interval(probe)
        for other in acts:
            if other.id == act.id or other.stage_id != stage_id:
                continue
            if other.slot_id == slot_id:
                continue  # same cell is already rejected by `occupied`
            other_start, other_end = schedule.interval(other)
            if start < other_end and other_start < end:
                return False
    return True


def _explain_move(moved_ids: set, before_clashes, after_clashes, saved: float) -> str:
    """Human-readable explanation of what a move fixed, from clash lists."""
    after_keys = {(a.entity_id, b.entity_id) for a, b, _, _ in after_clashes}
    removed = [
        (a, b, value)
        for a, b, value, _ in before_clashes
        if (a.entity_id, b.entity_id) not in after_keys
        and (a.id in moved_ids or b.id in moved_ids)
    ]
    if removed:
        parts = []
        for a, b, value in removed:
            other = b if a.id in moved_ids else a
            parts.append(f"{other.name} (similarity {value:.3f})")
        return f"Removes simultaneous-performance overlaps with {', '.join(parts)}."
    return (
        f"Rearranges the schedule to reduce total clash cost by {saved:.3f} "
        "(no single named pair removed)."
    )


def _best_action(schedule: Schedule, acts, similarities, prefs, initial_cells, current: float):
    """Steepest single relocation or swap against `current` objective.

    Returns (delta, action). action is ("move", act_id, stage, slot) or
    ("swap", id_a, id_b); delta is 0 and action None when nothing improves.
    """
    occupied = {(act.stage_id, act.slot_id) for act in acts}
    best_delta = 0.0
    best_action = None

    for act in acts:
        if act.fixed:
            continue
        for stage_id in schedule.stages:
            for slot_id in schedule.slots:
                if (stage_id, slot_id) == (act.stage_id, act.slot_id):
                    continue
                if not _can_place(schedule, act, stage_id, slot_id, occupied, acts):
                    continue
                candidate = [
                    ActState(**{**a.__dict__, "stage_id": stage_id, "slot_id": slot_id})
                    if a.id == act.id
                    else a
                    for a in acts
                ]
                delta = (
                    schedule.measure(candidate, similarities, prefs, initial_cells)["objective"]
                    - current
                )
                if delta < best_delta - 1e-12:
                    best_delta = delta
                    best_action = ("move", act.id, stage_id, slot_id)

    for i in range(len(acts)):
        act_i = acts[i]
        if act_i.fixed:
            continue
        for j in range(i + 1, len(acts)):
            act_j = acts[j]
            if act_j.fixed:
                continue
            if (act_i.stage_id, act_i.slot_id) == (act_j.stage_id, act_j.slot_id):
                continue
            if act_i.stage_id == act_j.stage_id:
                target_i = ActState(
                    **{**act_i.__dict__, "stage_id": act_j.stage_id, "slot_id": act_j.slot_id}
                )
                target_j = ActState(
                    **{**act_j.__dict__, "stage_id": act_i.stage_id, "slot_id": act_i.slot_id}
                )
                start_i, end_i = schedule.interval(target_i)
                start_j, end_j = schedule.interval(target_j)
                if start_i < end_j and start_j < end_i:
                    continue
            occupied_without_pair = occupied - {
                (act_i.stage_id, act_i.slot_id),
                (act_j.stage_id, act_j.slot_id),
            }
            if not _can_place(
                schedule, act_i, act_j.stage_id, act_j.slot_id, occupied_without_pair, acts
            ):
                continue
            if not _can_place(
                schedule, act_j, act_i.stage_id, act_i.slot_id, occupied_without_pair, acts
            ):
                continue
            candidate = []
            for a in acts:
                if a.id == act_i.id:
                    candidate.append(
                        ActState(
                            **{**a.__dict__, "stage_id": act_j.stage_id, "slot_id": act_j.slot_id}
                        )
                    )
                elif a.id == act_j.id:
                    candidate.append(
                        ActState(
                            **{**a.__dict__, "stage_id": act_i.stage_id, "slot_id": act_i.slot_id}
                        )
                    )
                else:
                    candidate.append(a)
            delta = (
                schedule.measure(candidate, similarities, prefs, initial_cells)["objective"]
                - current
            )
            if delta < best_delta - 1e-12:
                best_delta = delta
                best_action = ("swap", act_i.id, act_j.id)

    return best_delta, best_action


def _escape_cells(schedule: Schedule, acts, movable, blocker) -> list:
    """Cells `movable` could legally take that also stop it overlapping `blocker`."""
    occupied = {(a.stage_id, a.slot_id) for a in acts} - {(movable.stage_id, movable.slot_id)}
    blocker_start, blocker_end = schedule.interval(blocker)
    escapes = []
    for stage_id in schedule.stages:
        for slot_id in schedule.slots:
            if (stage_id, slot_id) == (movable.stage_id, movable.slot_id):
                continue
            if not _can_place(schedule, movable, stage_id, slot_id, occupied, acts):
                continue
            probe = ActState(**{**movable.__dict__, "stage_id": stage_id, "slot_id": slot_id})
            start, end = schedule.interval(probe)
            if start < blocker_end and blocker_start < end:
                continue
            escapes.append((stage_id, slot_id))
    return escapes


def _unresolved_reason(
    schedule: Schedule,
    acts,
    act_a,
    act_b,
    value: float,
    prefs: Preferences,
    improving_move_exists: bool,
    limit_reached: bool,
) -> dict:
    """Why this overlap is still there — from the checks we actually ran."""
    entry = {
        "a_id": act_a.id,
        "b_id": act_b.id,
        "similarity": round(value, 4),
        "high_affinity": value >= prefs.high_affinity_threshold,
    }
    if act_a.fixed and act_b.fixed:
        entry["kind"] = "both_fixed"
        entry["reason"] = (
            "Both acts are fixed; the optimizer never moves a locked headliner."
        )
        return entry
    if act_a.fixed or act_b.fixed:
        movable = act_b if act_a.fixed else act_a
        blocker = act_a if act_a.fixed else act_b
        escapes = _escape_cells(schedule, acts, movable, blocker)
        entry["fixed_act"] = blocker.id
        entry["movable_act"] = movable.id
        if not escapes:
            entry["kind"] = "no_legal_cell"
            entry["reason"] = (
                f"'{movable.name}' is the only movable side and no legal cell avoids "
                f"'{blocker.name}''s set time (fixed stage/slot, duration or "
                "double-booking rules)."
            )
        else:
            entry["kind"] = "worse_objective"
            entry["reason"] = (
                f"{len(escapes)} cell(s) would separate these two, but every schedule "
                "reached from here by one move or swap scores worse on the current "
                "priorities, so the move was not proposed."
            )
        return entry
    if limit_reached:
        entry["kind"] = "move_limit"
        entry["reason"] = (
            f"Stopped at the {prefs.max_moves}-move limit"
            + ("; an improving move still exists." if improving_move_exists else ".")
        )
        return entry
    entry["kind"] = "local_optimum"
    entry["reason"] = (
        "No single relocation or swap of either act lowers the objective — this pair "
        "is only separable by a change that costs more elsewhere (or by more moves "
        "than the search will bundle)."
    )
    return entry


def optimize_schedule(schedule: Schedule, similarities: dict, prefs: Preferences | None = None) -> dict:
    """Steepest-descent local search on the prioritized objective. Returns a report."""
    prefs = (prefs or DEFAULT_PREFERENCES).clamp()
    acts = [act for act in schedule.acts]
    initial_cells = {act.id: (act.stage_id, act.slot_id) for act in acts}

    before = schedule.measure(acts, similarities, prefs, initial_cells)
    state = before
    moves = []
    limit_reached = False

    for _pass in range(MAX_PASSES):
        if len(moves) >= prefs.max_moves:
            limit_reached = True
            break
        delta, best_action = _best_action(
            schedule, acts, similarities, prefs, initial_cells, state["objective"]
        )
        if best_action is None:
            break

        before_moves, before_clashes, _ = schedule.cost_and_clashes(acts, similarities)
        occupied = {(act.stage_id, act.slot_id) for act in acts}
        # Rebuilt every pass: each applied move replaces act objects with new
        # states, so a stale lookup would move an act to a cell it vacated
        # earlier and double-book it.
        by_id = {act.id: act for act in acts}

        if best_action[0] == "move":
            _, act_id, new_stage, new_slot = best_action
            act = by_id[act_id]
            move = {
                "act_id": act.id,
                "act_name": act.name,
                "moved_act_ids": [act.id],
                "from_stage": act.stage_id,
                "from_slot": act.slot_id,
                "to_stage": new_stage,
                "to_slot": new_slot,
                "kind": "relocate",
            }
            acts = [
                ActState(**{**a.__dict__, "stage_id": new_stage, "slot_id": new_slot})
                if a.id == act_id
                else a
                for a in acts
            ]
        else:
            _, id_a, id_b = best_action
            act_a, act_b = by_id[id_a], by_id[id_b]
            move = {
                "act_id": act_a.id,
                "act_name": f"{act_a.name} <-> {act_b.name}",
                "moved_act_ids": [act_a.id, act_b.id],
                "from_stage": act_a.stage_id,
                "from_slot": act_a.slot_id,
                "to_stage": act_b.stage_id,
                "to_slot": act_b.slot_id,
                "kind": "swap",
            }
            acts = [
                ActState(
                    **{**a.__dict__, "stage_id": act_b.stage_id, "slot_id": act_b.slot_id}
                )
                if a.id == id_a
                else ActState(
                    **{**a.__dict__, "stage_id": act_a.stage_id, "slot_id": act_a.slot_id}
                )
                if a.id == id_b
                else a
                for a in acts
            ]

        after_move = schedule.measure(acts, similarities, prefs, initial_cells)
        raw_saved = before_moves - after_move["raw_cost"]
        move["raw_cost_saved"] = round(raw_saved, 4)
        move["objective_delta"] = round(after_move["objective"] - state["objective"], 4)
        move["explanation"] = _explain_move(
            set(move["moved_act_ids"]), before_clashes, after_move["clashes"], raw_saved
        )
        moves.append(move)
        state = after_move
        # A proposal nobody can apply is worse than no proposal: re-check every
        # hard constraint after each accepted move.
        schedule.validate_assignment(acts)

    # `MAX_PASSES` and the largest move cap are the same number, so a run that
    # accepts exactly `max_moves` moves exits the loop without the top-of-pass
    # check ever firing. The cap still stopped it; say so.
    if len(moves) >= prefs.max_moves:
        limit_reached = True

    after = schedule.measure(acts, similarities, prefs, initial_cells)
    improving_move_exists = False
    if limit_reached:
        _, action = _best_action(
            schedule, acts, similarities, prefs, initial_cells, after["objective"]
        )
        improving_move_exists = action is not None

    moved_acts = [
        {
            "act_id": act.id,
            "act_name": act.name,
            "from_stage": initial_cells[act.id][0],
            "from_slot": initial_cells[act.id][1],
            "to_stage": act.stage_id,
            "to_slot": act.slot_id,
        }
        for act in acts
        if initial_cells[act.id] != (act.stage_id, act.slot_id)
    ]

    unresolved = [
        _unresolved_reason(
            schedule, acts, act_a, act_b, value, prefs, improving_move_exists, limit_reached
        )
        for act_a, act_b, value, _method in after["clashes"]
    ]

    excluded = []
    for act_a, act_b, pair in before["excluded"] + after["excluded"]:
        kind = (pair or {}).get("missing_kind")
        if kind == "disjoint_categories":
            reason = (
                "Both artists have tags, but in different categories — nothing "
                "comparable, so the pair is excluded rather than scored as 0."
            )
        else:
            reason = "Missing taste profile for at least one artist — excluded from the objective."
        entry = {"a_name": act_a.name, "b_name": act_b.name, "reason": reason}
        if entry not in excluded:
            excluded.append(entry)

    fixed_clashes = [
        {"a": a, "b": b, "value": value, "method": method}
        for a, b, value, method in after["clashes"]
        if a.fixed and b.fixed
    ]

    objective_improvement = before["objective"] - after["objective"]
    return {
        "preferences": prefs.__dict__,
        "preferences_description": prefs.describe(),
        "before": _rounded_measure(before),
        "after": _rounded_measure(after),
        "initial_cost": round(before["raw_cost"], 4),
        "optimized_cost": round(after["raw_cost"], 4),
        "improvement": round(objective_improvement, 4),
        "improved": objective_improvement > 1e-9,
        "percent_improvement": (
            round(objective_improvement / before["objective"], 4)
            if before["objective"] > 1e-9 and objective_improvement > 1e-9
            else None
        ),
        "limit_reached": limit_reached,
        "moves": moves,
        "moved_acts": moved_acts,
        "unresolved": unresolved,
        "initial_clashes": before["clashes"],
        "optimized_clashes": after["clashes"],
        "excluded_pairs": excluded,
        "fixed_clashes": fixed_clashes,
        "optimized_acts": acts,
    }


def _rounded_measure(measure: dict) -> dict:
    """Numbers for the report; the clash/excluded tuples stay out of the payload."""
    return {
        key: round(measure[key], 4)
        for key in ("raw_cost", "weighted_cost", "penalty", "objective")
    } | {
        "clashes": len(measure["clashes"]),
        "high_affinity_clashes": measure["high_affinity_clashes"],
        "churn": measure["churn"],
        "excluded": len(measure["excluded"]),
    }


HARD_CONSTRAINTS = (
    "one (stage, slot) cell per act",
    "no cell hosts two acts",
    "no two acts overlap in time on one stage",
    "set duration fits its slot",
    "stage/slot references exist",
    "allowed_stages and allowed_slots respected",
    "fixed acts keep their assigned cell",
)


def validate_schedule(payload_stages, payload_slots, payload_acts) -> dict:
    """Check a schedule against every hard constraint. Nothing is moved or scored."""
    try:
        schedule = Schedule.from_payload(payload_stages, payload_slots, payload_acts)
    except ScheduleError as exc:
        return {
            "valid": False,
            "issues": exc.issues,
            "acts": len(payload_acts),
            "constraints_checked": list(HARD_CONSTRAINTS),
        }

    fixed = [act for act in schedule.acts if act.fixed]
    return {
        "valid": True,
        "issues": [],
        "acts": len(schedule.acts),
        "fixed_acts": [act.name for act in fixed],
        "overlapping_pairs": len(schedule.overlapping_pairs(schedule.acts)),
        "constraints_checked": list(HARD_CONSTRAINTS),
    }


def assign_schedule(payload_stages, payload_slots, payload_acts) -> dict:
    """Build a usable schedule for a lineup by greedy placement.

    Acts with an assigned (stage, slot) keep their cell when it is valid;
    acts with an empty or no-longer-valid cell (e.g. the stage/slot was
    removed) are placed into free cells slot-by-slot, stage-by-stage.
    Fixed acts always keep their cell and raise if it became invalid.

    Returns {"acts": [...], "note": str}. Raises ScheduleError when the
    grid has no room for every act (no partial schedules).
    """
    schedule = Schedule.from_payload(payload_stages, payload_slots, [])

    occupied: set = set()
    placed: list[ActState] = []
    unplaced: list[ActState] = []
    seen_ids: set = set()

    for act in payload_acts:
        if act.id in seen_ids:
            raise ScheduleError(f"Duplicate act id '{act.id}'.")
        seen_ids.add(act.id)
        state = ActState(**act.model_dump())
        if act.allowed_stages is not None:
            for stage_id in act.allowed_stages:
                if stage_id not in schedule.stages:
                    raise ScheduleError(
                        f"Act '{act.name}' lists unknown allowed stage '{stage_id}'."
                    )
        if act.allowed_slots is not None:
            for slot_id in act.allowed_slots:
                if slot_id not in schedule.slots:
                    raise ScheduleError(
                        f"Act '{act.name}' lists unknown allowed slot '{slot_id}'."
                    )
        cell = (state.stage_id, state.slot_id)
        has_cell = state.stage_id in schedule.stages and state.slot_id in schedule.slots
        if state.fixed and not has_cell:
            raise ScheduleError(
                f"Fixed act '{act.name}' is assigned to a stage or slot that no "
                "longer exists; fixed acts cannot be moved."
            )
        if state.fixed and has_cell and cell in occupied:
            raise ScheduleError(
                f"Fixed act '{act.name}' shares a cell with another act; "
                "fixed acts cannot be moved."
            )
        if has_cell and cell not in occupied:
            occupied.add(cell)
            placed.append(state)
        else:
            unplaced.append(state)

    for state in unplaced:
        for slot_id in schedule.slots:
            for stage_id in schedule.stages:
                if (stage_id, slot_id) in occupied:
                    continue
                if not _can_place(schedule, state, stage_id, slot_id, occupied, placed):
                    continue
                occupied.add((stage_id, slot_id))
                state.stage_id = stage_id
                state.slot_id = slot_id
                placed.append(state)
                break
            else:
                continue
            break
        else:
            raise ScheduleError(
                f"No free cell for '{state.name}': the grid holds "
                f"{len(schedule.stages) * len(schedule.slots)} acts maximum."
            )

    schedule.validate_assignment(placed)
    if unplaced:
        note = (
            f"{len(unplaced)} act(s) had no valid cell and were placed greedily (first free "
            "cell, slot by slot). Run Optimize to reduce clashes."
        )
    else:
        note = "Every act already had a valid cell — nothing was moved."
    return {
        "acts": placed,
        "note": note,
    }
