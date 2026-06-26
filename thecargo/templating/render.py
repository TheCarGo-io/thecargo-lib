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

_REGISTRY_ROOTS: frozenset[str] = frozenset(v.path.split(".")[0].split("[")[0] for v in REGISTRY)
_CONTEXT_EXTRA_ROOTS: frozenset[str] = frozenset(
    {
        "customer",
        "shipment",
        "pricing",
        "agent",
        "company",
        "org",
        "carrier",
        "pickup",
        "delivery",
        "stops",
        "vehicle",
        "vehicles",
        "files",
        "tags",
        "payment",
        "vehicles_summary",
        "online_booking",
        "tracking_link",
        "current_time",
        "origin",
        "destination",
        "_meta",
    }
)
_KNOWN_VAR_ROOTS: frozenset[str] = _KNOWN_ROOTS | _REGISTRY_ROOTS | _CONTEXT_EXTRA_ROOTS


# ── Environment ──────────────────────────────────────────────────────


def _build_env() -> Environment:
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
    if not template:
        return template

    def _replace_double(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        liquid_path = _LEGACY_MAPPING.get(key, key)
        return "{{ " + liquid_path + " }}"

    def _replace_single(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        filt = (m.group(2) or "").strip()
        if key in _LEGACY_MAPPING:
            return "{{ " + _LEGACY_MAPPING[key] + " }}"
        root = key.split(".")[0].split("[")[0]
        if root in _KNOWN_VAR_ROOTS:
            return "{{ " + key + (" " + filt if filt else "") + " }}"
        return m.group(0)

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
_SINGLE_BRACE_LEGACY_RE = re.compile(
    r"(?<!\{)\{\s*"
    r"([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*|\[[0-9]+\])*)"
    r"(\s*\|\s*[^{}]*?)?"
    r"\s*\}(?!\})"
)
