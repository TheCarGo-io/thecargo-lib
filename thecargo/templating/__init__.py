"""Templating engine, variable registry, and renderer for user-authored
templates (SMS bodies, email subjects/bodies, automation templates).

Single source of truth shared by every service that renders or
introspects templates: the registry catalogues every available
placeholder, the renderer is built on Liquid (sandboxed, well-tested),
and the public API is intentionally small so call-sites never reach
into the engine directly.
"""

from thecargo.templating.registry import (
    REGISTRY,
    SCHEMAS,
    FieldDef,
    ObjectSchema,
    Variable,
    VarType,
    registry_tree,
    sample_context,
    suggest_correction,
)
from thecargo.templating.render import (
    RenderResult,
    ValidationIssue,
    legacy_to_liquid,
    render,
    validate,
)

__all__ = [
    "REGISTRY",
    "SCHEMAS",
    "FieldDef",
    "ObjectSchema",
    "RenderResult",
    "Variable",
    "VarType",
    "ValidationIssue",
    "legacy_to_liquid",
    "registry_tree",
    "render",
    "sample_context",
    "suggest_correction",
    "validate",
]
