"""Command-line runner for the ClashDoctor Qloo validation probe.

Mock mode is the default and makes no network calls. Live mode reuses the
production `app.qloo.QlooClient`, so authentication, endpoints, retries and
error handling are identical to the API. Reports go to
`probe/outputs/<mode>/` unless `--out` is given.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .core import (
    DEFAULT_DATASET,
    DatasetError,
    ProbeConfigError,
    run_probe,
)
from .report import write_reports

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "outputs"

EXIT_OK = 0
EXIT_DATASET_ERROR = 1
EXIT_ABORTED = 2
EXIT_MISSING_KEY = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m probe.run",
        description=(
            "Validate whether Qloo resolves the probe artists and carries useful "
            "taste signals. Mock mode is offline and synthetic; live mode calls Qloo."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="call the real Qloo API (requires QLOO_API_KEY in backend/.env)",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help=f"probe dataset JSON (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default: probe/outputs/<mode>)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="seconds to wait between artists (default: 0)",
    )
    parser.add_argument(
        "--take",
        type=int,
        default=None,
        help="tags requested per insights call (default: QLOO_INSIGHTS_TAKE)",
    )
    parser.add_argument(
        "--top-pairs",
        type=int,
        default=20,
        help="scored pairs carried in top_pairs (default: 20)",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    if args.take is not None and args.take < 1:
        parser.error("--take must be >= 1")
    if args.top_pairs < 1:
        parser.error("--top-pairs must be >= 1")


def _resolution_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = record["resolution"]["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def _source_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        section = record["profile"]
        if section["source"] == "unresolved":
            key = "unresolved"
        elif section["source"] == "unconfirmed":
            key = "unconfirmed"
        elif section["missing"]:
            key = "no usable tags"
        else:
            key = section["source"]
        counts[key] = counts.get(key, 0) + 1
    return counts


def _summary(report: dict) -> str:
    meta = report["probe"]
    computed = report["computed"]
    coverage = computed["coverage"]
    summary = computed["matrix_summary"]
    records = report["observed"]["artists"]
    mode = meta["mode"]

    lines = [
        "ClashDoctor Qloo validation probe",
        f"mode: {mode}",
    ]
    if not meta["evidence"]["is_evidence"]:
        lines.append(
            "evidence: no - synthetic fixtures. These numbers test the pipeline, "
            "not Qloo coverage."
            if mode == "mock"
            else "evidence: no - this live run produced no usable evidence."
        )
    else:
        lines.append(
            "evidence: yes - "
            f"{meta['transport']['profiles_with_usable_tags']} artist(s) with usable "
            f"tags from {meta['transport']['live_requests_succeeded']} live request(s)."
        )
    lines.append(
        "dataset: "
        f"{meta['dataset']['artist_count']} artists "
        f"({meta['dataset']['label_counts'].get('established', 0)} established, "
        f"{meta['dataset']['label_counts'].get('emerging', 0)} emerging)"
    )
    lines.append(
        "resolution: "
        + ", ".join(f"{k} {v}" for k, v in sorted(_resolution_counts(records).items()))
    )
    lines.append(
        "profile sources: "
        + ", ".join(f"{k} {v}" for k, v in sorted(_source_counts(records).items()))
    )
    lines.append(
        "coverage: "
        f"{coverage['profiles_with_data']}/{coverage['profiles_total']} artists with tags; "
        f"{coverage['pairs_scored']}/{coverage['pairs_total']} pairs scored "
        f"({coverage['pairs_missing']} excluded, "
        f"{coverage['pairs_low_confidence']} low-confidence)"
    )
    top = computed["top_pairs"]
    if top:
        pair = top[0]
        lines.append(
            "top pair: "
            f"{pair['artist_a']['name']} / {pair['artist_b']['name']} "
            f"taste {pair['taste_similarity']:.3f}"
        )
    if meta.get("aborted"):
        aborted = meta["aborted"]
        lines.append(
            f"ABORTED at {aborted['stage']} for {aborted['artist_id']}: "
            f"{aborted['reason']}"
        )
    return "\n".join(lines)


def _prepare_stdio() -> None:
    # Artist names can contain characters the local console cannot encode.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _prepare_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    mode = "live" if args.live else "mock"
    out_dir = args.out or (DEFAULT_OUTPUT_ROOT / mode)

    try:
        report = asyncio.run(
            run_probe(
                mode=mode,
                dataset_path=args.dataset,
                delay=args.delay,
                take=args.take,
                top_pairs=args.top_pairs,
            )
        )
    except DatasetError as exc:
        print(f"dataset error: {exc}", file=sys.stderr)
        return EXIT_DATASET_ERROR
    except ProbeConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_MISSING_KEY

    paths = write_reports(report, out_dir)
    print(_summary(report))
    if not report["probe"]["evidence"]["is_evidence"]:
        print(f"note: {report['probe']['evidence']['note']}")
    print("reports:")
    for kind, path in paths.items():
        print(f"  {kind}: {path}")
    return EXIT_ABORTED if report["probe"]["aborted"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
