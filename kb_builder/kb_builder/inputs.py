"""Resolve and validate the source inputs needed to build a KB."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .storage import sha256_file


@dataclass(frozen=True)
class SourcePaths:
    source_root: Path
    search_path: Path
    archive: Path | None


def _resolve(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def resolve_source_paths(manifest_path: Path, record: Mapping[str, Any]) -> SourcePaths:
    source_root = _resolve(manifest_path, str(record["source_root"]))
    search_path = _resolve(manifest_path, str(record["search_path"]))
    if not source_root.is_dir():
        raise FileNotFoundError(f"source_root does not exist: {source_root}")
    if not search_path.is_dir():
        raise FileNotFoundError(f"search_path does not exist: {search_path}")
    if not search_path.is_relative_to(source_root):
        raise ValueError(f"search_path is outside source_root: {search_path}")
    archive = None
    if record.get("source_archive") is not None:
        archive = _resolve(manifest_path, str(record["source_archive"]))
        if not archive.is_file():
            raise FileNotFoundError(f"source_archive does not exist: {archive}")
    return SourcePaths(source_root, search_path, archive)


def validate_build_input(record: Mapping[str, Any], paths: SourcePaths) -> dict[str, str]:
    if paths.archive is None:
        if record.get("archive_sha256") is not None:
            raise ValueError("archive_sha256 requires source_archive")
        return {}
    actual = sha256_file(paths.archive)
    expected = record.get("archive_sha256")
    if expected is not None and actual != str(expected):
        raise ValueError(
            f"archive_sha256 mismatch for {record['package']} {record['version']}: "
            f"expected {expected}, got {actual}"
        )
    return {"archive_sha256": actual}
