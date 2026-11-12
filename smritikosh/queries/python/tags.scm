; Python tags. Derived from tree-sitter/tree-sitter-python queries/tags.scm (MIT).
;
; Definitions only. The upstream file also emits @reference.call, which measured
; at 6.9x the definition volume across the reference corpus and has no consumer
; in the chunker. The call graph's calls, imports and type hints live in
; refs.scm instead, so the chunker never sees them.
;
; `async def` is a plain function_definition with an optional `async` token, and
; `X: Final[int] = 1` is an assignment carrying a `type:` field. Neither
; async_function_definition nor annotated_assignment exists in this grammar.

; ── module-level functions ───────────────────────────────────────────────────

(module
  (function_definition
    name: (identifier) @name) @definition.function)

(module
  (decorated_definition
    definition: (function_definition
      name: (identifier) @name)) @definition.function)

; ── classes ──────────────────────────────────────────────────────────────────

(module
  (class_definition
    name: (identifier) @name) @definition.class)

(module
  (decorated_definition
    definition: (class_definition
      name: (identifier) @name)) @definition.class)

; ── enums ────────────────────────────────────────────────────────────────────
; Deliberately overlaps @definition.class: an enum matches both, and the
; chunker's CAPTURE_PRIORITY resolves it in favour of the enum so the whole
; type lands in one chunk. Covers the mixin form (str, Enum), direct
; StrEnum/IntEnum inheritance, and the qualified enum.Enum form.

(class_definition
  name: (identifier) @name
  superclasses: (argument_list
    [
      (identifier) @_base
      (attribute
        attribute: (identifier) @_base)
    ]
    (#match? @_base "^(Enum|StrEnum|IntEnum|IntFlag|Flag|ReprEnum)$"))) @definition.enum

; ── constructors ─────────────────────────────────────────────────────────────
; Captured separately from methods so the chunker can absorb __init__ into its
; class's chunk rather than emitting it on its own.

(class_definition
  body: (block
    (function_definition
      name: (identifier) @name
      (#eq? @name "__init__")) @definition.class_init))

; ── methods ──────────────────────────────────────────────────────────────────

(class_definition
  body: (block
    (function_definition
      name: (identifier) @name
      (#not-eq? @name "__init__")) @definition.method))

(class_definition
  body: (block
    (decorated_definition
      definition: (function_definition
        name: (identifier) @name
        (#not-eq? @name "__init__"))) @definition.method))

; ── module constants ─────────────────────────────────────────────────────────
; Plain and annotated both parse as `assignment`; there is no
; expression_statement wrapper in this grammar.

(module
  (assignment
    left: (identifier) @name
    (#match? @name "^[A-Z][A-Z0-9_]*$")) @definition.constant)

; ── class constants ──────────────────────────────────────────────────────────

(class_definition
  body: (block
    (assignment
      left: (identifier) @name
      (#match? @name "^[A-Z][A-Z0-9_]*$")) @definition.class_constant))

; ── type aliases ─────────────────────────────────────────────────────────────
; The PEP 695 statement form, plus the assignment form that dominates in
; practice: `SerializableDecimal = Annotated[Decimal, PlainSerializer(...)]`.
; The name pattern requires a lowercase letter so it selects PascalCase and
; leaves SCREAMING_CASE to @definition.constant above.

(module
  (type_alias_statement
    left: (type
      (identifier) @name)) @definition.type)

(module
  (assignment
    left: (identifier) @name
    (#match? @name "^[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*$")) @definition.type)
