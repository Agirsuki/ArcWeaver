from __future__ import annotations

"""Command-line entrypoint for ArcWeaver."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, ExtractBatchResult, ExtractOptions, extract_tasks


def build_parser() -> argparse.ArgumentParser:
    """Build the ArcWeaver command-line parser."""

    parser = argparse.ArgumentParser(
        prog="arcweaver",
        description=(
            "Extract disguised, multipart, and recursively nested archives "
            "from files or directories."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="One or more files or directories to process.",
    )
    parser.add_argument(
        "-p",
        "--password",
        action="append",
        default=[],
        help="Archive password. Can be provided multiple times.",
    )
    parser.add_argument(
        "--password-file",
        help="Text file with one password per line.",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete source archives after a successful result promotion.",
    )
    parser.add_argument(
        "--delete-working-dir",
        action="store_true",
        help="Delete the working directory after completion.",
    )
    parser.add_argument(
        "--no-promote-output",
        dest="promote_output",
        action="store_false",
        help="Keep final results in the output directory instead of copying them back to the workspace.",
    )
    parser.add_argument(
        "--no-polyglot",
        dest="detect_polyglot",
        action="store_false",
        help="Disable polyglot archive detection.",
    )
    parser.add_argument(
        "--no-disguised",
        dest="detect_disguised",
        action="store_false",
        help="Disable disguised-archive detection.",
    )
    parser.add_argument(
        "--no-recycle-bin",
        dest="use_recycle_bin",
        action="store_false",
        help="Use direct deletion instead of the Windows recycle bin.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=10,
        help="Maximum recursive extraction depth. Default: 10.",
    )
    parser.add_argument(
        "--seven-zip-path",
        help="Path to 7z.exe.",
    )
    parser.add_argument(
        "--output-dir-name",
        default="unzipped",
        help="Name of the final output directory. Default: unzipped.",
    )
    parser.add_argument(
        "--working-dir-name",
        default=".complex_unzip_work",
        help="Name of the working directory. Default: .complex_unzip_work.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full batch result as JSON.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.set_defaults(
        promote_output=True,
        detect_polyglot=True,
        detect_disguised=True,
        use_recycle_bin=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ArcWeaver command-line entrypoint."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        options = _build_options(args)
        batch = extract_tasks(args.paths, options)
    except Exception as exc:
        print(f"arcweaver: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(asdict(batch), ensure_ascii=False, indent=2))
    else:
        _print_batch_summary(batch)

    return _determine_exit_code(batch)


def _build_options(args: argparse.Namespace) -> ExtractOptions:
    """Build normalized extraction options from parsed arguments."""

    passwords = list(args.password or [])
    passwords.extend(_load_password_file(args.password_file))

    return ExtractOptions(
        passwords=_dedupe_strings(passwords),
        detect_polyglot_archives=args.detect_polyglot,
        detect_disguised_archives=args.detect_disguised,
        delete_source_archives=args.delete_source,
        delete_working_dir=args.delete_working_dir,
        promote_output_contents_to_workspace=args.promote_output,
        use_recycle_bin=args.use_recycle_bin,
        max_depth=args.max_depth,
        seven_zip_path=args.seven_zip_path,
        output_dir_name=args.output_dir_name,
        working_dir_name=args.working_dir_name,
    )


def _load_password_file(path: str | None) -> list[str]:
    """Load additional passwords from a text file."""

    if not path:
        return []

    content = Path(path).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip()
    ]


def _dedupe_strings(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _print_batch_summary(batch: ExtractBatchResult) -> None:
    """Print a short human-readable summary for each task."""

    total = len(batch.tasks)
    for index, task in enumerate(batch.tasks, start=1):
        extraction = task.extraction
        print(f"[{index}/{total}] {task.plan.input_path}")
        print(
            "  "
            f"status={extraction.status} "
            f"next={extraction.next_action} "
            f"extracted={len(extraction.extracted_files)} "
            f"unresolved={len(extraction.unresolved_candidates)} "
            f"password_failed={len(extraction.password_failed_candidates)}"
        )
        if extraction.errors:
            print(f"  first_error={extraction.errors[0]}")


def _determine_exit_code(batch: ExtractBatchResult) -> int:
    """Map batch results to process exit codes."""

    statuses = {task.extraction.status for task in batch.tasks}
    if "failed" in statuses:
        return 2
    if "partial_success" in statuses:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
