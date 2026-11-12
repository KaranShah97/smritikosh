"""Call graph: per-file symbols, calls and imports, resolved once all files are in."""

from __future__ import annotations

import builtins
from collections import defaultdict
from functools import cache
from importlib import resources

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language

from smritikosh.engine import sm
from smritikosh.models import (
    Base,
    Call,
    Capture,
    Edge,
    Import,
    ParsedFile,
    Symbol,
    TypeHint,
)

_KINDS = {
    "definition.function": "function",
    "definition.class": "class",
    "definition.method": "method",
    "definition.class_init": "method",
}
_BUILTINS = frozenset(dir(builtins))


@cache
def _refs_query(language: str) -> Query | None:
    ref = resources.files("smritikosh.queries") / language / "refs.scm"
    if not ref.is_file():
        return None
    return Query(get_language(language), ref.read_text(encoding="utf-8"))


@sm.tracked
def graph_file(
    parsed: ParsedFile, captures: list[Capture]
) -> tuple[list[Symbol], list[Call], list[Import], list[TypeHint], list[Base]]:
    query = _refs_query(parsed.language)
    if query is None:
        return [], [], [], [], []

    symbols, spans = _symbols(parsed.path, captures)
    by_id = {s.id: s for s in symbols}
    calls: list[Call] = []
    imports: list[Import] = []
    hints: list[TypeHint] = []
    bases: list[Base] = []
    for _, match in QueryCursor(query).matches(parsed.tree.root_node):
        text = {key: nodes[0].text.decode() for key, nodes in match.items()}
        if "import" in text:
            imports.append(
                Import(
                    path=parsed.path,
                    module=_absolute(text["module"], parsed.path),
                    name=text.get("name"),
                    alias=text.get("alias"),
                )
            )
            continue
        if "hint" in text:
            node = match["hint"][0]
            scope = _innermost(spans, node.start_byte, node.end_byte)
            if scope is not None and text["var"].startswith("self."):
                scope = by_id[scope].parent
            if scope is not None:
                hints.append(TypeHint(parsed.path, scope, text["var"], text["type"]))
            continue
        if "class" in text:
            node = match["class"][0]
            owner = _innermost(spans, node.start_byte, node.end_byte)
            if owner is not None and by_id[owner].name == text["class_name"]:
                bases.append(Base(parsed.path, owner, text["base"]))
            continue
        receiver = text.get("receiver")
        if receiver is None and text["name"] in _BUILTINS:
            continue
        node = match["call"][0]
        scope = _innermost(spans, node.start_byte, node.end_byte)
        if scope is None:
            continue
        calls.append(
            Call(
                path=parsed.path,
                scope=scope,
                receiver=receiver,
                name=text["name"],
                line=node.start_point[0] + 1,
            )
        )
    return symbols, calls, imports, hints, bases


def _symbols(
    path: str, captures: list[Capture]
) -> tuple[list[Symbol], list[tuple[int, int, str]]]:
    defs = sorted(
        (c for c in captures if c.capture_name in _KINDS),
        key=lambda c: c.node.start_byte,
    )
    classes: list[tuple[int, int, str]] = []
    spans: list[tuple[int, int, str]] = []
    qualnames: dict[str, str] = {}
    symbols: list[Symbol] = []
    for capture in defs:
        node = capture.node
        kind = _KINDS[capture.capture_name]
        parent = _innermost(classes, node.start_byte, node.end_byte)
        qualname = f"{qualnames[parent]}.{capture.name}" if parent else capture.name
        symbol_id = f"{path}:{qualname}"
        if symbol_id in qualnames:
            symbol_id = f"{symbol_id}@{node.start_point[0] + 1}"
        qualnames[symbol_id] = qualname
        span = (node.start_byte, node.end_byte, symbol_id)
        spans.append(span)
        if kind == "class":
            classes.append(span)
        symbols.append(
            Symbol(
                id=symbol_id,
                name=capture.name,
                kind=kind,
                path=path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=parent,
            )
        )
    return symbols, spans


def _innermost(spans: list[tuple[int, int, str]], start: int, end: int) -> str | None:
    inside = [span for span in spans if span[0] <= start and end <= span[1]]
    return inside[-1][2] if inside else None


def _absolute(module: str, path: str) -> str:
    dots = len(module) - len(module.lstrip("."))
    if not dots:
        return module
    package = path.split("/")[:-1]
    package = package[: len(package) - dots + 1]
    rest = module[dots:]
    return ".".join([*package, rest] if rest else package)


