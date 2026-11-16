"""Build per-version knowledge bases."""

from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from importlib.metadata import version as distribution_version
from pathlib import Path

from .selection import selected_records
from .record_builder import build_record
from .storage import now, sha256_file, write_json


def run_build_pipeline(
    *,
    manifest_path: Path,
    output_dir: Path,
    packages: set[str] | None = None,
    versions: set[str] | None = None,
    keep_raw: bool = True,
) -> int:
    """Build one KB for each selected source record."""

    installed = distribution_version("griffe")
    manifest_path = manifest_path.resolve()
    output_dir = output_dir.resolve()
    packages = set() if packages is None else set(packages)
    versions = set() if versions is None else set(versions)
    raw_records = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw_records, list):
        raise ValueError("MANIFEST.json must contain a list")
    records = selected_records(raw_records, packages, versions)
    if not records:
        raise ValueError("no manifest records matched the filters")
    if output_dir.exists():
        raise FileExistsError(
            "output directory already exists (choose a new path): "
            f"{output_dir}"
        )
    output_dir.mkdir(parents=True)

    run = {
        "schema": "vercomfix-griffe-build-v1",
        "started_at": now(),
        "finished_at": None,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "griffe_version": installed,
        "python_version": sys.version,
        "config": {
            "allow_inspection": False,
            "resolve_aliases": True,
            "resolve_external": False,
            "keep_raw": keep_raw,
            "packages": sorted(packages),
            "versions": sorted(versions),
        },
        "results": [],
    }
    failed = False
    for record in records:
        package = str(record["package"])
        version = str(record["version"])
        print(f"[{package} {version}] building", flush=True)
        try:
            built = build_record(
                manifest_path,
                record,
                output_dir,
                keep_raw=keep_raw,
            )
        except Exception as exc:
            failed = True
            result = {
                "package": package,
                "version": version,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            print(
                f"[{package} {version}] failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
        else:
            result = built.result
            count = built.knowledge_base["metadata"]["signature_count"]
            print(
                f"[{package} {version}] {count} signatures", flush=True
            )
        run["results"].append(result)
        write_json(output_dir / "build_manifest.json", run)

    run["finished_at"] = now()
    run["counts"] = dict(
        Counter(result["status"] for result in run["results"])
    )
    write_json(output_dir / "build_manifest.json", run)
    return 1 if failed else 0
