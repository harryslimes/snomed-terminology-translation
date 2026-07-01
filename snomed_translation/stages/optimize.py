"""Optimization stage runner: GEPA over a seed style guide.

Reuses the DSPy harness from `scripts/optimization/dspy_translate.py`
(build_lm, build_translator, evaluate, metric) — the same machinery
`scripts/optimization/run_gepa.py` drives from the CLI. This module drives it
from a PipelineConfig + the flow graph's wired datasets instead:

* ``trainset`` / ``devset`` arrive as resolved dataset dicts (csv path + the
  role->column mapping detected by ``snomed_translation.graph.source_schema``), so any
  dataset that provides (sctid, en, target) works regardless of column names.
* the task LM is the translation candidate the config resolves (same selection
  rule as the translate stage), so the guide is optimised for the model that
  will actually use it;
* the reflection LM comes from the optimization recipe's catalog candidates,
  falling back to the legacy free-form ``reflection_lm`` spec, then to the
  task LM;
* the optimised guide is written under ``paths.output_dir`` (it is a run
  artifact — promote it into ``style_guide/`` deliberately, not implicitly).
"""
from __future__ import annotations

import csv
import logging
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import re

from snomed_translation.config import OptimizationStageSpec, PipelineConfig
from pipelines.context import RunContext, StageResult

log = logging.getLogger(__name__)


def _prompts_dir() -> str:
    """The prompt-template store dir (WIZARD_PROMPTS_DIR, else configs/prompts)."""
    return os.environ.get("WIZARD_PROMPTS_DIR", "configs/prompts")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "-", text.strip().lower()).strip("-_")
    return s or "gepa"


def _load_examples(ds: dict, limit: int | None = None) -> list:
    """Dataset dict (csv + role->column mapping) -> dspy.Examples.

    Mirrors dspy_translate.load_split but reads through the role mapping, so
    any (sctid, en, target) dataset works. A ``ko_all`` column is honoured for
    multi-reference scoring when the dataset happens to carry one.
    """
    import dspy

    roles = ds.get("roles") or {}
    missing = [r for r in ("sctid", "en", "target") if r not in roles]
    if missing:
        raise RuntimeError(
            f"dataset {ds.get('source_id')!r} lacks role column(s) {missing}"
        )
    examples = []
    with Path(ds["dataset"]).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            target = (row.get(roles["target"]) or "").strip()
            ex = dspy.Example(
                sctid=row[roles["sctid"]],
                preferred_term=row[roles["en"]],
                ko_reference=target,
                ko_all=(row.get("ko_all") or target),
                modality=row.get("modality", ""),
                source=row.get("source", ""),
                sme_rating=row.get("sme_rating", ""),
                sme_notes=row.get("sme_notes", ""),
            ).with_inputs("sctid", "preferred_term")
            examples.append(ex)
    if limit:
        examples = examples[:limit]
    return examples


def _task_lm(cfg: PipelineConfig):
    """Build the task LM from the resolved translation candidate."""
    from scripts.optimization.dspy_translate import build_lm

    candidate = cfg.translation.resolve_candidate()
    model = cfg.models[candidate.model_key]
    base_url = os.getenv("VLLM_BASE_URL", cfg.model_base_url(candidate.model_key))
    api_key = "EMPTY"
    if candidate.api_key_env and os.getenv(candidate.api_key_env):
        api_key = os.environ[candidate.api_key_env]
    lp = dict(candidate.llm_params or {})
    kwargs = {k: lp[k] for k in ("temperature", "top_p", "top_k", "max_tokens")
              if k in lp}
    return build_lm(model_id=model.hf_id, base_url=base_url, api_key=api_key,
                    **kwargs), candidate.model_key


