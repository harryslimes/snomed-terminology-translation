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
it without dragging in dspy/LiteLLM — same reasoning as ``snomed_translation.scoring``.
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
    # Regex on the SOURCE term. When set, the rule only fires for concepts
    # whose English matches — making the rule a statement about a MAPPING
    # rather than about the target string alone.
    #
    # The most valuable defect class we have is source-conditional and cannot
    # be expressed without this. 위팔 (upper arm) is correct Korean for "upper
    # arm", for 위팔뼈 (humerus) and for 위팔동맥 (brachial artery); it is wrong
    # only where the source says "upper limb". Banning the substring outright
    # flagged 64 rows of which 40 were correct — 63% false positives — and
    # would have refused correct translations forever after.
    when_source: str = ""
    # Worked examples: {"flag": [{source, target}, ...], "pass": [...]}.
    # `flag` must violate the rule, `pass` must not. Checked by
    # check_rule_examples and by the test suite, so a rule that stops firing —
    # or starts over-firing — fails loudly instead of silently changing what
    # ships. These rules gate both GEPA scoring and the deliverable, and the
    # first version of upper-limb-not-upper-arm was 63% false positives, so
    # "the regex looks right" is not good enough.
    examples: dict = field(default_factory=dict)
    enforce: bool = True
    freeze: bool = True
    # Master off switch. A rule kept in the file for documentation, or parked
    # pending validation, sets enabled: false and is dropped at load time so
    # NO consumer sees it. Previously `enforce: false` was doing double duty as
    # this switch, which broke the moment the validator started checking
    # non-enforced rules: example-native-body-site is disabled on purpose (an
    # ablation found prescribing native body sites hurts) and would otherwise
    # have started emitting warnings for 하지/상지.
    enabled: bool = True
    # How an OUTPUT violation is treated by validate_translations:
    #   "blocker" — malformed or clinically wrong; gates the deliverable
    #   "warning" — a style preference the SME accepts as synonymy; surfaces
    #               in review priority but never blocks
    # Independent of `penalty`, which is the optimiser's concern.
    severity: str = "warning"
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
            when_source=str(d.get("when_source", "")),
            examples=dict(d.get("examples") or {}),
            enforce=bool(d.get("enforce", True)),
            freeze=bool(d.get("freeze", True)),
            enabled=bool(d.get("enabled", True)),
            severity=str(d.get("severity", "warning")).strip().lower(),
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
    rules = [HardRule.from_dict(r) for r in (raw_rules or [])]
    return [r for r in rules if r.enabled]


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
    candidate: str, rules: list[HardRule], *, require_enforce: bool = True,
    source: str = ""
) -> list[tuple[HardRule, str]]:
    """Return (rule, message) for every rule the candidate breaks.

    Surface-form matching only: a forbidden substring present, or a forbidden
    regex matching. Scope is not consulted here (see HardRule.scope).

    ``require_enforce`` keeps the two switches independent, as the rules file
    has always documented them: ``enforce`` decides whether the OPTIMISER
    subtracts a penalty, ``severity`` decides whether a VALIDATOR treats the
    violation as shipping-blocking. Callers that score for GEPA keep the
    default; ``validate_translations`` passes False so an enforce=False rule
    is still checked against output.

    They were not actually independent before: this function skipped
    enforce=False rules outright, so a rule written to gate the deliverable
    without steering the prompt was silently a no-op. That is exactly the
    combination sme-rejected-body-site needs — a prior ablation found that
    PRESCRIBING native body sites hurts quality, so the terms must not enter
    the prompt or the metric, while shipping them still has to be caught.
    """
    out: list[tuple[HardRule, str]] = []
    for r in rules:
        if require_enforce and not r.enforce:
            continue
        if r.when_source:
            # A source-conditional rule is INERT without a source term rather
            # than firing blindly: callers that score a bare candidate (the
            # GEPA metric) must not be handed violations they cannot evaluate.
            if not source or not re.search(r.when_source, source, re.I):
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


def check_rule_examples(rules: list[HardRule]) -> list[str]:
    """Verify each rule's worked examples. Returns a list of failure messages.

    A rule file gates both GEPA scoring and what ships to a reviewer, so a
    regex that quietly stops matching — or starts matching correct output — is
    an expensive silent failure. The first version of upper-limb-not-upper-arm
    banned the substring 위팔 outright and flagged 40 correct rows (위팔뼈 is
    humerus, 위팔동맥 is the brachial artery); nothing caught it because a rule
    that fires looks identical to a rule that fires *correctly*.

    Rules without examples are skipped, not failed: backfilling every existing
    rule is a separate job, and refusing to load them would take the
    deliverable down.
    """
    failures: list[str] = []
    for rule in rules:
        for kind in ("flag", "pass"):
            for ex in rule.examples.get(kind) or []:
                target = str(ex.get("target", ""))
                source = str(ex.get("source", ""))
                hit = bool(find_violations(target, [rule], require_enforce=False,
                                           source=source))
                if kind == "flag" and not hit:
                    failures.append(
                        f"[{rule.id}] should FLAG but did not: "
                        f"{source!r} -> {target!r}")
                elif kind == "pass" and hit:
                    failures.append(
                        f"[{rule.id}] should PASS but was flagged: "
                        f"{source!r} -> {target!r}")
    return failures
