"""Domain schema tables for the SNOMED-translation node functions.

These describe each translation node's ports, the dataset *roles* its ports
require/provide, and the metric vectors its evaluate-family nodes emit. They
used to live in the monolith's ``pipelines/flow.py`` alongside the generic flow
model; with the split, the generic :class:`~pipelines.flow.FlowNode` /
:class:`~pipelines.flow.FlowSpec` come from the app and these *domain* tables
move here, owned by the plugin.

They remain the single source of truth for two consumers:

* :mod:`snomed_translation.graph` — ``build_*`` compilers read ``PORT_REQUIRES``
  / ``ROLE_LABELS`` to fail fast on an under-specified dataset;
* :mod:`snomed_translation.functions` — derives each :class:`FunctionSpec`'s
  input/output :class:`PortSpec`s and param metric choices from them.
"""
from __future__ import annotations

# The former hard-coded node types, kept as the canonical set of function names
# the plugin registers (a migrated flow's ``params.function`` is one of these).
STAGE_NODE_TYPES: tuple[str, ...] = (
    "translate", "evaluate", "optimize", "translate_consistency",
    "evaluate_consistency", "evaluate_formula", "score_workflow_llm",
)

# Each node type's ordered output ports. Most nodes emit one thing; an evaluate
# node emits two distinct things from its exit — the per-row scored dataset
# (`rows`) and the aggregate metric vector (`metrics`) — so a downstream node
# wires to exactly the one it needs. The FIRST port is the node's *primary*
# output (used when a consumer doesn't require a specific one).
NODE_OUTPUTS: dict[str, list[str]] = {
    "datasource": ["dataset"],
    "style_guide": ["style_guide"],
    "translate": ["translations"],
    # rows = the scored per-concept CSV; metrics = the aggregate vector.
    "evaluate": ["rows", "metrics"],
    "optimize": ["optimized_style_guide"],
    # Self-consistency variant: translate N times → a *candidates* dataset
    # (multiple distinct results per concept). The downstream judge/scorer is
    # evaluate_consistency — the candidate shape is deliberately different from
    # a plain translate output, so it can't feed a plain evaluate node.
    "translate_consistency": ["candidates"],
    "evaluate_consistency": ["rows", "metrics"],
    # Flow-level scoring nodes collapse an upstream evaluate *metric vector* into
    # a single comparable scalar. Their output is that scalar (a metric).
    "evaluate_formula": ["score"],
    "score_workflow_llm": ["score"],
}

# Back-compat single-output accessor: a node's *primary* (first) output port.
NODE_OUTPUT: dict[str, str] = {t: outs[0] for t, outs in NODE_OUTPUTS.items()}

# An input port that must connect to a *specific* named output of its upstream,
# rather than the upstream's primary output. This keeps the wire honest: a score
# node reads an evaluate node's `metrics` output, never its scored `rows`.
INPUT_REQUIRES_OUTPUT: dict[str, dict[str, str]] = {
    "evaluate_formula": {"metrics": "metrics"},
    "score_workflow_llm": {"metrics": "metrics"},
}

# Node types that aggregate an upstream metric vector into one scalar (the flow's
# comparable "score"). Editor + ledger treat these as a family.
SCORE_NODE_TYPES: set[str] = {"evaluate_formula", "score_workflow_llm"}

# Per node type: input-port name -> the upstream node types allowed to feed it.
# Port order matters: Drawflow numbers ports input_1, input_2… in this order,
# so append new ports at the end to keep saved graphs stable.
NODE_INPUTS: dict[str, dict[str, set[str]]] = {
    "datasource": {},
    "style_guide": {},
    "translate": {"terms": {"datasource"}, "exemplars": {"datasource"},
                  "style_guide": {"style_guide", "optimize"}},
    "evaluate": {"translations": {"translate"}, "reference": {"datasource"}},
    "optimize": {"trainset": {"datasource"}, "devset": {"datasource"},
                 "seed_style_guide": {"style_guide"}},
    # Same wiring as translate — it *is* a translate, just run N times.
    "translate_consistency": {"terms": {"datasource"},
                              "exemplars": {"datasource"},
                              "style_guide": {"style_guide", "optimize"}},
    # Consumes a candidates dataset (only translate_consistency produces one)
    # plus the gold reference to score the chosen translation against.
    "evaluate_consistency": {"candidates": {"translate_consistency"},
                             "reference": {"datasource"}},
    # A score node takes the `metrics` output of one evaluate / judge node and
    # reduces that metric vector to one scalar.
    "evaluate_formula": {"metrics": {"evaluate", "evaluate_consistency"}},
    "score_workflow_llm": {"metrics": {"evaluate", "evaluate_consistency"}},
}

