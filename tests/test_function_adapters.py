"""Headless tests for the translation plugin's function adapters.

Only the metric-only path (``evaluate_formula``) and source resolution run
without the GPU/LLM stack, so those are exercised end-to-end through the app's
generic engine. The heavier translate/evaluate/optimize adapters are covered by
spec-validation + compile-path unit checks here; their full execution is B7
(needs VLLM/Qdrant).
"""
from __future__ import annotations

import csv

import pytest

from pipelines import examples, registry
from pipelines.context import RunContext
from pipelines.flow import FlowNode, FlowSpec
from pipelines.run_flow import run_flow

import snomed_translation.functions as F
from snomed_translation.assemble import Registries
from snomed_translation.config import DataSourceSpec


@pytest.fixture(autouse=True)
def _plugins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    examples.install()          # demo make_rows / count_rows
    F.install()                 # translation functions + source resolver
    yield
    for name in ("make_rows", "count_rows"):
        registry.unregister(name)
    for s in F.specs():
        registry.unregister(s.name)
    registry.unregister_source("snomed_translation")


def _ctx(tmp_path, name):
    return RunContext(run_id=name, log_dir=tmp_path / name)


def test_all_specs_are_valid_and_runners_load():
    names = {s.name for s in F.specs()}
    assert names == {
        "translate", "translate_consistency", "evaluate",
        "evaluate_consistency", "optimize", "evaluate_formula",
        "score_workflow_llm", "style_guide", "build_snomed_index",
    }
    for s in F.specs():
        assert callable(s.load_runner())


def test_evaluate_formula_reduces_upstream_metrics(tmp_path):
    """count_rows emits a `score` metric; evaluate_formula reduces it via a
    formula — exercising the metrics wire (`up:metrics`) and the adapter."""
    flow = FlowSpec.model_validate({
        "id": "score", "name": "score", "nodes": [
            {"id": "rows", "type": "function",
             "params": {"function": "make_rows", "items": "a,b,c,d"}},
            {"id": "cnt", "type": "function",
             "params": {"function": "count_rows"},
             "inputs": {"dataset": "rows"}},
            {"id": "f", "type": "function",
             "params": {"function": "evaluate_formula",
                        "expression": "score * 2 + 1",
                        "output_name": "doubled"},
             "inputs": {"metrics": "cnt:metrics"}},
        ],
    })
    ok, journal = run_flow(flow, _ctx(tmp_path, "r"), stop_on_error=True)
    assert ok, journal
    f = next(e for e in journal if e["step_id"] == "f")
    assert f["metrics"]["doubled"] == 9.0  # count=4 -> 4*2+1


def test_evaluate_formula_fails_without_metrics(tmp_path):
    flow = FlowSpec.model_validate({
        "id": "bad", "name": "bad", "nodes": [
            {"id": "rows", "type": "function",
             "params": {"function": "make_rows", "items": "a,b"}},
            # wire the *dataset* (primary), not the metrics vector
            {"id": "f", "type": "function",
             "params": {"function": "evaluate_formula",
                        "expression": "score", "output_name": "s"},
             "inputs": {"metrics": "rows"}},
        ],
    })
    ok, journal = run_flow(flow, _ctx(tmp_path, "r"), stop_on_error=True)
    assert not ok
    f = next(e for e in journal if e["step_id"] == "f")
    assert not f["ok"] and "metric" in f["message"].lower()


def _make_source(tmp_path):
    """A built csv source + a Registries holding it, wired onto ctx.extras."""
    csv_path = tmp_path / "terms.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sctid", "preferred_term", "ko_reference"])
        w.writerow(["123", "heart", "심장"])
    spec = DataSourceSpec.model_validate({
        "id": "my_terms", "kind": "csv", "enabled": True,
        "output_csv": str(csv_path), "csv_path": str(csv_path),
        "csv_columns": {"sctid": "sctid", "en": "preferred_term",
                        "target": "ko_reference"},
    })
    return Registries(sources={"my_terms": spec})


def test_source_resolver_resolves_a_built_source(tmp_path):
    ctx = _ctx(tmp_path, "r")
    ctx.extras["registries"] = _make_source(tmp_path)
    node = FlowNode(id="ds", type="datasource", params={"source": "my_terms"})
    out = F.resolve_source(node, ctx)
    assert out is not None
    assert out["source_id"] == "my_terms"
    assert "sctid" in out["present"] and "target" in out["present"]
    assert out["_primary"] == out["dataset"]


def test_source_resolver_defers_when_no_source(tmp_path):
    node = FlowNode(id="ds", type="datasource",
                    params={"data_object": "promoted_thing"})
    assert F.resolve_source(node, _ctx(tmp_path, "r")) is None


def test_datasource_recovery_round_trips_a_path(tmp_path):
    """A datasource's wire value (a CSV path) is recovered to its full dict."""
    ctx = _ctx(tmp_path, "r")
    ctx.extras["registries"] = _make_source(tmp_path)
    path = str(tmp_path / "terms.csv")
    rec = F._datasource_dict(path, ctx)
    assert rec["source_id"] == "my_terms"
    assert rec["dataset"] == path