def _reflection_lm(cfg: PipelineConfig, opt: OptimizationStageSpec,
                   override_key: str | None, task_lm):
    """Reflection LM: catalog candidates first, legacy spec next, task LM last."""
    import dspy

    if opt.reflection_candidates:
        c = opt.resolve_reflection_candidate(override_key)
        model = cfg.models[c.model_key]
        kwargs = dict(
            api_base=cfg.model_base_url(c.model_key),
            api_key=(os.environ.get(model.api_key_env, "EMPTY")
                     if model.api_key_env else "EMPTY"),
            temperature=c.temperature,
            max_tokens=c.max_tokens,
        )
        if c.disable_thinking:
            kwargs["extra_body"] = {"enable_thinking": False}
        return dspy.LM(f"openai/{model.hf_id}", **kwargs), c.model_key
    rl = opt.reflection_lm
    if rl is not None:
        kwargs = dict(temperature=rl.temperature, max_tokens=rl.max_tokens)
        if rl.base_url:
            kwargs["api_base"] = rl.base_url
        if rl.api_key_env:
            kwargs["api_key"] = os.environ.get(rl.api_key_env, "EMPTY")
        if rl.disable_thinking:
            kwargs["extra_body"] = {"enable_thinking": False}
        mid = rl.model_id if rl.model_id.startswith(("openai/", "anthropic/")) \
            else f"openai/{rl.model_id}"
        return dspy.LM(mid, **kwargs), rl.model_id
    return task_lm, "(task LM)"


