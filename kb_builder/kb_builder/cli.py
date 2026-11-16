"""Command line interface for building Griffe knowledge bases."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .build_pipeline import run_build_pipeline


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build schema-v4 KBs from Python source")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--package", action="append", default=[], help="repeatable filter")
    parser.add_argument("--version", action="append", default=[], help="repeatable filter")
    parser.add_argument("--no-raw", action="store_true", help="omit full Griffe JSON")
    args = parser.parse_args(argv)
    return run_build_pipeline(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        packages=set(args.package),
        versions=set(args.version),
        keep_raw=not args.no_raw,
    )
