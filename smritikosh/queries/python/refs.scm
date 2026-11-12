(call function: (identifier) @name) @call

(call
  function: (attribute
    object: (identifier) @receiver
    attribute: (identifier) @name)) @call

(call
  function: (attribute
    object: (call function: (identifier) @receiver)
    attribute: (identifier) @name)) @call

(call
  function: (attribute
    object: (attribute) @receiver
    attribute: (identifier) @name)) @call

(call
  function: (attribute
    object: (call function: (attribute) @receiver)
    attribute: (identifier) @name)) @call

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

(assignment
  left: (attribute object: (identifier) @_self) @var
  right: (call function: [(identifier) (attribute)] @type)
  (#eq? @_self "self")) @hint

(class_definition
  name: (identifier) @class_name
  superclasses: (argument_list [(identifier) (attribute)] @base)) @class
