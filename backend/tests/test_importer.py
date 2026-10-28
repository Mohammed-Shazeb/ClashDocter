"""Tests for CSV / pasted-schedule import parsing and validation."""
import pytest

from app import importer


def parse(text):
    return importer.parse_lineup(text)


def errors(result):
    return [i for i in result["issues"] if i["severity"] == "error"]


def messages(result, severity="error"):
    return [i["message"] for i in result["issues"] if i["severity"] == severity]


# --- accepted formats ---

def test_csv_with_header_maps_columns():
    result = parse(
        "artist,stage,start,end,duration_min,fixed\n"
        "Radiohead,Main Stage,19:00,20:00,60,no\n"
        "Muse,Main Stage,21:00,22:30,75,yes\n"
    )
    assert result["valid"] is True
    assert result["source_format"] == "csv"
    assert [s["name"] for s in result["stages"]] == ["Main Stage"]
    assert [(s["start"], s["end"]) for s in result["slots"]] == [
        ("19:00", "20:00"),
        ("21:00", "22:30"),
    ]
    acts = {a["name"]: a for a in result["acts"]}
    assert acts["Radiohead"]["duration_min"] == 60
    assert acts["Radiohead"]["fixed"] is False
    assert acts["Muse"]["duration_min"] == 75
    assert acts["Muse"]["fixed"] is True


def test_csv_header_aliases_are_recognised():
    result = parse("Act,Venue,Begin,Finish,Set Length,Locked\nRadiohead,Main,19:00,20:00,60,yes\n")
    assert result["valid"] is True
    act = result["acts"][0]
    assert act["name"] == "Radiohead"
    assert act["stage_name"] == "Main"
    assert act["duration_min"] == 60
    assert act["fixed"] is True


def test_csv_without_header_uses_positions():
    result = parse("Radiohead,Main Stage,19:00,20:00,60\nMuse,Pulse Stage,19:00,20:00,45\n")
    assert result["valid"] is True
    assert len(result["acts"]) == 2
    assert {a["duration_min"] for a in result["acts"]} == {60, 45}


def test_pasted_text_with_dashes_and_time_range():
    result = parse(
        "Radiohead - Main Stage - 19:00-20:00 (60 min)\n"
        "Muse — Main Stage — 21:00–22:00 [headliner]\n"
    )
    assert result["valid"] is True
    assert result["source_format"] == "text"
    acts = {a["name"]: a for a in result["acts"]}
    assert acts["Radiohead"]["duration_min"] == 60
    assert acts["Muse"]["fixed"] is True, "bracketed headliner marker locks the act"
    assert acts["Muse"]["stage_name"] == "Main Stage"


def test_pasted_text_with_double_spaces():
    result = parse("Radiohead  Main Stage  19:00  20:00  60\n")
    assert result["valid"] is True
    assert result["acts"][0]["name"] == "Radiohead"


def test_tab_separated_rows():
    result = parse("Radiohead\tMain Stage\t19:00\t20:00\t60\nMuse\tMain Stage\t20:00\t21:00\t45\n")
    assert result["valid"] is True
    assert len(result["slots"]) == 2


def test_duration_units():
    result = parse(
        "artist,stage,start,end,duration\n"
        "A,Main,19:00,20:00,45min\n"
        "B,Main,20:00,21:00,1h\n"
        "C,Main,21:00,22:30,90 minutes\n"
        "D,Main,22:30,24:00,1.5h\n"
    )
    assert result["valid"] is True, messages(result)
    durations = {a["name"]: a["duration_min"] for a in result["acts"]}
    assert durations == {"A": 45, "B": 60, "C": 90, "D": 90}


def test_start_plus_duration_derives_end_time():
    result = parse("artist,stage,start,duration\nRadiohead,Main Stage,19:00,90\n")
    assert result["valid"] is True, messages(result)
    assert result["slots"][0]["start"] == "19:00"
    assert result["slots"][0]["end"] == "20:30"


def test_missing_duration_assumes_slot_length_and_reports_it():
    result = parse("Radiohead,Main Stage,19:00,20:00\n")
    assert result["valid"] is True
    assert result["acts"][0]["duration_min"] == 60
    info = messages(result, "info")
    assert info and "no explicit set length" in info[0]


def test_festival_name_from_comment():
    result = parse("# name: Reading 2026\nRadiohead,Main Stage,19:00,20:00\n")
    assert result["festival_name"] == "Reading 2026"


def test_slots_are_sorted_and_deduplicated():
    result = parse(
        "artist,stage,start,end\n"
        "A,Main,21:00,22:00\n"
        "B,Main,19:00,20:00\n"
        "C,Pulse,19:00,20:00\n"
    )
    assert [(s["start"], s["end"]) for s in result["slots"]] == [
        ("19:00", "20:00"),
        ("21:00", "22:00"),
    ]


def test_stage_ids_are_unique_for_similar_names():
    result = parse(
        "artist,stage,start,end\nA,Main Stage,19:00,20:00\nB,main stage!,19:00,20:00\n"
    )
    ids = [s["id"] for s in result["stages"]]
    assert len(ids) == len(set(ids))


