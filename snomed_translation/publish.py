"""Publish run artifacts to stable, named registry entries.

The run store (``data/wizard_runs/<run_id>/artifacts``) keeps *every* output
immutably; publishing is the explicit act of giving one artifact a stable
name so other flows can consume it:

* a **translate** node's output CSV publishes as a registered *data source*
  (``configs/sources/<name>.json`` pointing at an immutable copy under
  ``data/published/<name>/<run_id>.csv``) — any flow then consumes it through
  an ordinary datasource node, with column checks and exemplar embedding for
  free;
* an **optimize** node's tuned guide publishes into the **style-guide
  library** (``style_guide/<name>.md``) — it then appears in style-guide node
  pickers.

Re-publishing under the same name repoints the registry entry ("latest"
semantics) while older copies remain in ``data/published`` and the run store.
Publishing never overwrites a hand-authored entry: only registry entries that
already carry provenance (i.e. were themselves published) may be replaced.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from snomed_translation.config import CsvSourceColumns, DataSourceSpec, PipelineConfig
from pipelines.context import RunContext
from pipelines.flow import FlowNode

PUBLISH_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
PUBLISHED_DATA_DIR = Path("data/published")


class PublishError(Exception):
    """Raised when an artifact can't be published under the requested name."""


def validate_publish_name(name: str) -> None:
    if not PUBLISH_NAME_RE.match(name):
        raise PublishError(
            f"invalid publish name {name!r} (letters / digits / _ / - only)")


def _provenance(flow_name: str, node: FlowNode, ctx: RunContext,
                retroactive: bool = False) -> dict:
    """What produced this artifact — enough to reproduce or audit it.

    ``run_dir`` points at the run's directory, which holds the full
    reproduction context: ``assembled_config.json``, ``flow.json`` (the flow
    as it was when it ran), ``journal.json``, and the log.
    """
    prov = {
        "flow": flow_name,
        "node": node.id,
        "stage": node.type,
        "run_id": ctx.run_id,
        "run_dir": str(ctx.log_dir) if ctx.log_dir else None,
        "published_at": datetime.now().isoformat(timespec="seconds"),
        "params": dict(node.params),
        "inputs": dict(node.inputs),
    }
    if retroactive:
        prov["retroactive"] = True
    return prov


def publish_dataset(name: str, csv_path: Path, flow_name: str, node: FlowNode,
                    ctx: RunContext, cfg: PipelineConfig | None = None,
                    sources_dir: str | Path = "configs/sources",
                    published_dir: str | Path = PUBLISHED_DATA_DIR,
                    retroactive: bool = False) -> dict:
    """Register a translate output as a data source named ``name``."""
    validate_publish_name(name)
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise PublishError(f"artifact not found: {csv_path}")

    spec_path = Path(sources_dir) / f"{name}.json"
    if spec_path.exists():
        existing = DataSourceSpec.from_file(spec_path)
        if not existing.provenance:
            raise PublishError(
                f"source {name!r} already exists and was not published by a "
                "run — refusing to overwrite a hand-authored source; pick a "
                "different publish name")

    dest = Path(published_dir) / name / f"{ctx.run_id}{csv_path.suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(csv_path, dest)

    prov = _provenance(flow_name, node, ctx, retroactive=retroactive)
    if cfg is not None:
        prov["style_guide"] = (str(cfg.translation.style_guide_path)
                               if cfg.translation.style_guide_path else None)
        prov["model_key"] = cfg.translation.default_model_key
    spec = DataSourceSpec(
        id=name, kind="csv", enabled=True, output_csv=dest,
        # The translate stage's fixed output schema (see
        # graph.TRANSLATE_OUTPUT_ROLES).
        csv_columns=CsvSourceColumns(sctid="sctid", en="preferred_term",
                                     target="translation"),
        provenance=prov,
    )
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec.save(spec_path)
    return {"source_id": name, "spec": str(spec_path), "dataset": str(dest)}


def _lineage_parent_name(seed: Path | str | None,
                         style_guides_dir: Path) -> str | None:
    """Library name of the seed guide an optimise step started from.

    Lineage links guides *within* the library by name, so a seed that lives
    under ``style_guides_dir`` becomes its stem (the diff/lineage views can
    then resolve it). A seed pointing elsewhere has no in-library parent.
    """
    if not seed:
        return None
    seed = Path(seed)
    try:
        rel = seed.resolve().relative_to(style_guides_dir.resolve())
    except (ValueError, OSError):
        return None
    return str(rel).removesuffix(".md")


def publish_style_guide(name: str, md_path: Path, flow_name: str,
                        node: FlowNode, ctx: RunContext,
                        style_guides_dir: str | Path = "style_guide",
                        seed_style_guide: Path | str | None = None,
                        optimizer: str = "GEPA",
                        retroactive: bool = False) -> dict:
    """Promote an optimize output into the style-guide library as ``name``.

    Records a ``<name>.lineage.json`` sidecar linking the published guide back
    to its seed (``seed_style_guide``) so the library can show the optimisation
    history and a diff between the seed and its tuned child.
    """
    validate_publish_name(name)
    md_path = Path(md_path)
    if not md_path.exists():
        raise PublishError(f"artifact not found: {md_path}")

    style_guides_dir = Path(style_guides_dir)
    dest = style_guides_dir / f"{name}.md"
    sidecar = dest.with_suffix(".provenance.json")
    if dest.exists() and not sidecar.exists():
        raise PublishError(
            f"style guide {dest} already exists and was not published by a "
            "run — refusing to overwrite a hand-authored guide; pick a "
            "different publish name")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(md_path, dest)
    prov = _provenance(flow_name, node, ctx, retroactive=retroactive)
    sidecar.write_text(json.dumps(prov, indent=2, ensure_ascii=False),
                       encoding="utf-8")

    parent = _lineage_parent_name(seed_style_guide, style_guides_dir)
    lineage = {
        "parent": parent,
        "optimizer": optimizer,
        "created_at": prov["published_at"],
        "note": f"published by {flow_name}/{node.id} (run {ctx.run_id})",
    }
    lineage_path = dest.with_suffix(".lineage.json")
    lineage_path.write_text(json.dumps(lineage, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return {"style_guide": str(dest), "provenance": str(sidecar),
            "lineage": str(lineage_path), "parent": parent}
