"""Festival lineup import: CSV files and pasted schedule text.

Parsing and validation are deterministic and offline — no Qloo calls happen
here. Artist names stay plain text until the user confirms a match in the
resolve step, so no artist identity is ever invented.

Accepted shapes (all optional columns except artist, stage and set time):

    artist,stage,start,end,duration_min,fixed
    Radiohead,Main Stage,19:00,20:00,60,no

    Radiohead, Main Stage, 19:00-20:00, 60min
    Radiohead — Main Stage — 19:00–20:00 (60 min) [headliner]
    Radiohead    Main Stage    19:00    20:00    60

Stage names and set times define the grid: distinct stage names become stages,
distinct (start, end) pairs become time slots.
"""
import csv
import io
import re
from dataclasses import dataclass, field

MAX_TEXT_BYTES = 200_000
MAX_ROWS = 500
MIN_DURATION = 15
MAX_DURATION = 480

_SEPARATORS = [",", "\t", ";", "|"]

_TIME_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2}):(\d{2})\s*(?:-|–|—|\bto\b|\buntil\b)\s*(\d{1,2}):(\d{2})(?!\d)",
    re.IGNORECASE,
)
_SINGLE_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_DURATION_RE = re.compile(
    r"(?<![\d:])(\d+(?:[.,]\d+)?)\s*(min|mins|minute|minutes|m|hr|hrs|hour|hours|h)\b",
    re.IGNORECASE,
)
_BARE_DURATION_RE = re.compile(r"^\d{1,3}$")

_FIXED_WORDS = {"fixed", "locked", "lock", "headliner", "pinned", "yes", "true", "y", "1"}
_FIXED_MARKER_RE = re.compile(r"[\[(]([^)\]]*)[\])]")

_HEADER_ALIASES = {
    "artist": {"artist", "artists", "name", "act", "performer", "band", "artist_name", "who"},
    "stage": {"stage", "stages", "stage_name", "venue", "tent", "room"},
    "start": {"start", "start_time", "starttime", "begin", "from", "starts_at"},
    "end": {"end", "end_time", "endtime", "finish", "to", "until", "ends_at"},
    "time": {"time", "slot", "timeslot", "time_slot", "set_time", "when", "set"},
    "duration": {
        "duration", "duration_min", "duration_mins", "duration_minutes",
        "length", "set_length", "minutes", "mins", "set_duration", "set_minutes",
    },
    "fixed": {"fixed", "locked", "lock", "headliner", "is_fixed", "pinned"},
}


class ImportParseError(ValueError):
    """Input cannot be parsed at all (empty, oversized, or no usable rows)."""


@dataclass
class _Row:
    number: int
    raw: str
    artist: str | None = None
    stage: str | None = None
    start: int | None = None
    end: int | None = None
    duration: int | None = None
    fixed: bool = False
    problems: list = field(default_factory=list)


def _hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def _minutes_of(hhmm_value: str) -> int:
    hours, minutes = hhmm_value.split(":")
    return int(hours) * 60 + int(minutes)


def _to_minutes(hour: int, minute: int) -> int | None:
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour * 60 + minute
    if hour == 24 and minute == 0:
        return 24 * 60
    return None


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return value or "stage"


def _unique_slug(base: str, taken: set) -> str:
    slug = base
    suffix = 2
    while slug in taken:
        slug = f"{base}-{suffix}"
        suffix += 1
    taken.add(slug)
    return slug


def _strip_comment_lines(text: str) -> tuple[str, str | None]:
    """Drop '#' comment lines; '# name: X' or a bare '# X' names the festival."""
    kept = []
    festival_name = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if festival_name is None:
                body = stripped.lstrip("#").strip()
                if body.lower().startswith("name:"):
                    body = body.split(":", 1)[1].strip()
                if body:
                    festival_name = body
            continue
        kept.append(line)
    return "\n".join(kept), festival_name


def _detect_delimiter(lines: list) -> str | None:
    counts = {sep: sum(line.count(sep) for line in lines[:20]) for sep in _SEPARATORS}
    if "\t" in counts and counts["\t"] > 0:
        return "\t"
    best = max(counts, key=lambda sep: counts[sep])
    return best if counts[best] > 0 else None


def _normalize_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", cell.strip().lower()).strip("_")


def _match_header(cells: list) -> dict | None:
    """Map column index -> canonical field when the row looks like a header."""
    mapping = {}
    for index, cell in enumerate(cells):
        normalized = _normalize_header(cell)
        for canonical, aliases in _HEADER_ALIASES.items():
            if normalized in aliases:
                mapping[index] = canonical
                break
    known = set(mapping.values())
    if len(known) >= 2 and "artist" in known:
        return mapping
    return None


def _parse_duration(text: str) -> int | None:
    match = _DURATION_RE.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    minutes = value * 60 if unit.startswith("h") else value
    return int(round(minutes))


