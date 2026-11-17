"""Source-only supplements for fields absent from the Griffe model."""

from __future__ import annotations

import ast
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .constants import SOURCE_OVERLAY_SKIP_DIRS

def _block_always_exits(statements: list[ast.stmt]) -> bool:
    for statement in statements:
        if isinstance(statement, (ast.Return, ast.Raise)):
            return True
        if isinstance(statement, ast.If) and statement.orelse:
            if _block_always_exits(statement.body) and _block_always_exits(
                statement.orelse
            ):
                return True
        if isinstance(statement, (ast.With, ast.AsyncWith)) and _block_always_exits(
            statement.body
        ):
            return True
        if isinstance(statement, (ast.Try, ast.TryStar)):
            if statement.finalbody and _block_always_exits(statement.finalbody):
                return True
            if (
                statement.handlers
                and _block_always_exits(statement.body)
                and all(
                    _block_always_exits(handler.body)
                    for handler in statement.handlers
                )
                and (
                    not statement.orelse
                    or _block_always_exits(statement.orelse)
                )
            ):
                return True
    return False

def _return_shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    shapes: set[str] = set()

    class ReturnVisitor(ast.NodeVisitor):
        def visit_Return(self, return_node: ast.Return) -> None:
            if return_node.value is None:
                shapes.add("none")
            elif isinstance(return_node.value, (ast.Tuple, ast.List)):
                if any(
                    isinstance(element, ast.Starred)
                    for element in return_node.value.elts
                ):
                    shapes.add("unknown")
                else:
                    shapes.add(f"tuple:{len(return_node.value.elts)}")
            else:
                shapes.add("value")

        def visit_Yield(self, yield_node: ast.Yield) -> None:
            shapes.add("unknown")

        def visit_YieldFrom(self, yield_node: ast.YieldFrom) -> None:
            shapes.add("unknown")

        def visit_FunctionDef(self, nested: ast.FunctionDef) -> None:
            if nested is node:
                self.generic_visit(nested)

        def visit_AsyncFunctionDef(self, nested: ast.AsyncFunctionDef) -> None:
            if nested is node:
                self.generic_visit(nested)

        def visit_ClassDef(self, nested: ast.ClassDef) -> None:
            return

    ReturnVisitor().visit(node)
    if "unknown" in shapes:
        return "unknown"
    if shapes and not _block_always_exits(node.body):
        shapes.add("none")
    if not shapes:
        return "unknown" if _block_always_exits(node.body) else "none"
    if len(shapes) == 1:
        return next(iter(shapes))
    return "mixed"

def _callable_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    has_yield = False

    class YieldVisitor(ast.NodeVisitor):
        def visit_Yield(self, yield_node: ast.Yield) -> None:
            nonlocal has_yield
            has_yield = True

        def visit_YieldFrom(self, yield_node: ast.YieldFrom) -> None:
            nonlocal has_yield
            has_yield = True

        def visit_FunctionDef(self, nested: ast.FunctionDef) -> None:
            if nested is node:
                self.generic_visit(nested)

        def visit_AsyncFunctionDef(self, nested: ast.AsyncFunctionDef) -> None:
            if nested is node:
                self.generic_visit(nested)

        def visit_ClassDef(self, nested: ast.ClassDef) -> None:
            return

    YieldVisitor().visit(node)
    if has_yield:
        return "async_generator" if isinstance(
            node, ast.AsyncFunctionDef
        ) else "generator"
    return "async" if isinstance(node, ast.AsyncFunctionDef) else "sync"

class AstIndex:
    """Small source-side supplement for fields Griffe intentionally omits."""

    def __init__(self) -> None:
        self._cache: dict[Path, dict[int, ast.FunctionDef | ast.AsyncFunctionDef]] = {}

    def function(
        self, path: Path | None, lineno: int
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        if path is None or not path.is_file() or lineno <= 0:
            return None
        resolved = path.resolve()
        if resolved not in self._cache:
            try:
                tree = ast.parse(resolved.read_text(encoding="utf-8"), str(resolved))
            except (OSError, UnicodeError, SyntaxError):
                self._cache[resolved] = {}
            else:
                self._cache[resolved] = {
                    node.lineno: node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
        return self._cache[resolved].get(lineno)

@dataclass(frozen=True)
class SourceImportEdge:
    exposed_fqn: str
    target_fqn: str
    source_file: str
    line: int

def _source_module_name(search_path: Path, path: Path) -> tuple[str, bool]:
    relative = path.relative_to(search_path)
    parts = list(relative.parts)
    is_init = parts[-1] == "__init__.py"
    if is_init:
        parts = parts[:-1]
    else:
        parts[-1] = path.stem
    return ".".join(parts), is_init

def _resolve_source_import(
    current_module: str,
    *,
    is_init: bool,
    level: int,
    imported_module: str | None,
) -> str:
    if level == 0:
        return imported_module or ""
    package_parts = (
        current_module.split(".")
        if is_init
        else current_module.split(".")[:-1]
    )
    remove = max(level - 1, 0)
    if remove:
        package_parts = package_parts[:-remove]
    if imported_module:
        package_parts.extend(imported_module.split("."))
    return ".".join(package_parts)

def _source_import_edges(search_path: Path, package: str) -> tuple[
    list[SourceImportEdge], list[dict[str, str]]
]:
    """Read explicit, runtime-visible ``from`` imports from the source tree.

    Griffe cannot represent a submodule and a same-named imported object at the
    same path.  It can also omit implicit namespace subpackages.  This overlay
    recovers only exposed names; callable signatures still come from Griffe's
    canonical objects.
    """

    package_dir = search_path.joinpath(*package.split("."))
    files: list[Path]
    if package_dir.is_dir():
        files = [
            path
            for path in package_dir.rglob("*.py")
            if not any(
                part in SOURCE_OVERLAY_SKIP_DIRS
                for part in path.relative_to(package_dir).parts[:-1]
            )
        ]
    else:
        module_file = search_path.joinpath(*package.split(".")).with_suffix(".py")
        files = [module_file] if module_file.is_file() else []
    edges: list[SourceImportEdge] = []
    errors: list[dict[str, str]] = []
    for path in sorted(files):
        module, is_init = _source_module_name(search_path, path)
        try:
            with tokenize.open(path) as stream:
                tree = ast.parse(stream.read(), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(
                {
                    "source_file": path.relative_to(search_path).as_posix(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_module = _resolve_source_import(
                module,
                is_init=is_init,
                level=node.level,
                imported_module=node.module,
            )
            if not imported_module:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                exposed_name = alias.asname or alias.name
                if exposed_name.startswith("_"):
                    continue
                exposed_fqn = f"{module}.{exposed_name}"
                target_fqn = f"{imported_module}.{alias.name}"
                if not (
                    target_fqn == package
                    or target_fqn.startswith(f"{package}.")
                ):
                    continue
                edges.append(
                    SourceImportEdge(
                        exposed_fqn=exposed_fqn,
                        target_fqn=target_fqn,
                        source_file=path.relative_to(search_path).as_posix(),
                        line=node.lineno,
                    )
                )
    unique = {
        (edge.exposed_fqn, edge.target_fqn): edge
        for edge in edges
    }
    return sorted(
        unique.values(),
        key=lambda edge: (edge.exposed_fqn, edge.target_fqn),
    ), errors