def test_acts_never_carry_an_invented_entity_id():
    result = parse("Radiohead,Main Stage,19:00,20:00\nMuse,Pulse Stage,19:00,20:00\n")
    assert all(act["entity_id"] == "" for act in result["acts"])


def test_end_of_day_slot_is_allowed():
    result = parse("Radiohead,Main Stage,23:00,24:00\n")
    assert result["valid"] is True, messages(result)
    assert result["slots"][0]["end"] == "24:00"


# --- validation failures ---

def test_missing_artist_is_an_error():
    result = parse("artist,stage,start,end\n,Main Stage,19:00,20:00\n")
    assert result["valid"] is False
    assert any("Missing artist name" in m for m in messages(result))


def test_missing_stage_is_an_error():
    result = parse("artist,stage,start,end\nRadiohead,,19:00,20:00\n")
    assert result["valid"] is False
    assert any("Missing stage name" in m for m in messages(result))


def test_unparseable_time_is_an_error():
    result = parse("artist,stage,start,end\nRadiohead,Main Stage,7pm,20:00\n")
    assert result["valid"] is False
    assert any("not a 24h HH:MM time" in m for m in messages(result))


def test_out_of_range_time_is_an_error():
    result = parse("artist,stage,start,end\nRadiohead,Main Stage,25:00,26:00\n")
    assert result["valid"] is False
    assert any("not a valid 24h time" in m for m in messages(result))


def test_end_before_start_is_an_error():
    result = parse("artist,stage,start,end\nRadiohead,Main Stage,20:00,19:00\n")
    assert result["valid"] is False
    assert any("ends before it starts" in m for m in messages(result))


def test_set_longer_than_slot_is_an_error():
    result = parse("artist,stage,start,end,duration\nRadiohead,Main Stage,19:00,20:00,90\n")
    assert result["valid"] is False
    assert any("does not fit" in m for m in messages(result))


def test_absurd_duration_is_an_error():
    result = parse("artist,stage,start,end,duration\nRadiohead,Main Stage,19:00,23:00,5\n")
    assert result["valid"] is False
    assert any("outside" in m for m in messages(result))


def test_double_booking_is_reported_for_both_rows():
    result = parse(
        "artist,stage,start,end\nRadiohead,Main Stage,19:00,20:00\nMuse,Main Stage,19:00,20:00\n"
    )
    assert result["valid"] is False
    doubles = [i for i in errors(result) if "Double booking" in i["message"]]
    assert len(doubles) == 2
    assert {i["row"] for i in doubles} == {2, 3}


def test_overlapping_sets_on_one_stage_are_a_conflict():
    result = parse(
        "artist,stage,start,end\nRadiohead,Main Stage,19:00,20:30\nMuse,Main Stage,20:00,21:00\n"
    )
    assert result["valid"] is False
    assert any("Overlapping sets on Main Stage" in m for m in messages(result))


def test_same_time_on_different_stages_is_not_a_conflict():
    result = parse(
        "artist,stage,start,end\nRadiohead,Main Stage,19:00,20:00\nMuse,Pulse Stage,19:00,20:00\n"
    )
    assert result["valid"] is True, messages(result)


def test_rejected_rows_do_not_block_valid_ones():
    result = parse(
        "artist,stage,start,end\nRadiohead,Main Stage,19:00,20:00\n,Main Stage,21:00,22:00\n"
    )
    assert result["valid"] is False
    assert [a["name"] for a in result["acts"]] == ["Radiohead"]
    assert "1 row(s) rejected" in result["summary"]


def test_empty_input_raises():
    with pytest.raises(importer.ImportParseError, match="empty"):
        parse("   \n\n")


def test_header_only_input_raises():
    with pytest.raises(importer.ImportParseError, match="No schedule rows"):
        parse("artist,stage,start,end\n")


def test_oversized_input_raises():
    with pytest.raises(importer.ImportParseError, match="too large"):
        parse("x" * (importer.MAX_TEXT_BYTES + 1))


def test_too_many_rows_raises():
    rows = "".join(f"A{i},Main Stage,19:00,20:00\n" for i in range(importer.MAX_ROWS + 1))
    with pytest.raises(importer.ImportParseError, match="Too many rows"):
        parse(rows)


def test_imported_structure_feeds_the_schedule_assigner():
    """Parsed output must be directly usable by the existing assign endpoint."""
    from app import models, optimizer

    result = parse(
        "artist,stage,start,end,duration\n"
        "Radiohead,Main Stage,19:00,20:00,60\n"
        "Muse,Pulse Stage,19:00,20:00,60\n"
    )
    stages = [models.Stage(**s) for s in result["stages"]]
    slots = [models.Slot(**{k: v for k, v in s.items() if k != "duration_min"}) for s in result["slots"]]
    acts = [
        models.Act(
            id=a["id"], name=a["name"], entity_id=a["entity_id"],
            stage_id=a["stage_id"], slot_id=a["slot_id"],
            duration_min=a["duration_min"], fixed=a["fixed"],
        )
        for a in result["acts"]
    ]
    assigned = optimizer.assign_schedule(stages, slots, acts)
    placed = {a.name: (a.stage_id, a.slot_id) for a in assigned["acts"]}
    assert placed == {"Radiohead": ("main-stage", "t1"), "Muse": ("pulse-stage", "t1")}