def _take_duration(text: str, current: int | None) -> tuple:
    """Pull a trailing duration out of leftover text, e.g. '19:00-20:00 (60 min)'."""
    if not text or current is not None:
        return text, current
    parsed = _parse_duration(text)
    if parsed is None:
        if _BARE_DURATION_RE.match(text):
            return "", int(text)
        return text, current
    remainder = _DURATION_RE.sub(" ", text).strip(" \t-,;|()[]")
    return remainder, parsed


def _parse_time_cell(text: str) -> tuple:
    """Parse 'HH:MM' into minutes; returns (minutes, error)."""
    match = _SINGLE_TIME_RE.fullmatch(text.strip())
    if not match:
        return None, f"'{text.strip()}' is not a 24h HH:MM time"
    minutes = _to_minutes(int(match.group(1)), int(match.group(2)))
    if minutes is None:
        return None, f"'{text.strip()}' is not a valid 24h time"
    return minutes, None


def _classify_fields(fields: list) -> dict:
    """Split free-form fields into times, duration, fixed flag and text."""
    texts = []
    singles = []
    time_range = None
    duration = None
    fixed = False

    for raw in fields:
        value = raw.strip()
        if not value:
            continue
        lowered = value.lower().strip("[](){}*")
        if lowered in _FIXED_WORDS:
            fixed = True
            continue

        marker = _FIXED_MARKER_RE.search(value)
        if marker and marker.group(1).strip().lower() in _FIXED_WORDS:
            fixed = True
            value = _FIXED_MARKER_RE.sub(" ", value).strip(" \t-,;|")
            if not value:
                continue

        match = _TIME_RANGE_RE.search(value)
        if match:
            time_range = tuple(int(g) for g in match.groups())
            remainder = _TIME_RANGE_RE.sub(" ", value).strip(" \t-,;|()[]")
            remainder, duration = _take_duration(remainder, duration)
            if remainder:
                texts.append(remainder)
            continue

        parsed = _parse_duration(value)
        if parsed is not None:
            duration = parsed
            remainder = _DURATION_RE.sub(" ", value).strip(" \t-,;|()[]")
            if remainder and not _BARE_DURATION_RE.match(remainder):
                texts.append(remainder)
            continue

        found = _SINGLE_TIME_RE.findall(value)
        if found:
            for hour, minute in found:
                singles.append((int(hour), int(minute)))
            remainder = _SINGLE_TIME_RE.sub(" ", value).strip(" \t-,;|()[]")
            remainder, duration = _take_duration(remainder, duration)
            if remainder:
                texts.append(remainder)
            continue

        if duration is None and _BARE_DURATION_RE.match(value):
            duration = int(value)
            continue

        texts.append(value)

    return {
        "texts": texts,
        "singles": singles,
        "time_range": time_range,
        "duration": duration,
        "fixed": fixed,
    }


def _resolve_times(row: _Row, time_range, singles) -> None:
    if time_range:
        start = _to_minutes(time_range[0], time_range[1])
        end = _to_minutes(time_range[2], time_range[3])
        if start is None:
            row.problems.append(f"invalid start time '{time_range[0]}:{time_range[1]}'")
        if end is None:
            row.problems.append(f"invalid end time '{time_range[2]}:{time_range[3]}'")
        row.start, row.end = start, end
        return
    if len(singles) >= 2:
        start = _to_minutes(*singles[0])
        end = _to_minutes(*singles[1])
        if start is None or end is None:
            row.problems.append("invalid time in this row (expected 24h HH:MM)")
        row.start, row.end = start, end
        return
    if len(singles) == 1:
        start = _to_minutes(*singles[0])
        if start is None:
            row.problems.append("invalid time in this row (expected 24h HH:MM)")
            return
        row.start = start
        if row.duration:
            row.end = row.start + row.duration
        else:
            row.problems.append("only one time given — add an end time or a set duration")


def _row_from_fields(fields: list, number: int, raw: str) -> _Row:
    row = _Row(number=number, raw=raw)
    data = _classify_fields(fields)
    row.duration = data["duration"]
    row.fixed = data["fixed"]
    _resolve_times(row, data["time_range"], data["singles"])
    texts = data["texts"]
    if texts:
        row.artist = texts[0]
    if len(texts) > 1:
        row.stage = texts[1]
    if len(texts) > 2:
        row.problems.append(
            f"unexpected extra column(s): {', '.join(texts[2:])} — ignored"
        )
    return row


