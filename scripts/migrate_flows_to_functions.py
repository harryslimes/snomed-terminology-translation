"""Migrate legacy flow JSON to the generic function/promote node model.

The semi-automated-research app replaced the hard-coded node *types*
(translate/evaluate/optimize/...) with a single ``function`` node kind whose
behaviour comes from a registered plugin function, and replaced the per-node
``publish_as`` param with an explicit ``promote`` node wired to the output.

This script rewrites the old ``configs/flows/*.json`` accordingly:

* a node whose ``type`` is a former stage (``translate``, ``evaluate``,
  ``optimize``, ``translate_consistency``, ``evaluate_consistency``,
  ``evaluate_formula``, ``score_workflow_llm``) becomes
  ``{"type": "function", "params": {"function": <old type>, ...}}``;
* a ``style_guide`` node becomes a ``style_guide`` function (the translation
  plugin provides a trivial runner that emits the guide path);
* a ``datasource`` node is left unchanged (the plugin resolves its ``source``);
* any ``params.publish_as: NAME`` is removed and a new ``promote`` node named
  NAME is added, wired ``value`` ← the promoting node's primary output.

Usage:
    python scripts/migrate_flows_to_functions.py configs/flows/*.json        # dry run
    python scripts/migrate_flows_to_functions.py --write configs/flows/*.json
    python scripts/migrate_flows_to_functions.py --out-dir configs/flows_v2 configs/flows/*.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

# Legacy executable stage types -> the function name they become.
STAGE_TYPES = {
    "translate", "evaluate", "optimize", "translate_consistency",
    "evaluate_consistency", "evaluate_formula", "score_workflow_llm",
}
# Input node that becomes a (plugin-provided) function rather than staying a
# bespoke node kind.
INPUT_FUNCTION_TYPES = {"style_guide"}

# Score nodes read a *specific* output port of their upstream evaluate node (its
# `metrics` vector, not the scored `rows`). The old editor routed this
# implicitly via INPUT_REQUIRES_OUTPUT; the generic engine needs it spelled out
# on the wire as ``upstream_id:metrics``. Map: function -> {input_port -> port}.
INPUT_REQUIRES_OUTPUT = {
    "evaluate_formula": {"metrics": "metrics"},
    "score_workflow_llm": {"metrics": "metrics"},
}


def migrate_flow(flow: dict) -> dict:
    flow = copy.deepcopy(flow)
    nodes = flow.get("nodes", [])
    promotes: list[dict] = []

    for node in nodes:
        ntype = node.get("type")
        params = node.setdefault("params", {})

        if ntype in STAGE_TYPES or ntype in INPUT_FUNCTION_TYPES:
            node["type"] = "function"
            params["function"] = ntype

        # Spell out the specific upstream output port a score node consumes, so
        # the generic engine wires the metric vector (not the primary output).
        port_map = INPUT_REQUIRES_OUTPUT.get(ntype, {})
        for in_port, out_port in port_map.items():
            ref = node.get("inputs", {}).get(in_port)
            if isinstance(ref, str) and ":" not in ref:
                node["inputs"][in_port] = f"{ref}:{out_port}"

        publish_as = params.pop("publish_as", None)
        if publish_as:
            pos = node.get("pos", {}) or {}
            promotes.append({
                "id": f"{node['id']}__promote",
                "type": "promote",
                "pos": {"x": float(pos.get("x", 0)) + 220.0,
                        "y": float(pos.get("y", 0)) + 140.0},
                "params": {"name": publish_as},
                "inputs": {"value": node["id"]},
            })

    nodes.extend(promotes)
    return flow


def _changed_summary(before: dict, after: dict) -> str:
    b = {n["id"]: n["type"] for n in before.get("nodes", [])}
    a = {n["id"]: n["type"] for n in after.get("nodes", [])}
    retyped = sum(1 for k in b if b[k] != a.get(k))
    added = len(a) - len(b)
    return f"{retyped} node(s) retyped, {added} promote node(s) added"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", type=Path, help="Flow JSON files.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="Rewrite files in place.")
    g.add_argument("--out-dir", type=Path, help="Write migrated copies here.")
    args = p.parse_args(argv)

    for path in args.files:
        flow = json.loads(path.read_text(encoding="utf-8"))
        migrated = migrate_flow(flow)
        print(f"{path}: {_changed_summary(flow, migrated)}")
        text = json.dumps(migrated, indent=2, ensure_ascii=False)
        if args.write:
            path.write_text(text, encoding="utf-8")
        elif args.out_dir:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            (args.out_dir / path.name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
