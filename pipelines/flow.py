"""Flow definitions: a *sequence* of pipeline stages, each with per-step
overrides, that compose a full experiment.

A Flow is a recipe; a *flow execution* is an instance of running that recipe.
The pipeline defines capabilities (sources, candidate models, scorers, GEPA
recipe). The flow chooses *which* of those capabilities to use, in *what
order*, with *what overrides* per step. References like
``$step_id.output_csv`` resolve to a prior step's named output at execute
time, so e.g. ``translate (full corpus)`` can consume the optimised style
guide produced by ``optimize`` earlier in the same flow.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Node graph: a flow is a DAG of typed nodes wired output->input. Datasource
# nodes reference a registered source block; translate/evaluate nodes consume
# upstream outputs. This is the explicit form of what $step.field references
# expressed implicitly.
# ---------------------------------------------------------------------------

NodeType = Literal["datasource", "style_guide", "translate", "evaluate",
                   "optimize", "translate_consistency", "evaluate_consistency",
                   "evaluate_formula", "score_workflow_llm"]

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
# node reads an evaluate node's `metrics` output, never its scored `rows`. The
# editor + the drawflow converters use this to route the connection to (and gate
# it on) the right output dot; the runtime reads the metric vector regardless.
INPUT_REQUIRES_OUTPUT: dict[str, dict[str, str]] = {
    "evaluate_formula": {"metrics": "metrics"},
    "score_workflow_llm": {"metrics": "metrics"},
}

# Node types that aggregate an upstream metric vector into one scalar (the flow's
# comparable "score"). Editor + ledger treat these as a family.
SCORE_NODE_TYPES: set[str] = {"evaluate_formula", "score_workflow_llm"}


def output_index(source_type: str, target_type: str, target_port: str) -> int:
    """1-based index of the source's output port that a given input port
    consumes (defaults to the primary output)."""
    outs = NODE_OUTPUTS.get(source_type) or ["out"]
    req = INPUT_REQUIRES_OUTPUT.get(target_type, {}).get(target_port)
    return outs.index(req) + 1 if (req and req in outs) else 1

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
    # reduces that metric vector to one scalar. The input is the JSON of metric
    # keys→values the upstream emitted (see INPUT_REQUIRES_OUTPUT).
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
# by hand with the stage runners (pipelines/stages/evaluate*.py). Score nodes
# emit a single, user-named metric (``output_name``), so they're not listed
# statically — the editor reads their configured name instead.
NODE_METRICS: dict[str, list[str]] = {
    "evaluate": ["composite_score", "mean_chrf", "exact_match_pct", "n"],
    "evaluate_consistency": [
        "composite_score", "mean_chrf", "exact_match_pct", "n", "n_judged",
        "n_multi_candidate", "judge_oracle_accuracy", "majority_oracle_accuracy",
    ],
}


class NodePos(BaseModel):
    """Canvas coordinates for the visual editor (ignored by execution)."""
    x: float = 0
    y: float = 0


class FlowNode(BaseModel):
    """One node in a flow graph.

    ``inputs`` wires this node's input ports to upstream nodes: a mapping of
    input-port name -> upstream node id. The upstream node's (single) output
    feeds the port. ``params`` holds node-type config: a datasource names a
    registered ``source``; a translate node names ``model_key`` /
    ``style_guide_path`` / optional ``output_tag`` / ``limit``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_-]*$",
        description="Stable identifier; referenced by downstream nodes' inputs.",
    )
    type: NodeType
    pos: NodePos = Field(default_factory=NodePos)
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="input_port -> upstream_node_id.",
    )


class FlowSpec(BaseModel):
    """A saved flow recipe.

    Pipelines + eval-sets + flows are three independent libraries the wizard
    composes at run time. The flow file is the most expressive of the three:
    it captures the whole experiment as a single self-contained artifact.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., pattern=r"^[a-zA-Z0-9_-]+$",
        description="Stable identifier; the filename stem and URL segment. "
                    "Never changes once assigned, so renaming the flow (its "
                    "display `name`) doesn't break links, history, or runs.",
    )
    name: str = Field(
        ..., min_length=1,
        description="Human-facing display label. Freely editable; unlike `id` "
                    "it is not used in paths, so it may contain spaces.",
    )
    description: str = ""
    project: str = Field(
        default="project",
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Project block name (configs/<project>.json stem) supplying "
                    "the environment: language, paths, Qdrant, overlap defaults, "
                    "and the rarely-varying stage recipes.",
    )
    resources: list[str] | None = Field(
        default=None,
        description="Resource ids to enable from the manifest. None = all.",
    )
    nodes: list[FlowNode] = Field(
        default_factory=list,
        description="The flow graph: typed nodes wired output->input.",
    )

    @model_validator(mode="after")
    def _validate_graph(self) -> "FlowSpec":
        by_id: dict[str, FlowNode] = {}
        for n in self.nodes:
            if n.id in by_id:
                raise ValueError(f"duplicate node id {n.id!r}")
            by_id[n.id] = n
        for n in self.nodes:
            allowed_ports = NODE_INPUTS[n.type]
            for port, src_id in n.inputs.items():
                if port not in allowed_ports:
                    raise ValueError(
                        f"node {n.id!r} ({n.type}) has no input port {port!r}; "
                        f"valid: {sorted(allowed_ports)}"
                    )
                if src_id not in by_id:
                    raise ValueError(
                        f"node {n.id!r} input {port!r} references unknown node "
                        f"{src_id!r}"
                    )
                src_type = by_id[src_id].type
                if src_type not in allowed_ports[port]:
                    raise ValueError(
                        f"node {n.id!r} input {port!r} accepts "
                        f"{sorted(allowed_ports[port])} outputs, but {src_id!r} "
                        f"is a {src_type} node"
                    )
        self._assert_acyclic(by_id)
        return self

    def _assert_acyclic(self, by_id: dict[str, FlowNode]) -> None:
        # DFS colouring: white=0 unseen, grey=1 on stack, black=2 done.
        colour: dict[str, int] = {}

        def visit(nid: str) -> None:
            colour[nid] = 1
            for src_id in by_id[nid].inputs.values():
                c = colour.get(src_id, 0)
                if c == 1:
                    raise ValueError(f"flow graph has a cycle involving {nid!r}")
                if c == 0:
                    visit(src_id)
            colour[nid] = 2

        for nid in by_id:
            if colour.get(nid, 0) == 0:
                visit(nid)

    @classmethod
    def from_file(cls, path: Path | str) -> "FlowSpec":
        path = Path(path)
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
        # Legacy flows (pre-`id`) used `name` as the filename stem and URL.
        # Adopt the stem as the stable id so old URLs keep resolving, and seed
        # the display name from the id when it too is absent.
        if isinstance(data, dict):
            data.setdefault("id", path.stem)
            data.setdefault("name", data["id"])
        return cls.model_validate(data)

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_none=True)
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                            encoding="utf-8")
        else:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