def _row_from_mapping(cells: list, mapping: dict, number: int, raw: str) -> _Row:
    row = _Row(number=number, raw=raw)
    by_name = {}
    for index, canonical in mapping.items():
        if index < len(cells):
            by_name[canonical] = cells[index].strip()

    row.artist = by_name.get("artist") or None
    row.stage = by_name.get("stage") or None
    lowered_fixed = (by_name.get("fixed") or "").lower().strip("[](){}*")
    row.fixed = lowered_fixed in _FIXED_WORDS

    time_cell = by_name.get("time") or ""
    if time_cell:
        match = _TIME_RANGE_RE.search(time_cell)
        if match:
            row.start = _to_minutes(int(match.group(1)), int(match.group(2)))
            row.end = _to_minutes(int(match.group(3)), int(match.group(4)))
        else:
            singles = _SINGLE_TIME_RE.findall(time_cell)
            if len(singles) >= 2:
                row.start = _to_minutes(int(singles[0][0]), int(singles[0][1]))
                row.end = _to_minutes(int(singles[1][0]), int(singles[1][1]))
            elif len(singles) == 1:
                row.start = _to_minutes(int(singles[0][0]), int(singles[0][1]))
        if row.start is None:
            row.problems.append(f"could not read a set time from '{time_cell}'")

    if by_name.get("start"):
        value, error = _parse_time_cell(by_name["start"])
        if error:
            row.problems.append(f"start time {error}")
        row.start = value
    if by_name.get("end"):
        value, error = _parse_time_cell(by_name["end"])
        if error:
            row.problems.append(f"end time {error}")
        row.end = value

    duration_cell = by_name.get("duration") or ""
    if duration_cell:
        parsed = _parse_duration(duration_cell)
        if parsed is None and _BARE_DURATION_RE.match(duration_cell):
            parsed = int(duration_cell)
        if parsed is None:
            row.problems.append(f"could not read a set duration from '{duration_cell}'")
        row.duration = parsed

    if row.start is not None and row.end is None and row.duration:
        row.end = row.start + row.duration
    return row


def _split_text_line(line: str) -> list:
    """Split a pasted line on double spaces, spaced dashes or '@'."""
    fields = [part.strip() for part in re.split(r"\s{2,}|\s+[–—-]\s+|@", line) if part.strip()]
    return fields or [line]


def _read_rows(text: str) -> tuple:
    """Returns (rows, source_format, festival_name)."""
    body, festival_name = _strip_comment_lines(text)
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        raise ImportParseError("The import is empty — paste a schedule or choose a CSV file.")

    delimiter = _detect_delimiter(lines)
    rows = []
    source_format = "text"

    if delimiter:
        source_format = "csv"
        reader = csv.reader(io.StringIO(body), delimiter=delimiter, skipinitialspace=True)
        parsed = [cells for cells in reader if any(cell.strip() for cell in cells)]
        if not parsed:
            raise ImportParseError("No usable rows found in the CSV.")
        mapping = _match_header(parsed[0])
        start = 0
        if mapping:
            start = 1
        for offset, cells in enumerate(parsed[start:]):
            number = offset + start + 1
            raw = delimiter.join(cells)
            if mapping:
                rows.append(_row_from_mapping(cells, mapping, number, raw))
            else:
                rows.append(_row_from_fields(cells, number, raw))
    else:
        text_mapping = None
        for offset, line in enumerate(lines):
            number = offset + 1
            fields = _split_text_line(line)
            if offset == 0:
                text_mapping = _match_header(fields)
                if text_mapping:
                    source_format = "csv"
                    continue
            if text_mapping:
                rows.append(_row_from_mapping(fields, text_mapping, number, line))
            else:
                rows.append(_row_from_fields(fields, number, line))

    if not rows:
        raise ImportParseError("No schedule rows found — expected artist, stage and set time.")
    return rows, source_format, festival_name


