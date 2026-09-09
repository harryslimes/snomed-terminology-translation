"""Smoke tests for snomed_translation.hard_rules — runnable with pytest or `python`.

Deliberately free of dspy/LiteLLM so the hard-rules logic can be checked
without the model stack (mirrors why snomed_translation.scoring was extracted).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from snomed_translation.hard_rules import (  # noqa: E402
    find_violations,
    frozen_block,
    load_hard_rules,
    penalty_for,
)

RULES = {
    "language": "ko",
    "rules": [
        {"id": "no-trailing-punctuation", "forbidden_regex": [r"[.,;:]\s*$"],
         "enforce": True, "freeze": True, "penalty": 0.25,
         "description": "no terminal punctuation"},
        {"id": "no-sino-arm", "forbidden": ["상지"], "canonical": ["팔"],
         "enforce": True, "freeze": True, "penalty": 0.5,
         "description": "prefer native arm"},
        {"id": "frozen-only", "forbidden": ["xyz"], "enforce": False,
         "freeze": True, "description": "documented but not scored"},
    ],
}


def test_enforce_flag_gates_scoring():
    rules = load_hard_rules(RULES)
    enforced = [r for r in rules if r.enforce]
    # The freeze-only rule must not contribute to violations even if matched.
    v = find_violations("contains xyz token", enforced)
    assert v == [], "freeze-only rule should never be a violation"


def test_forbidden_substring_and_regex():
    enforced = [r for r in load_hard_rules(RULES) if r.enforce]
    v = find_violations("팔 절제술.", enforced)
    ids = {r.id for r, _ in v}
    assert "no-trailing-punctuation" in ids
    v2 = find_violations("상지 절제술", enforced)
    ids2 = {r.id for r, _ in v2}
    assert "no-sino-arm" in ids2
    assert "no-trailing-punctuation" not in ids2


def test_penalty_sums_per_rule_once():
    enforced = [r for r in load_hard_rules(RULES) if r.enforce]
    # Violates both punctuation (0.25) and sino-arm (0.5).
    v = find_violations("상지 절제.", enforced)
    assert abs(penalty_for(v) - 0.75) < 1e-9


def test_frozen_block_excludes_non_frozen_and_includes_frozen():
    rules = load_hard_rules(RULES)
    block = frozen_block(rules)
    assert "NON-NEGOTIABLE" in block
    assert "no terminal punctuation" in block
    assert "prefer native arm" in block
    # canonical/forbidden surfaced in composed text
    assert "Use: 팔" in block
    assert "Never use: 상지" in block


def test_none_is_backward_compatible():
    assert load_hard_rules(None) == []
    assert frozen_block([]) == ""
    assert find_violations("anything", []) == []


def test_seed_yaml_loads_and_is_safe_by_default():
    path = ROOT / "configs" / "hard_rules" / "ko.yaml"
    rules = load_hard_rules(path)
    by_id = {r.id: r for r in rules}
    # The illustrative native-body-site rule ships DISABLED (known-risky), and
    # `enabled: false` means dropped at load — not merely unenforced. It must
    # not reach ANY consumer: the validator deliberately checks enforce:false
    # rules, so relying on `enforce` alone would have turned this parked rule
    # into live warnings for 하지/상지.
    assert "example-native-body-site" not in by_id
    # Output-hygiene invariants ship enabled + frozen.
    assert by_id["no-trailing-punctuation"].enforce is True
    block = frozen_block(rules)
    # Disabled example must not leak into the prompt block.
    assert "상지" not in block


def test_severity_and_enforce_are_independent():
    """An enforce:false rule still gates output; it just doesn't steer GEPA."""
    rules = load_hard_rules({"rules": [
        {"id": "output-only", "forbidden": ["위팔"],
         "enforce": False, "freeze": False, "severity": "blocker"},
    ]})
    assert rules and rules[0].severity == "blocker"
    # The optimiser's view: no penalty, so GEPA is not steered by this rule.
    assert find_violations("위팔 동맥 색전술", rules) == []
    # The validator's view: the violation is still caught.
    caught = find_violations("위팔 동맥 색전술", rules, require_enforce=False)
    assert [r.id for r, _ in caught] == ["output-only"]


def test_disabled_rules_are_dropped_for_every_consumer():
    rules = load_hard_rules({"rules": [
        {"id": "parked", "forbidden": ["하지"], "enabled": False,
         "severity": "blocker"},
        {"id": "live", "forbidden": ["위팔"], "severity": "blocker"},
    ]})
    assert [r.id for r in rules] == ["live"]
    assert find_violations("왼쪽 하지 촬영", rules, require_enforce=False) == []


def test_shipped_rule_examples_all_hold():
    """Every worked example in the live ko.yaml behaves as documented.

    This is the guard that was missing when upper-limb-not-upper-arm shipped as
    a bare `위팔` ban: it flagged 64 production rows of which 40 were correct,
    and the count was quoted as a finding before anyone checked the flagged
    rows against their source terms.
    """
    from snomed_translation.hard_rules import check_rule_examples

    rules = load_hard_rules(ROOT / "configs" / "hard_rules" / "ko.yaml")
    assert check_rule_examples(rules) == []


def test_source_conditional_rule_only_fires_for_matching_sources():
    rules = load_hard_rules({"rules": [
        {"id": "upper-limb", "when_source": r"upper (limb|extremit)",
         "forbidden_regex": [r"위팔(?!뼈|두갈래)"], "severity": "blocker"},
    ]})
    fire = lambda tgt, src: [r.id for r, _ in find_violations(
        tgt, rules, require_enforce=False, source=src)]

    # Wrong: 위팔 is the upper arm specifically, too narrow for "upper limb".
    assert fire("투시 유도하 위팔 배액", "Drainage of upper limb") == ["upper-limb"]
    # Right, and the reason a bare substring ban was unusable: each of these
    # contains 위팔 legitimately.
    assert fire("위팔 컴퓨터 단층 촬영", "CT of upper arm") == []
    assert fire("왼쪽 위팔뼈 단순 촬영", "Plain X-ray of left humerus") == []
    assert fire("왼쪽 위팔 동맥 혈관 조영", "Angiography of left brachial artery") == []
    # Inert without a source rather than firing blindly — the GEPA metric
    # scores bare candidates and must not be handed unevaluable violations.
    assert fire("투시 유도하 위팔 배액", "") == []


if __name__ == "__main__":
    # Kept last on purpose: it collects test_* from globals(), so any test
    # defined below this block would be silently skipped in script mode.
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
