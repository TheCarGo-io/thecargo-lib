"""Render and validate user-authored templates against a context.

The engine is :mod:`liquid` (python-liquid) — chosen because:

* its sandbox forbids attribute access on host objects, so user
  templates can't reach into Python state even if a future template
  comes from an untrusted source;
* a near-identical implementation exists for the browser
  (``liquidjs``), so the admin UI can render a live preview that
  matches what the server will produce on send;
* loops, conditionals, and filters are first-class — covering every
  shipment use case (multi-vehicle, multi-stop, conditional CC, etc.)
  without us reinventing them.

This module is the **only** place call-sites should touch Liquid; the
public API is :func:`render`, :func:`validate`, and
:func:`legacy_to_liquid`. Rest of the codebase imports those from
``thecargo.templating``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from liquid import Environment, Mode
from liquid.exceptions import LiquidSyntaxError, UndefinedError

from thecargo.templating.filters import FILTERS
from thecargo.templating.registry import REGISTRY, suggest_correction

_KNOWN_PATHS: frozenset[str] = frozenset(v.path for v in REGISTRY) | frozenset(
    v.path.split("[")[0] for v in REGISTRY if "[" in v.path
)
# Top-level keys reachable through the context dict but not always
# explicitly listed in REGISTRY (e.g. ``files``, ``stops`` as iterables
# without dot-paths). Validators tolerate these.
_KNOWN_ROOTS: frozenset[str] = frozenset(
    {"customer", "shipment", "agent", "pickup", "delivery", "vehicles", "stops", "files", "tags", "_meta"}
)


# ── Environment ──────────────────────────────────────────────────────


def _build_env() -> Environment:
    """python-liquid 1.x's Environment.

    Notes on configuration choices:

    * ``autoescape=False`` — SMS is plain text and email body is HTML
      that the caller is responsible for. We don't autoescape because
      autoescape would turn ``<br>`` in templates into ``&lt;br&gt;``,
      breaking long-standing user templates.
    * ``strict_filters=False`` — an unknown filter renders as a no-op
      rather than a 500. The validator surfaces it as a warning.
    * ``tolerance=Mode.LAX`` — same idea applied to other parser
      tolerance toggles.

    Variable-level laxity (unknown variable → empty string) is the
    library default: the standard ``Undefined`` class renders empty
    when accessed.
    """
    env = Environment(
        autoescape=False,
        strict_filters=False,
        tolerance=Mode.LAX,
    )
    for name, fn in FILTERS.items():
        env.add_filter(name, fn)
    return env


_ENV: Environment = _build_env()


# ── Public API ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderResult:
    """Three-state result so callers can pick fail-loud vs fail-soft.

    ``ok`` is true for every render that produced a string (even if
    some variables were undefined and rendered empty); ``errors``
    captures syntax/parse failures, which a caller in a send pipeline
    will typically convert to a 4xx instead of shipping a broken
    message to the customer.
    """

    ok: bool
    text: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    message: str
    line: int | None = None
    column: int | None = None
    suggestion: str | None = None


def render(template: str, context: dict | None) -> RenderResult:
    """Render ``template`` with ``context``.

    Legacy compatibility — templates saved with single-brace ``{key}``
    or flat-key ``{{key}}`` syntax (pre-Liquid migration) are rewritten
    on the fly so the org admin's existing library keeps working
    without forcing them to re-edit every row. New templates use full
    Liquid (``{{ namespace.key }}``) and are unaffected.

    Empty/None template short-circuits to an empty success — this
    matches existing call-sites that pass partially-filled message
    bodies.
    """
    if not template:
        return RenderResult(ok=True, text="")
    ctx = context or {}
    template = legacy_to_liquid(template)
    try:
        tpl = _ENV.from_string(template)
    except LiquidSyntaxError as exc:
        return RenderResult(ok=False, text="", errors=(str(exc),))
    try:
        out = tpl.render(**ctx)
    except UndefinedError as exc:
        return RenderResult(ok=False, text="", errors=(str(exc),))
    except Exception as exc:  # filter raised, etc.
        return RenderResult(ok=False, text="", errors=(f"render failed: {exc}",))
    return RenderResult(ok=True, text=out)


def validate(template: str) -> tuple[ValidationIssue, ...]:
    """Static-check a template without a context.

    Catches syntax errors plus references to variables we don't
    recognise (with a Levenshtein "did you mean…" hint). Loop variables
    inside ``{% for x in xs %}`` aren't flagged as unknown — only the
    top-level path is checked.
    """
    if not template:
        return ()
    issues: list[ValidationIssue] = []
    try:
        _ENV.parse(template)
    except LiquidSyntaxError as exc:
        return (ValidationIssue("error", str(exc)),)

    loop_vars = set(_LOOP_VAR_RE.findall(template))
    for match in _VARIABLE_RE.finditer(template):
        path = match.group(1)
        root = path.split(".")[0].split("[")[0]
        # loop variable like ``v`` from ``{% for v in vehicles %}``
        if root in loop_vars:
            continue
        # exact known path
        if path in _KNOWN_PATHS:
            continue
        # bare root reference (``vehicles`` itself, used by ``size`` etc.)
        if "." not in path and "[" not in path and root in _KNOWN_ROOTS:
            continue
        # nested dotted path under a known root that we don't catalogue
        # (rare — REGISTRY normally lists every leaf). Surface as a
        # *warning* so the user notices, but only if no closer
        # suggestion exists.
        suggestion = suggest_correction(path)
        line = template.count("\n", 0, match.start()) + 1
        issues.append(
            ValidationIssue(
                severity="warning",
                message=f"Unknown variable: {path}",
                line=line,
                suggestion=suggestion,
            )
        )
    return tuple(issues)


# ── Legacy compatibility ─────────────────────────────────────────────

_LEGACY_MAPPING: dict[str, str] = {
    # Single-brace flat keys → Liquid namespaced equivalents.
    "customer_first_name": "customer.first_name",
    "customer_last_name": "customer.last_name",
    "customer_name": "customer.full_name",
    "customer_email": "customer.email",
    "customer_phone": "customer.phone | phone",
    "shipment_code": "shipment.code",
    "code": "shipment.code",
    "origin_city": "pickup.city",
    "origin_state": "pickup.state",
    "destination_city": "delivery.city",
    "destination_state": "delivery.state",
    "vehicle_year": "vehicles[0].year",
    "vehicle_make": "vehicles[0].make",
    "vehicle_model": "vehicles[0].model",
    "tariff": "shipment.tariff | currency",
    "first_available_date": "shipment.first_available_date | date_short",
    "agent_name": "agent.name",
}


def legacy_to_liquid(template: str) -> str:
    """One-shot conversion of legacy ``{key}`` syntax to Liquid.

    * ``{{key}}`` (already double-brace) → keeps the path but rewrites
      the key if a mapping exists.
    * ``{key}`` (single brace) → ``{{ liquid.path }}``.

    Unknown legacy keys are passed through verbatim so the migration
    script can surface them for human review instead of silently
    dropping data.
    """
    if not template:
        return template

    def _replace_double(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        liquid_path = _LEGACY_MAPPING.get(key, key)
        return "{{ " + liquid_path + " }}"

    def _replace_single(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key not in _LEGACY_MAPPING:
            return m.group(0)
        return "{{ " + _LEGACY_MAPPING[key] + " }}"

    out = _DOUBLE_BRACE_LEGACY_RE.sub(_replace_double, template)
    out = _SINGLE_BRACE_LEGACY_RE.sub(_replace_single, out)
    return out


# ── Regexes used by validate / legacy migration ──────────────────────

# Match `{{ path }}` and `{{ path | filter }}` — captures the path part only.
_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.\[\]]*)(?:\s*\|[^}]*)?\s*\}\}")
# Match loop variables introduced by `{% for x in xs %}`.
_LOOP_VAR_RE = re.compile(r"\{%\s*for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+", re.IGNORECASE)
# Pre-Liquid `{{key}}` (no spaces, flat name).
_DOUBLE_BRACE_LEGACY_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
# Pre-Liquid `{key}`.
_SINGLE_BRACE_LEGACY_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
