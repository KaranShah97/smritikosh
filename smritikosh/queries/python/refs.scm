; Python call-graph facts: calls, imports, type hints and base classes.
;
; Read only by indexing/graph.py, never by the chunker, so none of this changes
; how files are chunked. graph_file() tells the families apart by capture name:
; @import, @hint and @class rows, and everything else is a @call. Every name is
; stored as written; resolve() links it to a definition after all files are in.

; ── calls ────────────────────────────────────────────────────────────────────
; @receiver is the text before the dot, or absent for a bare call. A bare call
; to a builtin is dropped, and a call outside any definition has no caller.

(call function: (identifier) @name) @call

; x.f() — x is an import, a class, or a local the resolver may have a type for.

(call
  function: (attribute
    object: (identifier) @receiver
    attribute: (identifier) @name)) @call

; X().f() — the receiver is the constructor's name, resolved like a class.

(call
  function: (attribute
    object: (call function: (identifier) @receiver)
    attribute: (identifier) @name)) @call

; self.client.f() and a.b.f(). Recorded even when they can't be resolved, so
; explore impact counts them as unresolved instead of reporting no callers.

(call
  function: (attribute
    object: (attribute) @receiver
    attribute: (identifier) @name)) @call

; Factory.get().f() — the receiver is the call that produced the object.

(call
  function: (attribute
    object: (call function: (attribute) @receiver)
    attribute: (identifier) @name)) @call

; ── imports ──────────────────────────────────────────────────────────────────
; `import a.b`, `import a.b as c`, `from m import x`, `from m import x as y`.
; Relative modules (`from ..util import x`) are made absolute in graph_file().

(import_statement name: (dotted_name) @module) @import

(import_statement
  name: (aliased_import
    name: (dotted_name) @module
    alias: (identifier) @alias)) @import

(import_from_statement
  module_name: (_) @module
  name: (dotted_name) @name) @import

(import_from_statement
  module_name: (_) @module
  name: (aliased_import
    name: (dotted_name) @name
    alias: (identifier) @alias)) @import

; ── type hints ───────────────────────────────────────────────────────────────
; What a name's type is, per scope: typed parameters, annotated assignments and
; constructor assignments. @type is kept as written; it only becomes a type if
; it resolves to a repo class, so `x = make_repo()` adds nothing. A name hinted
; with two different classes in one scope gets no type at all.

(typed_parameter
  (identifier) @var
  type: (type [(identifier) (attribute)] @type)) @hint

(typed_default_parameter
  name: (identifier) @var
  type: (type [(identifier) (attribute)] @type)) @hint

(assignment
  left: (identifier) @var
  type: (type [(identifier) (attribute)] @type)) @hint

(assignment
  left: (identifier) @var
  right: (call function: [(identifier) (attribute)] @type)) @hint

; self.x = C() in any method types self.x for the whole class.

(assignment
  left: (attribute object: (identifier) @_self) @var
  right: (call function: [(identifier) (attribute)] @type)
  (#eq? @_self "self")) @hint

; ── base classes ─────────────────────────────────────────────────────────────
; One row per base as written, so self.f() and C.f() can find inherited
; methods. Keyword arguments such as metaclass= are not bases and don't match.

(class_definition
  name: (identifier) @class_name
  superclasses: (argument_list [(identifier) (attribute)] @base)) @class