def parse_lineup(text: str) -> dict:
    """Parse and validate raw import text into a festival structure.

    Returns stages, slots and acts (entity ids intentionally empty — artists are
    matched to Qloo entities only after the user confirms a candidate), plus an
    issue list. Rows with errors are dropped; warnings and info are kept.
    """
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ImportParseError(
            f"The import is too large (max {MAX_TEXT_BYTES // 1000} KB). Split it into parts."
        )

    rows, source_format, festival_name = _read_rows(text)
    issues = []

    def add(severity: str, message: str, row: int | None = None, field_name: str | None = None):
        issues.append({"severity": severity, "row": row, "field": field_name, "message": message})

    if len(rows) > MAX_ROWS:
        raise ImportParseError(f"Too many rows ({len(rows)}); the maximum is {MAX_ROWS}.")

    # --- stage + slot structure, from the names and times actually present ---
    stage_ids = {}
    taken_slugs = set()
    slot_ids = {}
    usable = []

    for row in rows:
        for problem in row.problems:
            add("error", problem, row.number)
        if not (row.artist or "").strip():
            add("error", "Missing artist name.", row.number, "artist")
        if not (row.stage or "").strip():
            add("error", "Missing stage name.", row.number, "stage")
        if row.start is None or row.end is None:
            if not row.problems:
                add("error", "Missing set time (expected HH:MM-HH:MM).", row.number, "time")
            continue
        if row.end <= row.start:
            add(
                "error",
                f"Set ends before it starts ({_hhmm(row.start)}–{_hhmm(row.end)}).",
                row.number,
                "time",
            )
            continue
        if not (row.artist or "").strip() or not (row.stage or "").strip():
            continue

        stage_name = row.stage.strip()
        if stage_name not in stage_ids:
            stage_ids[stage_name] = _unique_slug(_slug(stage_name), taken_slugs)
        slot_key = (row.start, row.end)
        if slot_key not in slot_ids:
            slot_ids[slot_key] = f"t{len(slot_ids) + 1}"
        usable.append(row)

    stages = [{"id": stage_ids[name], "name": name} for name in stage_ids]
    slots = [
        {
            "id": slot_ids[key],
            "label": _hhmm(key[0]),
            "start": _hhmm(key[0]),
            "end": _hhmm(key[1]),
            "duration_min": key[1] - key[0],
        }
        for key in sorted(slot_ids, key=lambda item: (item[0], item[1]))
    ]
    slot_by_key = {(s["start"], s["end"]): s for s in slots}

    # --- acts, durations and conflicts ---
    acts = []
    assumed_durations = 0
    cells = {}
    for row in usable:
        start = _hhmm(row.start)
        end = _hhmm(row.end)
        slot = slot_by_key[(start, end)]
        duration = row.duration
        duration_assumed = duration is None
        if duration_assumed:
            duration = slot["duration_min"]
        if duration > slot["duration_min"]:
            add(
                "error",
                f"{row.artist}: a {duration} min set does not fit the "
                f"{slot['duration_min']} min slot {start}–{end}.",
                row.number,
                "duration",
            )
            continue
        if duration < MIN_DURATION or duration > MAX_DURATION:
            add(
                "error",
                f"{row.artist}: set duration {duration} min is outside "
                f"{MIN_DURATION}–{MAX_DURATION} min.",
                row.number,
                "duration",
            )
            continue
        act = {
            "id": f"a{len(acts) + 1}",
            "row": row.number,
            "name": row.artist.strip(),
            "entity_id": "",
            "stage_id": stage_ids[row.stage.strip()],
            "stage_name": row.stage.strip(),
            "slot_id": slot["id"],
            "start": start,
            "end": end,
            "duration_min": duration,
            "fixed": row.fixed,
        }
        cell = (act["stage_id"], act["slot_id"])
        if cell in cells:
            first = cells[cell]
            add(
                "error",
                f"Double booking: {act['name']} and {first['name']} are both on "
                f"{act['stage_name']} at {start}–{end}.",
                row.number,
                "stage",
            )
            add(
                "error",
                f"Double booking: {first['name']} and {act['name']} are both on "
                f"{first['stage_name']} at {start}–{end}.",
                first["row"],
                "stage",
            )
            continue
        cells[cell] = act
        acts.append(act)
        if duration_assumed:
            assumed_durations += 1

    if assumed_durations:
        add(
            "info",
            f"{assumed_durations} act(s) had no explicit set length — assumed equal to "
            "their time slot length.",
        )

    # --- same-stage overlaps between different slots ---
    by_stage = {}
    for act in acts:
        by_stage.setdefault(act["stage_id"], []).append(act)
    for stage_id, stage_acts in by_stage.items():
        for i in range(len(stage_acts)):
            for j in range(i + 1, len(stage_acts)):
                a, b = stage_acts[i], stage_acts[j]
                if a["slot_id"] == b["slot_id"]:
                    continue
                a_start, a_end = a["start"], a["end"]
                b_start, b_end = b["start"], b["end"]
                a_start_min, a_end_min = _minutes_of(a_start), _minutes_of(a_end)
                b_start_min, b_end_min = _minutes_of(b_start), _minutes_of(b_end)
                if a_start_min < b_end_min and b_start_min < a_end_min:
                    stage_name = next(s["name"] for s in stages if s["id"] == stage_id)
                    add(
                        "error",
                        f"Overlapping sets on {stage_name}: {a['name']} "
                        f"({a_start}–{a_end}) and {b['name']} ({b_start}–{b_end}).",
                        a["row"],
                        "time",
                    )

    errors = [i for i in issues if i["severity"] == "error"]
    summary = (
        f"{len(acts)} artist(s) · {len(stages)} stage(s) · {len(slots)} time slot(s) "
        f"parsed from {'CSV' if source_format == 'csv' else 'pasted text'}"
    )
    if errors:
        summary += f" · {len(errors)} row(s) rejected"

    return {
        "source_format": source_format,
        "festival_name": festival_name,
        "stages": stages,
        "slots": slots,
        "acts": acts,
        "issues": issues,
        "valid": not errors,
        "summary": summary,
    }
