"""Atomic JSON and gzip persistence helpers."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_path(target: Path) -> tuple[Path, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
        delete=False,
    )
    return Path(handle.name), handle


def write_json(path: Path, value: Any) -> None:
    temp, handle = _atomic_path(path)
    try:
        with handle:
            payload = json.dumps(
                value, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8") + b"\n"
            handle.write(payload)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def write_json_gz(path: Path, value: Any) -> None:
    temp, handle = _atomic_path(path)
    try:
        handle.close()
        with gzip.open(temp, "wt", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def write_text_gz(path: Path, value: str) -> None:
    temp, handle = _atomic_path(path)
    try:
        handle.close()
        with gzip.open(temp, "wt", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
