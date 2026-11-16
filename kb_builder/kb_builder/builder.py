"""Griffe loading and schema-v4 knowledge-base construction only."""

from __future__ import annotations

import copy
from collections import Counter
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any

import griffe

from .constants import (
    ADAPTER_SCHEMA_VERSION,
    KNOWLEDGE_BASE_SCHEMA_VERSION,
)
from .source_analysis import (
    AstIndex,
    _callable_kind,
    _return_shape,
    _source_import_edges,
)

def _safe_path(value: Any) -> str | None:
    try:
        path = value.path
    except Exception:
        return None
    return str(path)

def _safe_filepath(value: Any) -> Path | None:
    try:
        filepath = value.filepath
    except Exception:
        return None
    if filepath is None:
        return None
    return Path(filepath)

def _source_file(value: Any, search_path: Path) -> str:
    filepath = _safe_filepath(value)
    if filepath is None:
        return ""
    try:
        return filepath.resolve().relative_to(search_path.resolve()).as_posix()
    except ValueError:
        return filepath.as_posix()

def _annotation(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)

def _decorator_names(value: Any) -> set[str]:
    names: set[str] = set()
    for decorator in getattr(value, "decorators", ()):
        text = str(getattr(decorator, "value", decorator))
        names.add(text.rsplit(".", 1)[-1].split("(", 1)[0])
    return names

