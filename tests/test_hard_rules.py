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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
