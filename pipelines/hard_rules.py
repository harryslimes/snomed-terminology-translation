"""Hard rules — non-negotiable translation constraints that sit *beside* the
style guide rather than inside it.

Motivation
----------
GEPA optimises a single mutable string (``signature.instructions`` = the whole
style guide). It will happily flip any clause if the metric pays for it — so
when the reference data carries an inconsistency (e.g. a 70:30 split between
two acceptable forms), GEPA wastes budget oscillating, and a noisy dev split
can flip a rule we'd rather pin. Hard rules give us two levers GEPA can't erode:

1. **Freeze** (``freeze: true``) — the rule text is injected into the prompt as
   a constant *input field*, never as part of the optimisable instruction
   string, so reflective mutation can't rewrite or delete it.
2. **Enforce** (``enforce: true``) — the metric applies a score *penalty* when a
   candidate violates the rule, removing the reward signal that made GEPA
   explore the disallowed form in the first place. (Today's hints only add
   feedback text; they don't move the score, so they don't actually pin a rule.)

Freeze alone is necessary but not sufficient: GEPA can still add a *mutable*
clause that contradicts a frozen rule. Only the enforce penalty makes such a
clause lower-scoring, so it dies in selection. Use both to truly lock a rule.

This module is deliberately dependency-light (stdlib + PyYAML only) so the
metric, the DSPy harness, and any future production-prompt path can all share
it without dragging in dspy/LiteLLM — same reasoning as ``pipelines.scoring``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# A violation costs this much of the [0, 1] metric score unless the rule
# overrides it. Tuned to dominate a marginal chrF gain (~0.1) so GEPA can't
# "buy back" a violation with a slightly closer surface form.
DEFAULT_PENALTY = 0.25


@dataclass
class HardRule:
    """One non-negotiable constraint.

    A rule is *enforced* (scored in the metric), *frozen* (injected verbatim
    into the prompt), or both. A rule that is neither is inert documentation.
    """

    id: str
    description: str = ""
    # ECL expression naming the concepts the rule applies to. Stored for the
    # frozen-block text and future per-concept scoping; the metric's violation
    # check is currently surface-form based (scope-agnostic) because the GEPA
    # harness scores against references, not live SNOMED structure.
    scope: str = "<<138875005"
    # The preferred form(s). Documentation for the frozen block + the violation
    # message; not matched directly (see `forbidden`).
    canonical: list[str] = field(default_factory=list)
    # Substrings that must never appear in the output.
    forbidden: list[str] = field(default_factory=list)
    # Regex patterns that must never match the output.
    forbidden_regex: list[str] = field(default_factory=list)
    enforce: bool = True
    freeze: bool = True
    penalty: float = DEFAULT_PENALTY
    # Optional hand-written prompt text; if absent the frozen block is composed
    # from description + canonical/forbidden.
    text: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "HardRule":
        def _as_list(v) -> list[str]:
            if v is None:
                return []
            if isinstance(v, str):
                return [v]
            return [str(x) for x in v]

        if "id" not in d:
            raise ValueError(f"hard rule missing required 'id': {d!r}")
        return cls(
            id=str(d["id"]),
            description=str(d.get("description", "")),
            scope=str(d.get("scope", "<<138875005")),
            canonical=_as_list(d.get("canonical")),
            forbidden=_as_list(d.get("forbidden")),
            forbidden_regex=_as_list(d.get("forbidden_regex")),
            enforce=bool(d.get("enforce", True)),
            freeze=bool(d.get("freeze", True)),
            penalty=float(d.get("penalty", DEFAULT_PENALTY)),
            text=str(d.get("text", "")),
        )

    def compiled_regex(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.forbidden_regex]


def load_hard_rules(src: "dict | Path | str | None") -> list[HardRule]:
    """Load hard rules from a YAML path, an already-parsed dict, or None.

    YAML shape (mirrors configs/hints/<lang>.yaml — data, not logic):

        language: ko
        rules:
          - id: no-trailing-punctuation
            enforce: true
            freeze: true
            forbidden_regex: ['[.,;:]$']

    Returns ``[]`` for None/empty so callers stay backward-compatible.
    """
    if src is None:
        return []
    if isinstance(src, dict):
        data = src
    else:
        import yaml
        data = yaml.safe_load(Path(src).read_text(encoding="utf-8")) or {}
    raw_rules = data.get("rules") if isinstance(data, dict) else data
    return [HardRule.from_dict(r) for r in (raw_rules or [])]


def frozen_block(rules: list[HardRule]) -> str:
    """Render the freeze=True rules as a markdown block for prompt injection.

    Returns "" when no rule is frozen, so callers can fall back to the
    2-input signature and keep behaviour identical to the pre-hard-rules path.
    """
    frozen = [r for r in rules if r.freeze]
    if not frozen:
        return ""
    lines = [
        "These constraints are NON-NEGOTIABLE. They override anything in the "
        "style guide. Never violate them, even if an example or reference "
        "suggests otherwise.",
        "",
    ]
    for r in frozen:
        if r.text:
            lines.append(f"- {r.text}")
            continue
        bits = [r.description or r.id]
        if r.canonical:
            bits.append("Use: " + ", ".join(r.canonical) + ".")
        if r.forbidden:
            bits.append("Never use: " + ", ".join(r.forbidden) + ".")
        lines.append("- " + " ".join(bits))
    return "\n".join(lines)


def find_violations(
    candidate: str, rules: list[HardRule]
) -> list[tuple[HardRule, str]]:
    """Return (rule, message) for every enforce=True rule the candidate breaks.

    Surface-form matching only: a forbidden substring present, or a forbidden
    regex matching. Scope is not consulted here (see HardRule.scope).
    """
    out: list[tuple[HardRule, str]] = []
    for r in rules:
        if not r.enforce:
            continue
        for tok in r.forbidden:
            if tok and tok in candidate:
                out.append((r, f"[{r.id}] forbidden form '{tok}' present"))
        for pat in r.compiled_regex():
            if pat.search(candidate):
                out.append((r, f"[{r.id}] matches forbidden pattern /{pat.pattern}/"))
    return out


def penalty_for(violations: list[tuple[HardRule, str]]) -> float:
    """Total score penalty for a set of violations (sum of per-rule penalties).

    Deduplicates by rule id so a rule that fires twice isn't double-charged.
    """
    seen: dict[str, float] = {}
    for rule, _ in violations:
        seen[rule.id] = rule.penalty
    return sum(seen.values())
