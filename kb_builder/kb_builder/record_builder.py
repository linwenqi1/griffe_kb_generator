"""Build and persist one Griffe KB record without comparing it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .builder import build_knowledge_base
from .inputs import (
    resolve_source_paths,
    validate_build_input,
)
from .storage import write_json_gz, write_text_gz


@dataclass(frozen=True)
class BuiltRecord:
    """Artifacts produced for one source version."""

    result: dict[str, Any]
    knowledge_base: dict[str, Any]


def build_record(
    manifest_path: Path,
    record: Mapping[str, Any],
    output_dir: Path,
    *,
    keep_raw: bool,
) -> BuiltRecord:
    """Build one schema-v4 KB and write only Griffe-derived artifacts."""

    package = str(record["package"])
    version = str(record["version"])
    import_name = str(record["import_name"])
    paths = resolve_source_paths(manifest_path, record)
    hashes = validate_build_input(record, paths)
    record_output = output_dir / package / version
    record_output.mkdir(parents=True, exist_ok=False)

    root, generated = build_knowledge_base(
        package=package,
        version=version,
        import_name=import_name,
        search_path=paths.search_path,
    )
    generated["metadata"].update(
        {
            "distribution": package,
            "import_name": import_name,
            "source_root": str(paths.source_root),
            **({"archive": str(paths.archive)} if paths.archive else {}),
            **hashes,
        }
    )
    if keep_raw:
        write_text_gz(
            record_output / "griffe_raw.json.gz",
            root.as_json(full=True),
        )
    kb_path = record_output / "griffe_kb.json.gz"
    write_json_gz(kb_path, generated)

    result = {
        "package": package,
        "version": version,
        "import_name": import_name,
        "status": "completed",
        "source_root": str(paths.source_root),
        "search_path": str(paths.search_path),
        "output_dir": str(record_output),
        "knowledge_base": str(kb_path),
        "unresolved_alias_count": generated["metadata"][
            "unresolved_alias_count"
        ],
    }
    return BuiltRecord(
        result=result,
        knowledge_base=generated,
    )