def run(cfg: PipelineConfig, ctx: RunContext, *,
        trainset: dict | None = None, devset: dict | None = None,
        train_limit: int | None = None, dev_limit: int | None = None,
        reflection_model_key: str | None = None,
        output_tag: str = "gepa", **_) -> StageResult:
    """Run GEPA; write the optimised style guide; report before/after scores."""
    opt = cfg.optimization
    if opt is None:
        return StageResult(stage="optimize", ok=False,
                           message="config has no optimization recipe")
    if trainset is None:
        return StageResult(stage="optimize", ok=False,
                           message="optimize stage requires a trainset — wire "
                                   "a datasource to the node's trainset port")
    out_dir = ctx.artifacts_dir() or cfg.paths.output_dir
    # Seed GEPA from a store template (preferred) or a bare style-guide file.
    seed_tmpl = None
    if opt.seed_template:
        try:
            from pipelines.prompts import load_template
            seed_tmpl = load_template(_prompts_dir(), opt.seed_template)
        except Exception as exc:
            return StageResult(
                stage="optimize", ok=False,
                message=f"seed_template {opt.seed_template!r} not found in "
                        f"store ({_prompts_dir()}): {exc}")
        seed = out_dir / f"_seed_{output_tag}.md"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text(seed_tmpl.body, encoding="utf-8")
    else:
        seed = opt.seed_style_guide
        if seed is None or not Path(seed).exists():
            return StageResult(stage="optimize", ok=False,
                               message=f"seed style guide not found: {seed}")
    lookup = opt.lookup_cache or cfg.paths.lookup_cache
    if lookup is None or not Path(lookup).exists():
        return StageResult(
            stage="optimize", ok=False,
            message=f"exemplar lookup cache not found: {lookup} — the DSPy "
                    "translator needs the pre-built BGE-M3 cache (see "
                    "optimization.lookup_cache)")

    # dspy imports LiteLLM, which warns about missing botocore (Bedrock/
    # SageMaker preloading) — irrelevant here, so keep the log clean.
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    hard_rules = opt.hard_rules_file
    if hard_rules is not None and not Path(hard_rules).exists():
        return StageResult(stage="optimize", ok=False,
                           message=f"hard_rules_file not found: {hard_rules}")

    try:
        import dspy
        from dspy.teleprompt import GEPA
        from scripts.optimization.dspy_translate import (
            build_translator, evaluate, make_metric,
        )
    except ImportError as exc:
        return StageResult(stage="optimize", ok=False,
                           message=f"dspy not available: {exc}")

    try:
        task_lm, task_key = _task_lm(cfg)
        configure_kwargs: dict = {"lm": task_lm}
        if opt.production_scaffold:
            # Render GEPA's LM calls through production's exact scaffold (Phase 3b).
            from snomed_translation.gepa_scaffold import make_production_adapter
            from snomed_translation.stages.translate import (
                _template_body, script_name)
            pt = cfg.translation.prompt_templates
            configure_kwargs["adapter"] = make_production_adapter(
                _template_body(pt.system_template_id, pt.system),
                _template_body(pt.user_template_id, pt.user),
                language_name=cfg.language.name,
                language_script_name=script_name(cfg.language.code, cfg.language.name))
            log.info("GEPA: production-scaffold adapter active — LM calls render "
                     "the exact translate system/user prompt")
        dspy.settings.configure(**configure_kwargs)
        reflection_lm, reflection_key = _reflection_lm(
            cfg, opt, reflection_model_key, task_lm)

        train = _load_examples(trainset, train_limit)
        dev = _load_examples(devset, dev_limit) if devset else None
        valset = dev if dev is not None else train
        log.info("GEPA: train=%d val=%d task_lm=%s reflection_lm=%s seed=%s "
                 "hints=%s hard_rules=%s",
                 len(train), len(valset), task_key, reflection_key, seed,
                 opt.hints_file, hard_rules)

        # Metric honours the recipe's hints + hard rules (previously the
        # module-level default metric was used, silently ignoring opt.hints_file).
        metric = make_metric(hints=opt.hints_file, hard_rules=hard_rules)
        translator = build_translator(style_guide_path=seed,
                                      lookup_cache_path=lookup,
                                      hard_rules=hard_rules)
        pre = evaluate(translator, valset)

        gepa_kwargs = dict(metric=metric, reflection_lm=reflection_lm,
                           track_stats=opt.gepa.track_stats)
        if opt.gepa.max_metric_calls is not None:
            gepa_kwargs["max_metric_calls"] = opt.gepa.max_metric_calls
        else:
            gepa_kwargs["auto"] = opt.gepa.auto

        t0 = time.monotonic()
        optimized = GEPA(**gepa_kwargs).compile(
            translator, trainset=train, valset=valset)
        elapsed = time.monotonic() - t0

        post = evaluate(optimized, valset)
        evolved = optimized.predictor.signature.instructions
        out_md = out_dir / f"style_guide_{output_tag}.md"
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(evolved, encoding="utf-8")

        # When seeded from a store template, write the evolved body back as a
        # gepa-provenance CHILD version (lineage), guarding required slots (D8).
        child_id = None
        slot_warn = ""
        if seed_tmpl is not None:
            from pipelines.prompts import (
                PromptTemplate as _PT,
                missing_required,
                save_template,
            )
            missing = missing_required(evolved, seed_tmpl.required_var_names())
            if missing:
                slot_warn = (f" [required slots dropped by GEPA {missing}; "
                             "store version NOT written]")
                log.warning("GEPA evolved body dropped required slots %s; "
                            "keeping file output only", missing)
            else:
                child_id = _slug(f"{seed_tmpl.id}__gepa_{output_tag}")
                save_template(_prompts_dir(), _PT(
                    id=child_id,
                    name=f"{seed_tmpl.name or seed_tmpl.id} (GEPA {output_tag})",
                    kind=seed_tmpl.kind, body=evolved, provenance="gepa",
                    parent=seed_tmpl.id, tags=list(seed_tmpl.tags)))
                log.info("wrote GEPA child template %s (parent %s)",
                         child_id, seed_tmpl.id)
    except Exception as exc:
        log.exception("GEPA run failed")
        return StageResult(stage="optimize", ok=False,
                           message=f"GEPA failed: {exc}")

    outputs: dict = {"optimized_style_guide": out_md}
    if child_id:
        outputs["prompt_template"] = child_id      # the gepa-provenance version
    return StageResult(
        stage="optimize", ok=True,
        message=(f"GEPA ({opt.gepa.auto}) in {elapsed:.0f}s: mean_score "
                 f"{pre['mean_score']:.3f} -> {post['mean_score']:.3f} on the "
                 f"{'dev' if dev is not None else 'train'} split"
                 + (f"; -> template {child_id}" if child_id else "") + slot_warn),
        outputs=outputs,
        metrics={
            "pre_mean_score": pre["mean_score"],
            "post_mean_score": post["mean_score"],
            "pre_exact_match_pct": pre["exact_match_pct"],
            "post_exact_match_pct": post["exact_match_pct"],
            "pre_mean_chrf": pre["mean_chrf"],
            "post_mean_chrf": post["mean_chrf"],
            "elapsed_seconds": round(elapsed, 1),
        },
    )
