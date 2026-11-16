"""Select manifest records for a build run."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def selected_records(
    records: Iterable[Mapping[str, Any]],
    packages: set[str],
    versions: set[str],
) -> list[Mapping[str, Any]]:
    selected = [
        record
        for record in records
        if (not packages or str(record["package"]) in packages)
        and (not versions or str(record["version"]) in versions)
    ]
    return sorted(
        selected,
        key=lambda row: (str(row["package"]), str(row["version"])),
    )
