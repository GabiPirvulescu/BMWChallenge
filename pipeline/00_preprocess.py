
"""Convert explicitly supplied raw BMW files into a source-preserving bundle.

Example:
    python pipeline/00_preprocess.py --raw-data-dir <raw-dir> --output-dir <processed-dir>

The raw directory is read-only from this script's perspective. Both paths are
required so a run cannot silently select a personal/default data directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.ingestion import (  # noqa: E402
    DEFAULT_REQUIRED_KINDS,
    ConversionError,
    convert_sources,
    write_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-data-dir", required=True, type=Path,
                        help="Directory to read; originals are never edited or deleted.")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="Processed JSONL/manifest destination outside the raw directory.")
    parser.add_argument("--required-kind", action="append", dest="required_kinds",
                        choices=("feedback", "survey", "sales", "document"),
                        help="Required source kind; defaults to feedback, survey, sales, and document.")
    parser.add_argument("--check-known-feedback-counts", action="store_true",
                        help="Fail the bundle as partial if complete-export row/comment targets differ from the Role 01 baseline.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required = args.required_kinds if args.required_kinds is not None else DEFAULT_REQUIRED_KINDS
    try:
        raw_dir = args.raw_data_dir.resolve()
        output_dir = args.output_dir.resolve()
        if output_dir == raw_dir or raw_dir in output_dir.parents:
            raise ConversionError("Output directory must be outside the raw data directory")
        bundle = convert_sources(raw_dir, required_kinds=required,
                                 check_known_feedback_counts=args.check_known_feedback_counts)
        manifest_path = write_bundle(bundle, output_dir, raw_dir)
    except (ConversionError, OSError) as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 2

    print(f"Status: {bundle.manifest.get('status')}")
    print(f"Sources: {bundle.manifest.get('counts', {}).get('source_files', 0)}")
    print(f"Source records: {bundle.manifest.get('counts', {}).get('source_records', 0)}")
    print(f"Comments: {bundle.manifest.get('counts', {}).get('feedback_comments', 0)}")
    print(f"Annotations: {bundle.manifest.get('counts', {}).get('feedback_annotations', 0)}")
    print(f"Facts: {bundle.manifest.get('counts', {}).get('facts', 0)}")
    print(f"Document chunks: {bundle.manifest.get('counts', {}).get('document_chunks', 0)}")
    print(f"Manifest: {manifest_path}")
    if bundle.manifest.get("status") != "succeeded":
        print("This bundle is incomplete. Review manifest.json and resolve input/parser issues before import.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
