"""Shared schema and adapter constants."""

from __future__ import annotations



KNOWLEDGE_BASE_SCHEMA_VERSION = 4

ADAPTER_SCHEMA_VERSION = 4

SOURCE_OVERLAY_SKIP_DIRS = {
    "__pycache__",
    "benchmarks",
    "doc",
    "docs",
    "examples",
    "test",
    "testing",
    "tests",
}