def _parameters(value: Any, *, drop_receiver: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        parameters = list(value.parameters)
    except Exception:
        return result
    for index, parameter in enumerate(parameters):
        if drop_receiver and index == 0 and parameter.name in {"self", "cls", "mcs"}:
            continue
        kind = getattr(parameter.kind, "name", str(parameter.kind).replace(" ", "_"))
        default = parameter.default
        variadic = kind in {"var_positional", "var_keyword"}
        result.append(
            {
                "name": parameter.name,
                "kind": kind,
                "required": default is None and not variadic,
                "default": None if default is None else str(default),
                "annotation": _annotation(parameter.annotation),
            }
        )
    return result

def _base_names(value: Any) -> list[str]:
    return [str(base) for base in getattr(value, "bases", ())]

class GriffeAdapter:
    def __init__(self, *, package: str, version: str, search_path: Path) -> None:
        self.package = package
        self.version = version
        self.search_path = search_path.resolve()
        self.ast_index = AstIndex()
        self.signatures: dict[str, dict[str, Any]] = {}
        self.aliases: list[dict[str, Any]] = []
        self.unresolved_aliases: list[dict[str, str]] = []
        self.filtered_instance_attributes: list[str] = []
        self.filtered_non_runtime_members: list[str] = []
        self.skipped_module_alias_descents: list[dict[str, str]] = []
        self._skipped_module_alias_descent_keys: set[tuple[str, str]] = set()
        self.source_import_overlay_edges: list[SourceImportEdge] = []
        self.source_import_overlay_parse_errors: list[dict[str, str]] = []
        self.recovered_exposed_fqns: list[str] = []
        self.unresolved_source_import_edges: list[SourceImportEdge] = []
        self._visited_containers: set[tuple[str, str]] = set()

    def convert(self, root: Any) -> dict[str, Any]:
        self._walk_container(root, str(root.path))
        self._apply_source_import_overlay()
        scopes = Counter(value["scope"] for value in self.signatures.values())
        return {
            "schema_version": KNOWLEDGE_BASE_SCHEMA_VERSION,
            "package": self.package,
            "metadata": {
                "generator": "griffe",
                "adapter_schema": ADAPTER_SCHEMA_VERSION,
                "griffe_version": distribution_version("griffe"),
                "allow_inspection": False,
                "resolve_aliases": True,
                "resolve_external": False,
                "search_path": str(self.search_path),
                "signature_count": len(self.signatures),
                "scope_counts": dict(sorted(scopes.items())),
                "alias_edges": self.aliases,
                "unresolved_alias_count": len(self.unresolved_aliases),
                "unresolved_aliases": self.unresolved_aliases[:500],
                "filtered_instance_attribute_count": len(
                    self.filtered_instance_attributes
                ),
                "filtered_instance_attributes": self.filtered_instance_attributes[:500],
                "filtered_non_runtime_member_count": len(
                    self.filtered_non_runtime_members
                ),
                "filtered_non_runtime_members": (
                    self.filtered_non_runtime_members[:500]
                ),
                "skipped_module_alias_descent_count": len(
                    self.skipped_module_alias_descents
                ),
                "skipped_module_alias_descents": (
                    self.skipped_module_alias_descents[:1000]
                ),
                "source_import_overlay_edge_count": len(
                    self.source_import_overlay_edges
                ),
                "source_import_overlay_edges": [
                    {
                        "exposed_fqn": edge.exposed_fqn,
                        "target_fqn": edge.target_fqn,
                        "source_file": edge.source_file,
                        "line": edge.line,
                    }
                    for edge in self.source_import_overlay_edges[:1000]
                ],
                "source_import_overlay_parse_error_count": len(
                    self.source_import_overlay_parse_errors
                ),
                "source_import_overlay_parse_errors": (
                    self.source_import_overlay_parse_errors[:100]
                ),
                "recovered_exposed_fqn_count": len(self.recovered_exposed_fqns),
                "recovered_exposed_fqns": self.recovered_exposed_fqns[:1000],
                "unresolved_source_import_edge_count": len(
                    self.unresolved_source_import_edges
                ),
                "unresolved_source_import_edges": [
                    {
                        "exposed_fqn": edge.exposed_fqn,
                        "target_fqn": edge.target_fqn,
                        "source_file": edge.source_file,
                        "line": edge.line,
                    }
                    for edge in self.unresolved_source_import_edges[:500]
                ],
                "return_shape_source": "source AST supplement",
            },
            "versions": {self.version: dict(sorted(self.signatures.items()))},
        }

    def _copy_exposed_signature(
        self, exposed_fqn: str, target_fqn: str
    ) -> bool:
        if exposed_fqn in self.signatures:
            return False
        target = self.signatures.get(target_fqn)
        if target is None:
            return False
        value = copy.deepcopy(target)
        value["fqn"] = exposed_fqn
        value["canonical_fqn"] = target.get("canonical_fqn") or target_fqn
        self.signatures[exposed_fqn] = value
        self.recovered_exposed_fqns.append(exposed_fqn)

        if target.get("scope") == "class":
            prefix = f"{target_fqn}."
            for child_fqn, child in list(self.signatures.items()):
                if not child_fqn.startswith(prefix):
                    continue
                suffix = child_fqn[len(prefix):]
                exposed_child = f"{exposed_fqn}.{suffix}"
                if exposed_child in self.signatures:
                    continue
                child_value = copy.deepcopy(child)
                child_value["fqn"] = exposed_child
                child_value["canonical_fqn"] = (
                    child.get("canonical_fqn") or child_fqn
                )
                self.signatures[exposed_child] = child_value
                self.recovered_exposed_fqns.append(exposed_child)
        return True

    def _apply_source_import_overlay(self) -> None:
        edges, errors = _source_import_edges(self.search_path, self.package)
        self.source_import_overlay_edges = edges
        self.source_import_overlay_parse_errors = errors
        pending = list(edges)
        # Imported aliases can point at other imported aliases.  Resolve to a
        # fixed point without executing package code.
        while pending:
            next_pending: list[SourceImportEdge] = []
            changed = False
            for edge in pending:
                if edge.exposed_fqn in self.signatures:
                    continue
                if self._copy_exposed_signature(
                    edge.exposed_fqn, edge.target_fqn
                ):
                    changed = True
                else:
                    next_pending.append(edge)
            if not changed:
                self.unresolved_source_import_edges = next_pending
                break
            pending = next_pending

    def _walk_container(self, container: Any, exposed_path: str) -> None:
        canonical = _safe_path(container) or exposed_path
        visit_key = (exposed_path, canonical)
        if visit_key in self._visited_containers:
            return
        self._visited_containers.add(visit_key)
        try:
            members = container.members
        except Exception:
            return
        for name, member in sorted(members.items()):
            member_path = f"{exposed_path}.{name}"
            # Griffe keeps type-guarded objects in its model so they can resolve
            # annotations, but marks the exposed object or alias as unavailable
            # at runtime.  Check this before resolving aliases: their canonical
            # targets can be runtime objects even when this exposed path is not.
            if not getattr(member, "runtime", True):
                self.filtered_non_runtime_members.append(member_path)
                continue
            if getattr(member, "is_alias", False):
                if not name.startswith("_"):
                    self._visit_alias(member, member_path)
                continue
            if getattr(member, "is_module", False):
                # The legacy extractor scanned private modules too; privacy is
                # determined by the final API member, not by module filenames.
                self._walk_container(member, member_path)
                continue
            if name.startswith("_"):
                continue
            self._visit_object(member, member_path, canonical_path=_safe_path(member))

    def _record_skipped_module_alias_descent(
        self, exposed_fqn: str, target_fqn: str
    ) -> None:
        key = (exposed_fqn, target_fqn)
        if key in self._skipped_module_alias_descent_keys:
            return
        self._skipped_module_alias_descent_keys.add(key)
        self.skipped_module_alias_descents.append(
            {"exposed_fqn": exposed_fqn, "target_fqn": target_fqn}
        )

    def _walk_module_alias(self, module: Any, exposed_path: str) -> None:
        """Expose one module-alias hop without cloning its module graph.

        Direct functions, classes and object aliases remain addressable through
        the imported module object.  Submodules and aliases to other modules are
        recorded but not traversed: Griffe loads source submodules statically,
        which does not prove that Python attached them to this alias at runtime.
        """

        canonical = _safe_path(module) or exposed_path
        visit_key = (f"module-alias:{exposed_path}", canonical)
        if visit_key in self._visited_containers:
            return
        self._visited_containers.add(visit_key)
        try:
            members = module.members
        except Exception:
            return
        for name, member in sorted(members.items()):
            member_path = f"{exposed_path}.{name}"
            if not getattr(member, "runtime", True):
                self.filtered_non_runtime_members.append(member_path)
                continue
            if name.startswith("_"):
                continue
            if getattr(member, "is_alias", False):
                self._visit_alias(
                    member,
                    member_path,
                    expand_module_target=False,
                )
                continue
            if getattr(member, "is_module", False):
                self._record_skipped_module_alias_descent(
                    member_path, _safe_path(member) or member_path
                )
                continue
            self._visit_object(
                member,
                member_path,
                canonical_path=_safe_path(member),
            )

    def _resolve_alias(self, alias: Any) -> Any | None:
        value = alias
        seen: set[int] = set()
        try:
            while getattr(value, "is_alias", False):
                if id(value) in seen:
                    raise RuntimeError("alias cycle")
                seen.add(id(value))
                value = value.target
            return value
        except Exception as exc:
            self.unresolved_aliases.append(
                {
                    "exposed_fqn": _safe_path(alias) or "",
                    "target_fqn": str(getattr(alias, "target_path", "")),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return None

    def _visit_alias(
        self,
        alias: Any,
        exposed_path: str,
        *,
        expand_module_target: bool = True,
    ) -> None:
        target_path = str(getattr(alias, "target_path", ""))
        target = self._resolve_alias(alias)
        resolved_path = _safe_path(target) if target is not None else None
        self.aliases.append(
            {
                "exposed_fqn": exposed_path,
                "target_fqn": target_path,
                "resolved_fqn": resolved_path,
                "resolved": target is not None,
            }
        )
        if target is None or not resolved_path:
            return
        if not (
            resolved_path == self.package
            or resolved_path.startswith(f"{self.package}.")
        ):
            return
        if getattr(target, "is_module", False):
            if expand_module_target:
                self._walk_module_alias(target, exposed_path)
            else:
                self._record_skipped_module_alias_descent(
                    exposed_path, resolved_path
                )
            return
        self._visit_object(target, exposed_path, canonical_path=resolved_path)

    def _visit_object(
        self, value: Any, exposed_path: str, *, canonical_path: str | None
    ) -> None:
        if getattr(value, "is_class", False):
            self._add_class(value, exposed_path, canonical_path)
            self._walk_container(value, exposed_path)
        elif getattr(value, "is_function", False):
            self._add_function(value, exposed_path, canonical_path)
        elif getattr(value, "is_attribute", False) or getattr(
            value, "is_type_alias", False
        ):
            labels = set(getattr(value, "labels", ()))
            if (
                "instance-attribute" in labels
                and "class-attribute" not in labels
                and "property" not in labels
            ):
                # Griffe promotes assignments such as ``self.name = value`` to
                # class members.  They are useful for API documentation, but are
                # not callable signatures and were intentionally absent from the
                # legacy signature extractor.  Keep class declarations and
                # properties; discard only instance-only inferred attributes.
                self.filtered_instance_attributes.append(exposed_path)
                return
            self._add_attribute(value, exposed_path, canonical_path)

    def _common(
        self,
        value: Any,
        exposed_path: str,
        canonical_path: str | None,
    ) -> dict[str, Any]:
        canonical = canonical_path if canonical_path != exposed_path else None
        return {
            "fqn": exposed_path,
            "source_file": _source_file(value, self.search_path),
            "line": int(getattr(value, "lineno", 0) or 0),
            "canonical_fqn": canonical,
        }

    def _add_class(
        self, value: Any, exposed_path: str, canonical_path: str | None
    ) -> None:
        members = getattr(value, "members", {})
        constructor = members.get("__init__") or members.get("__new__")
        bases = _base_names(value)
        benign_bases = all(
            base.rsplit(".", 1)[-1] in {"object", "Generic", "ABC"}
            for base in bases
        )
        known = (
            constructor is not None
            and not _decorator_names(value)
            and benign_bases
            and "__new__" not in members
        )
        signature = {
            **self._common(
                constructor or value, exposed_path, canonical_path
            ),
            "parameters": _parameters(value, drop_receiver=True),
            "return_annotation": None,
            "return_shape": "unknown",
            "scope": "class",
            "bases": bases,
            "parameters_known": known,
            "callable_kind": "sync",
            "instance_result_known": known,
        }
        self.signatures.setdefault(exposed_path, signature)

    def _add_function(
        self, value: Any, exposed_path: str, canonical_path: str | None
    ) -> None:
        parent = getattr(value, "parent", None)
        parent_is_class = bool(parent is not None and getattr(parent, "is_class", False))
        labels = set(getattr(value, "labels", ()))
        decorators = _decorator_names(value)
        # Griffe normally models properties as Attributes.  When a package or
        # module is itself named ``property`` (for example
        # ``bokeh.core.property``), a read-only built-in ``@property`` can
        # remain a Function whose decorator is still recorded.  Preserve the
        # API kind instead of treating that getter as a method.  Writable
        # properties remain Griffe Attributes handled by ``_add_attribute``.
        is_property = parent_is_class and "property" in decorators
        if is_property:
            scope = "property"
            drop_receiver = True
            structural = {"property"}
        elif parent_is_class and "staticmethod" in labels:
            scope = "staticmethod"
            drop_receiver = False
            structural = {"staticmethod"}
        elif parent_is_class and "classmethod" in labels:
            scope = "classmethod"
            drop_receiver = True
            structural = {"classmethod"}
        elif parent_is_class:
            scope = "method"
            drop_receiver = True
            structural = set()
        else:
            scope = "function"
            drop_receiver = False
            structural = set()
        filepath = _safe_filepath(value)
        node = self.ast_index.function(filepath, int(getattr(value, "lineno", 0) or 0))
        signature = {
            **self._common(value, exposed_path, canonical_path),
            "parameters": (
                [] if is_property else _parameters(value, drop_receiver=drop_receiver)
            ),
            "return_annotation": _annotation(getattr(value, "returns", None)),
            "return_shape": _return_shape(node) if node is not None else "unknown",
            "scope": scope,
            "bases": [],
            "parameters_known": (
                False if is_property else decorators <= structural
            ),
            "callable_kind": (
                _callable_kind(node)
                if node is not None
                else ("async" if "async" in labels else "sync")
            ),
            "instance_result_known": not is_property,
        }
        self.signatures.setdefault(exposed_path, signature)

    def _add_attribute(
        self, value: Any, exposed_path: str, canonical_path: str | None
    ) -> None:
        labels = set(getattr(value, "labels", ()))
        scope = "property" if "property" in labels else "attribute"
        filepath = _safe_filepath(value)
        node = self.ast_index.function(filepath, int(getattr(value, "lineno", 0) or 0))
        signature = {
            **self._common(value, exposed_path, canonical_path),
            "parameters": [],
            "return_annotation": _annotation(getattr(value, "annotation", None)),
            "return_shape": _return_shape(node) if node is not None else "unknown",
            "scope": scope,
            "bases": [],
            "parameters_known": False,
            "callable_kind": (
                _callable_kind(node) if node is not None else "sync"
            ),
            "instance_result_known": False,
        }
        self.signatures.setdefault(exposed_path, signature)

def load_with_griffe(import_name: str, search_path: Path) -> Any:
    return griffe.load(
        import_name,
        search_paths=[search_path],
        submodules=True,
        try_relative_path=False,
        allow_inspection=False,
        force_inspection=False,
        store_source=False,
        resolve_aliases=True,
        resolve_external=False,
        resolve_implicit=False,
    )

def build_knowledge_base(
    *, package: str, version: str, import_name: str, search_path: Path
) -> tuple[Any, dict[str, Any]]:
    root = load_with_griffe(import_name, search_path)
    adapter = GriffeAdapter(
        package=import_name, version=version, search_path=search_path
    )
    knowledge_base = adapter.convert(root)
    # Distribution names and import names differ for packages such as
    # pre-commit and more-itertools.  The on-disk schema uses the distribution.
    knowledge_base["package"] = package
    return root, knowledge_base