def resolve(
    paths: set[str],
    symbols: list[Symbol],
    calls: list[Call],
    imports: list[Import],
    hints: list[TypeHint],
    bases: list[Base],
) -> list[Edge]:
    index = _Index(paths, symbols, imports, hints, bases)
    edges: list[Edge] = []
    for call in calls:
        target = index.target(call)
        if target is not None:
            edges.append(Edge(call.scope, target, call.path, call.line))
    return edges


def _one(ids: list[str]) -> str | None:
    return ids[0] if len(ids) == 1 else None


class _Index:
    def __init__(
        self,
        paths: set[str],
        symbols: list[Symbol],
        imports: list[Import],
        hints: list[TypeHint],
        bases: list[Base],
    ) -> None:
        self.kind: dict[str, str] = {}
        self.path: dict[str, str] = {}
        self.parent: dict[str, str | None] = {}
        self.in_file: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.members: dict[tuple[str, str], list[str]] = defaultdict(list)
        for s in symbols:
            self.kind[s.id] = s.kind
            self.path[s.id] = s.path
            self.parent[s.id] = s.parent
            if s.parent is None:
                self.in_file[(s.path, s.name)].append(s.id)
            else:
                self.members[(s.parent, s.name)].append(s.id)

        self.modules: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            if path.endswith(".py"):
                for name in _module_names(path, paths):
                    self.modules[name].append(path)

        self.from_imports: dict[tuple[str, str], tuple[str, str]] = {}
        self.aliases: dict[tuple[str, str], str] = {}
        for i in imports:
            if i.name is None:
                local = i.alias or i.module.split(".")[0]
                self.aliases[(i.path, local)] = i.module if i.alias else local
            else:
                self.from_imports[(i.path, i.alias or i.name)] = (i.module, i.name)

        self.types: dict[tuple[str, str], list[str]] = defaultdict(list)
        for h in hints:
            self.types[(h.scope, h.name)].append(h.type_name)
        self.bases: dict[str, list[str]] = defaultdict(list)
        for b in bases:
            self.bases[b.symbol].append(b.name)

    def target(self, call: Call) -> str | None:
        if call.receiver in ("self", "cls"):
            return self.member(self.parent.get(call.scope), call.name)
        if call.receiver is None:
            return self.lookup(call.path, call.name)
        module = self.module_of(call.path, call.receiver)
        if module is not None:
            return _one(self.in_file.get((module, call.name), []))
        owner = self.class_of(call.path, call.receiver) or self.type_of(call)
        return self.member(owner, call.name)

    def member(
        self, owner: str | None, name: str, seen: set[str] | None = None
    ) -> str | None:
        if owner is None:
            return None
        seen = set() if seen is None else seen
        if owner in seen:
            return None
        seen.add(owner)
        found = self.members.get((owner, name))
        if found:
            return _one(found)
        for base in self.bases.get(owner, []):
            target = self.member(self.class_of(self.path[owner], base), name, seen)
            if target is not None:
                return target
        return None

    def class_of(self, path: str, name: str) -> str | None:
        module, _, last = name.rpartition(".")
        if module:
            module_path = self.module_of(path, module)
            found = (
                _one(self.in_file.get((module_path, last), [])) if module_path else None
            )
        else:
            found = self.lookup(path, name)
        return found if found is not None and self.kind[found] == "class" else None

    def type_of(self, call: Call) -> str | None:
        scope = call.scope
        if call.receiver.startswith("self."):
            scope = self.parent.get(call.scope)
        classes = {
            found
            for type_name in self.types.get((scope, call.receiver), [])
            if (found := self.class_of(call.path, type_name)) is not None
        }
        return classes.pop() if len(classes) == 1 else None

    def lookup(self, path: str, name: str) -> str | None:
        local = self.in_file.get((path, name))
        if local:
            return _one(local)
        imported = self.from_imports.get((path, name))
        if imported:
            module = self.module_path(imported[0])
            if module is None:
                return None
            return _one(self.in_file.get((module, imported[1]), []))
        return None

    def module_of(self, path: str, local: str) -> str | None:
        if (path, local) in self.aliases:
            return self.module_path(self.aliases[(path, local)])
        imported = self.from_imports.get((path, local))
        if imported:
            return self.module_path(".".join(imported))
        return None

    def module_path(self, module: str) -> str | None:
        return _one(self.modules.get(module, []))


def _module_names(path: str, paths: set[str]) -> set[str]:
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    dirs = path.split("/")[:-1]
    root = len(dirs)
    while root and "/".join(dirs[:root]) + "/__init__.py" in paths:
        root -= 1
    return {".".join(parts), ".".join(parts[root:])} - {""}
