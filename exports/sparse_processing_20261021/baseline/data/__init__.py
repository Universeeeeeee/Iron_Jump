"""Data access layer.

Provides persistence stores such as ``subject_store``.

The ``__init__.py`` marks this directory as a regular package rather than a
namespace package. It is not currently shadowed, but it mirrors the top-level
``config`` package: without this file a same-named subpackage (e.g.
``agent/data``) created later would silently shadow ``data`` whenever a script
is run from a directory that contains it.
"""