# Input ports that may be left unwired. The node then falls back to the
# project recipe: optimize.devset -> GEPA validates on the trainset;
# optimize.seed_style_guide -> the recipe's optimization.seed_style_guide.
# translate.style_guide is REQUIRED (a translate without a guide can't run).
OPTIONAL_PORTS: dict[str, set[str]] = {
    "optimize": {"devset", "seed_style_guide"},
}

# Semantic column roles a dataset can provide. Sources map these roles to
# physical CSV columns; downstream ports require a subset of them. Roles (not
# literal column names) are the compatibility currency so differently-named
# CSVs interoperate.
ROLE_LABELS: dict[str, str] = {
    "sctid": "concept id",
    "en": "English term",
    "target": "translation",
    "candidates": "candidate translations",
}

# Per node type: which input ports require which roles of the dataset that
# feeds them. A port absent here carries no column requirement. Used by the
# editor to gate connections and by the graph compiler to fail fast on an
# under-specified dataset.
PORT_REQUIRES: dict[str, dict[str, list[str]]] = {
    "translate": {"terms": ["sctid", "en"], "exemplars": ["en", "target"]},
    "evaluate": {"translations": ["sctid", "target"],
                 "reference": ["sctid", "target"]},
    # GEPA's metric scores candidates against gold translations, so both
    # splits need the target column — not just the English term.
    "optimize": {"trainset": ["sctid", "en", "target"],
                 "devset": ["sctid", "en", "target"]},
    # Same term/exemplar requirements as translate.
    "translate_consistency": {"terms": ["sctid", "en"],
                              "exemplars": ["en", "target"]},
    # The candidates port needs the multi-candidate column; reference is the
    # gold the chosen translation is scored against.
    "evaluate_consistency": {"candidates": ["sctid", "candidates"],
                             "reference": ["sctid", "target"]},
}

# Dataset roles each *executable* node's output provides. (Datasource outputs
# are dynamic — detected from the source CSV; see graph.source_schema.) These
# are fixed by the stage runners' output formats: translate writes
# (sctid, preferred_term, ko_reference, translation); evaluate's scored CSV
# keeps sctid + score columns only. Wire compatibility is uniform:
# upstream-provides ⊇ port-requires.
NODE_PROVIDES: dict[str, list[str]] = {
    "translate": ["sctid", "en", "target"],
    "evaluate": ["sctid"],
    # A candidates dataset: the concept id, the source English term, and the
    # multiple distinct translations. Deliberately NOT `target` — there is no
    # single chosen translation yet, so this can only feed evaluate_consistency.
    "translate_consistency": ["sctid", "en", "candidates"],
    "evaluate_consistency": ["sctid"],
}

# Aggregate metric keys each evaluate-family node emits (its StageResult
# ``metrics``). A score node consumes the wired upstream's vector; the editor
# reads this to show which names a formula / prompt can reference. Kept in sync
# by hand with the stage runners (snomed_translation/stages/evaluate*.py).
NODE_METRICS: dict[str, list[str]] = {
    "evaluate": ["composite_score", "mean_chrf", "exact_match_pct", "n"],
    "evaluate_consistency": [
        "composite_score", "mean_chrf", "exact_match_pct", "n", "n_judged",
        "n_multi_candidate", "judge_oracle_accuracy", "majority_oracle_accuracy",
    ],
}


def output_index(source_type: str, target_type: str, target_port: str) -> int:
    """1-based index of the source's output port that a given input port
    consumes (defaults to the primary output)."""
    outs = NODE_OUTPUTS.get(source_type) or ["out"]
    req = INPUT_REQUIRES_OUTPUT.get(target_type, {}).get(target_port)
    return outs.index(req) + 1 if (req and req in outs) else 1
