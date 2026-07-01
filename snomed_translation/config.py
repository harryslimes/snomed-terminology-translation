"""PipelineConfig — the single source of truth for a SNOMED translation run.

Loadable from JSON or YAML; emits either. The wizard produces an instance of
this model; the staged runners (snomed_translation.stages.*) consume it.

Design rules:
  * Defaults match today's Korean pipeline behaviour so existing scripts keep
    working when wrapped.
  * Everything that varies between languages (column names, regex, native-vs-
    Sino word lists, Qdrant collection name, style guide path, ...) is
    surfaced as a field. No language string is hard-coded in the schema.
  * Two existing config files keep working AS-IS:
      - configs/models.json   →  embedded into PipelineConfig.models / .jobs
      - configs/resources_ko.yaml  →  PipelineConfig.resources is a direct
        Pydantic port of its schema (kinds, scope ECL, overlap policy).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Language + paths
# ---------------------------------------------------------------------------


class LanguageSpec(BaseModel):
    """Identifies the target language for a translation run."""

    code: str = Field(..., description="ISO 639-1 or 639-2 (e.g. 'ko', 'et', 'es').")
    name: str = Field(..., description="Human-readable name (e.g. 'Korean').")
    direction: str = Field(
        ..., description="Direction string used by the exemplar Qdrant filter, e.g. 'EN->KO'."
    )
    tokenizer_lang: str = Field(
        default="en",
        description="YAKE keyword-extractor language code used on English source terms.",
    )


class PathsSpec(BaseModel):
    """Filesystem paths shared across stages. All relative to repo root."""

    root: Path = Field(default=Path("."), description="Repo root.")
    data_dir: Path = Path("data")
    output_dir: Path = Path("data/evals/korean")
    lookup_cache: Path = Path("data/evals/korean/lookup_cache.json")


# ---------------------------------------------------------------------------
# Data sources — pluggable producers of (sctid, en_term, target_translation)
# ---------------------------------------------------------------------------


DataSourceKind = Literal[
    "snomed_national_extension",
    "csv",
    "athena_vocabulary",
    "loinc_linguistic_variant",
]


class SnomedFilterSpec(BaseModel):
    """Filter applied when ingesting from a SNOMED national extension.

    Supports a small set of presets (hierarchy / method / body site) AND a
    raw ECL override. When `ecl` is non-empty it takes precedence over the
    preset fields.
    """

    hierarchy_root: str | None = Field(
        default=None,
        description="SCTID of the top-level hierarchy to include "
                    "(e.g. 71388002 = Procedure, 404684003 = Clinical finding).",
    )
    method_axis_id: str | None = Field(
        default=None,
        description="SCTID of a method attribute value to require "
                    "(e.g. 363679005 = Imaging - action for radiology only).",
    )
    body_site_id: str | None = Field(
        default=None,
        description="SCTID of a body-site attribute value to require.",
    )
    ecl: str = Field(
        default="",
        description="Raw ECL expression. When set, overrides the preset "
                    "fields above. Example: '<<71388002 AND :260686004=<<363679005'.",
    )


class CsvSourceColumns(BaseModel):
    sctid: str = "sctid"
    en: str = "en_term"
    target: str = "target_term"


class DataSourceSpec(BaseModel):
    """One source of bilingual data. Multiple sources can be combined.

    The fields used depend on `kind`; unused fields are ignored. See the
    kind-specific docs below.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Stable identifier referenced by eval_set.source.")
    kind: DataSourceKind
    enabled: bool = True
    output_csv: Path = Field(
        ..., description="Where this source's normalised output is written."
    )

    # snomed_national_extension fields
    rf2_root: Path | None = None
    description_file: Path | None = None
    language_refset_id: str | None = None
    international_release_root: Path | None = None
    snomed_filter: SnomedFilterSpec | None = None

    # csv fields
    csv_path: Path | None = None
    csv_columns: CsvSourceColumns | None = None

    # athena_vocabulary fields
    athena_root: Path | None = None
    athena_vocabulary: str | None = Field(
        default=None,
        description="Vocabulary code, e.g. 'EDI', 'KCD7', 'ICD10'.",
    )
    athena_language_concept_id: str | None = None

    # loinc_linguistic_variant fields
    loinc_root: Path | None = None
    loinc_variant_file: Path | None = None

    # Set when this source was *published* from a pipeline run (flow / node /
    # run_id / node params+inputs). Publishing only ever overwrites sources
    # that carry provenance — hand-authored specs are protected.
    provenance: dict[str, Any] | None = None

    @classmethod
    def from_file(cls, path: Path | str) -> "DataSourceSpec":
        """Load a standalone source-registry file (configs/sources/<id>.json)."""
        path = Path(path)
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
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


class BilingualPoolSpec(BaseModel):
    """Union of selected data sources, used as the RAG exemplar pool."""

    sources: list[str] = Field(
        default_factory=list,
        description="Data source ids to include. Empty = all enabled sources.",
    )
    output_csv: Path = Field(
        default=Path("data/EN-KO/all_bilingual_pairs.csv"),
        description="Pooled output written by the source_ingestion stage.",
    )
    dedup_key: list[str] = Field(
        default_factory=lambda: ["en_lower", "target"],
        description="Field set used to deduplicate across sources.",
    )


class SourcesSpec(BaseModel):
    """Pipeline data sources + pool definition."""

    data_sources: list[DataSourceSpec] = Field(default_factory=list)
    pool: BilingualPoolSpec = BilingualPoolSpec()


# ---------------------------------------------------------------------------
# Evaluation set (and its physical→abstract column mapping)
# ---------------------------------------------------------------------------


class EvalSetColumns(BaseModel):
    """Map abstract field names to the CSV's physical column names.

    The single most important decoupling for language-agnosticism — readers
    elsewhere ask for `cfg.eval_set.columns.reference` instead of the literal
    string 'ko_reference'.
    """

    sctid: str = "sctid"
    source_term: str = "preferred_term"
    reference: str = "ko_reference"
    all_references: str = "ko_all"


class EvalSetSpec(BaseModel):
    """The CSV used as the source of truth for evaluation.

    Either point at a pre-built CSV (`csv` field) OR derive from one of the
    data sources by id (`source` field). When `source` is set, the
    eval_set stage filters/samples that source to produce `csv`.

    Eval sets are run-specifying, not pipeline-defining: the same pipeline
    can be evaluated against the 100-term SME packet, the long-tail set,
    or a synthetic stress set without changing the pipeline itself.
    Load standalone files via :meth:`from_file`; the run CLI's
    ``--eval-set`` flag overrides the pipeline's inline default.
    """

    csv: Path
    source: str | None = Field(
        default=None,
        description="Optional reference to a data_sources[].id. When set, "
                    "the eval_set stage builds `csv` from this source.",
    )
    sample_size: int | None = Field(
        default=None,
        description="Stratified sample size; null = use all rows.",
    )
    columns: EvalSetColumns = EvalSetColumns()
    multi_ref_separator: str = "|"
    splits_dir: Path | None = Field(
        default=None,
        description="If set, expects train.csv / dev.csv / test.csv inside.",
    )

    @classmethod
    def from_file(cls, path: Path | str) -> "EvalSetSpec":
        path = Path(path)
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
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


# ---------------------------------------------------------------------------
# Resources (port of configs/resources_ko.yaml)
# ---------------------------------------------------------------------------


ResourceKind = Literal[
    "prompt_addendum", "term_dictionary", "retrieval_corpus", "exemplar_set"
]
OverlapPolicy = Literal["additive", "most_specific", "union_dedupe"]


class ResourcePayload(BaseModel):
    """Free-form payload — each kind interprets its own fields."""

    model_config = ConfigDict(extra="allow")
    path: Path | None = None
    key_path: str | None = None
    match_mode: str | None = None
    collection: str | None = None


class ResourceSpec(BaseModel):
    """One resource entry — mirrors `resources_ko.yaml` exactly."""

    id: str
    kind: ResourceKind
    scope: str = Field(default="<<138875005", description="ECL expression.")
    payload: ResourcePayload
    overlap: OverlapPolicy | None = Field(
        default=None,
        description="Override the defaults.overlap[<kind>] value for this entry.",
    )


class OverlapDefaults(BaseModel):
    """Default overlap policy per kind. Matches resources_ko.yaml defaults."""

    prompt_addendum: OverlapPolicy = "additive"
    term_dictionary: OverlapPolicy = "most_specific"
    retrieval_corpus: OverlapPolicy = "additive"
    exemplar_set: OverlapPolicy = "union_dedupe"


class ResourceManifest(BaseModel):
    """The on-disk resources registry (configs/resources_ko.yaml).

    Resources are kept as a single hand-authored YAML manifest rather than
    per-resource files: entries carry rich shapes (``variants``, free-form
    ``payload``, key-path DSL) plus documenting comments that don't round-trip
    through per-field forms. The Resources UI edits this file as raw YAML; the
    assembler validates each ``resources[]`` entry to :class:`ResourceSpec`
    lazily and filters by the ids a flow selects.
    """

    model_config = ConfigDict(extra="allow")
    version: int = 1
    language: str | None = None
    defaults: dict[str, Any] | None = None
    resources: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path | str) -> "ResourceManifest":
        path = Path(path)
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
        return cls.model_validate(data or {})


# ---------------------------------------------------------------------------
# Qdrant + embedder
# ---------------------------------------------------------------------------


class BgeM3Spec(BaseModel):
    model_name: str = "BAAI/bge-m3"
    use_fp16: bool = False
    batch_size: int = 256
    max_length: int = 512


class QdrantSpec(BaseModel):
    url: str = "http://localhost:6333"
    api_key_env: str | None = None
    exemplar_collection: str | None = Field(
        default=None,
        description=(
            "Override for the exemplar collection name. Normally left unset — "
            "PipelineConfig.resolved_exemplar_collection() derives a "
            "deterministic name from the pool contents + embedder + language "
            "so two configs with the same pool share one indexed collection."
        ),
    )
    bgem3: BgeM3Spec = BgeM3Spec()


# ---------------------------------------------------------------------------
# Models + jobs (mirror configs/models.json)
# ---------------------------------------------------------------------------


class ModelSpec(BaseModel):
    """Single LLM endpoint definition (mirrors configs/models.json entries).

    Local vLLM: just `port` (implicit localhost).
    Remote: `host` + `port`. The "Test endpoint" probe and runtime URL builder
    construct base_url identically:
        f"{'https' if port == 443 else 'http'}://{host or 'localhost'}:{port}/v1"
    """

    model_config = ConfigDict(extra="allow")
    # Either hf_id (vLLM/Dashscope) or model_path (llama.cpp GGUF) is required;
    # callers should check which one is set.
    hf_id: str | None = None
    model_path: str | None = None
    port: int = 8000
    host: str | None = None
    image: str | None = None
    container_name: str | None = None
    notes: str | None = None
    # Default runtime bundle used when the assembler synthesises a translation
    # candidate for this model (so flows stay terse — a translate step just
    # names model_key and inherits these). Per-step params still win.
    llm_params: dict[str, Any] | None = None
    api_key_env: str | None = Field(
        default=None,
        description="Env var holding the bearer token for remote endpoints "
                    "(e.g. DASHSCOPE_API_KEY); null for local vLLM.",
    )


class JobSpec(BaseModel):
    """One pipeline job (mirrors configs/models.json `jobs.*` entries)."""

    model_config = ConfigDict(extra="allow")
    script: str | None = None
    description: str | None = None
    default_model: str | None = None
    concurrency: int = 16
    eval_set: str | None = None
    output_dir: str | None = None
    qdrant_collection: str | None = None
    lookup_topn: int = 5
    style_guide: str | None = None
    llm_params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-stage specs (translation / evaluation / optimization / sme)
# ---------------------------------------------------------------------------


class PromptTemplates(BaseModel):
    """Translation prompt templates — language-agnostic; the language string
    is interpolated from cfg.language at runtime via {language_name} /
    {language_native} placeholders."""

    system: str = Field(
        default=(
            "You are a medical terminology translator specialising in English "
            "to {{language_name}} translation of SNOMED CT clinical terms in the "
            "**Procedure** hierarchy. You must follow the style guide below. "
            "Return ONLY the {{language_name}} translation in {{language_script_name}} "
            "— no explanation, no quotes, no romanisation, no English, no extra "
            "text.\n\n# Style guide\n\n{{style_guide}}"
        ),
    )
    user: str = Field(
        default=(
            "Here are similar {{language_name}} SNOMED translations for "
            "reference:\n\n{{paired_translations}}\n\n"
            "Translate this SNOMED CT procedure term from English to "
            "{{language_name}}.\nEnglish: {{english}}\n{{language_name}}:"
        ),
    )
    # Version-controlled store templates (prompt-templates feature): when set, the
    # translate stage loads the body from WIZARD_PROMPTS_DIR/<id> instead of the
    # inline default above — the ONE render path shared with GEPA (design D7).
    # Falls back to the inline default when the id isn't found in the store, so
    # output is unchanged whether or not the store is present.
    system_template_id: str | None = "translate_system"
    user_template_id: str | None = "translate_user"


class TranslationCandidate(BaseModel):
    """One callable model + its run-time bundle.

    Different models want different runtime params: gpt-oss-120b wants
    ``enable_thinking=True``; qwen122b is faster with it off. A remote
    endpoint may need ``concurrency=4`` while a local vLLM is happy at 32.
    Each candidate carries its own settings so pipelines don't have to
    compromise on a one-size-fits-all default.
    """

    model_key: str = Field(
        ..., description="Key into PipelineConfig.models.")
    concurrency: int = 16
    llm_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_tokens": 256,
            "temperature": 0.0,
            "stop": ["\n\n", "English:"],
        },
        description="Sent verbatim to the OpenAI-compatible /chat/completions "
                    "endpoint. enable_thinking, chat_template_kwargs, etc.",
    )
    api_key_env: str | None = Field(
        default=None,
        description="Env var to read for the bearer token; null for local vLLM.",
    )


class TranslationStageSpec(BaseModel):
    """Knobs for the translate stage.

    Models are configured as a list of *candidates*, each with its own
    ``concurrency``, ``llm_params``, and ``api_key_env``. The runner's
    ``--model-key`` flag (and the wizard's Review-page picker) chooses one
    candidate per run; comparison runs swap candidates without editing the
    pipeline. Legacy single-model configs are migrated to a one-entry
    candidates list at validation time.
    """

    candidates: list[TranslationCandidate] = Field(
        default_factory=list,
        description="Models the pipeline is allowed to run against, each "
                    "with its own runtime bundle.",
    )
    default_model_key: str | None = Field(
        default=None,
        description="model_key of the candidate used when --model-key isn't "
                    "supplied. Auto-set to candidates[0].model_key if omitted.",
    )

    # ---- Legacy single-model fields. Set None as default — present only
    # to migrate older configs / wizard sessions. The validator folds them
    # into a synthesised candidate.
    model_key: str | None = None
    concurrency: int | None = None
    llm_params: dict[str, Any] | None = None
    api_key_env: str | None = None

    # ---- Common (apply to every candidate)
    lookup_topn: int = 5
    style_guide_path: Path | None = Field(
        default=None,
        description=(
            "Optional default style guide. Style guides are flow artifacts: "
            "translate steps in a flow supply their own (typically a path to "
            "a saved style guide file, or a $opt.optimized_style_guide ref). "
            "Set this only if you want single-stage `python -m snomed_translation.run "
            "--stage translate` invocations to have something to fall back on."
        ),
    )
    prompt_templates: PromptTemplates = PromptTemplates()
    output_tag: str = "default"
    output_filename_pattern: str = "translations_{output_tag}_lookup.csv"

    @model_validator(mode="after")
    def _normalise_candidates(self) -> "TranslationStageSpec":
        # Migrate legacy single-model shape into a candidates entry.
        if not self.candidates and self.model_key:
            self.candidates = [TranslationCandidate(
                model_key=self.model_key,
                concurrency=self.concurrency if self.concurrency is not None else 16,
                llm_params=self.llm_params if self.llm_params is not None else {
                    "max_tokens": 256,
                    "temperature": 0.0,
                    "stop": ["\n\n", "English:"],
                },
                api_key_env=self.api_key_env,
            )]
        # Default to the first candidate if not specified.
        if self.default_model_key is None and self.candidates:
            self.default_model_key = self.candidates[0].model_key
        # Validate default is one of the listed candidates.
        if self.default_model_key is not None:
            keys = [c.model_key for c in self.candidates]
            if self.default_model_key not in keys:
                raise ValueError(
                    f"default_model_key {self.default_model_key!r} is not in "
                    f"candidates {keys}"
                )
            # Detect duplicate model_keys — current design keys candidates
            # uniquely by model_key. Add a label field if you need two
            # configurations of the same model_key.
            dupes = [k for k in set(keys) if keys.count(k) > 1]
            if dupes:
                raise ValueError(
                    f"duplicate model_key(s) in candidates: {dupes}. "
                    "Each candidate must have a unique model_key."
                )
        return self

    def resolve_candidate(
        self, override_key: str | None = None
    ) -> TranslationCandidate:
        """Pick the candidate for this run, validating against the whitelist."""
        key = override_key or self.default_model_key
        if key is None:
            raise RuntimeError(
                "translation has no candidates configured — add at least one "
                "candidate (or pass --model-key)."
            )
        for c in self.candidates:
            if c.model_key == key:
                return c
        listed = [c.model_key for c in self.candidates]
        raise RuntimeError(
            f"model_key {key!r} is not in candidates {listed}; either add it "
            "to the pipeline or pick from the listed candidates."
        )


class ScorerSpec(BaseModel):
    """One scoring component contributing to the evaluation composite."""

    kind: Literal[
        "exact_match", "chrf", "token_jaccard", "char_sim",
        "back_translation", "cosine_similarity",
    ]
    weight: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)


class JudgeSpec(BaseModel):
    """LLM-as-judge configuration."""

    kind: Literal["none", "local_llm", "sonnet"] = "none"
    model_key: str | None = None
    labels: list[str] = Field(default_factory=lambda: ["ACCEPTABLE", "PARTIAL", "WRONG"])
    concurrency: int = 8
    # The two judge prompts; {language_name} interpolated at runtime.
    system_template: str | None = None
    user_template: str | None = None


class EvalStageSpec(BaseModel):
    scorers: list[ScorerSpec] = Field(
        default_factory=lambda: [
            ScorerSpec(kind="exact_match", weight=0.2),
            ScorerSpec(kind="chrf", weight=0.5),
            ScorerSpec(kind="cosine_similarity", weight=0.3),
        ]
    )
    multi_ref: bool = True
    judge: JudgeSpec = JudgeSpec()


class GepaSpec(BaseModel):
    auto: Literal["light", "medium", "heavy"] = "medium"
    max_metric_calls: int | None = None
    track_stats: bool = True


class ReflectionLmSpec(BaseModel):
    """Legacy: pre-catalog reflection-LM config (model_id + base_url +
    api_key_env). Kept for back-compat with pipeline configs that haven't
    been re-saved through the wizard yet. New configs should use
    ``OptimizationStageSpec.reflection_candidates`` referring to keys in the
    models catalog instead.
    """

    model_id: str
    base_url: str | None = None
    api_key_env: str | None = None
    disable_thinking: bool = False
    temperature: float = 1.0
    max_tokens: int = 4000


class ReflectionCandidate(BaseModel):
    """A reflection LM eligible for use by GEPA, referencing a model in the
    pipeline's catalog.

    ``disable_thinking`` is per-role, not per-model: the same Qwen model
    might want thinking on when translating but off when reflecting, so it
    lives here rather than on the catalog entry.
    """

    model_key: str = Field(
        ..., description="Key into PipelineConfig.models.")
    disable_thinking: bool = False
    temperature: float = 1.0
    max_tokens: int = 4000


class OptimizationStageSpec(BaseModel):
    """The optimization *recipe* — what kind of GEPA run to do, with what
    reflection LM, against what hints. The *inputs* (seed style guide, train
    split) are flow artifacts: an ``optimize`` step in a flow supplies them
    explicitly. The *output* is an optimised style guide that downstream
    translate steps reference via ``$opt_step.optimized_style_guide``.
    """

    # Optional defaults for single-stage CLI invocations. Flow steps always
    # supply their own.
    seed_style_guide: Path | None = None
    splits_dir: Path | None = None
    lookup_cache: Path | None = None
    gepa: GepaSpec = GepaSpec()

    # Reflection LM as candidates referring to the model catalog.
    reflection_candidates: list[ReflectionCandidate] = Field(
        default_factory=list,
        description="Models from PipelineConfig.models eligible to be the "
                    "reflection LM. Flow steps pick one per run.",
    )
    default_reflection_model_key: str | None = Field(
        default=None,
        description="Default reflection candidate (model_key). Auto-set to "
                    "reflection_candidates[0] if omitted.",
    )

    # Legacy free-form reflection config. Ignored when reflection_candidates
    # is populated; left in place so older configs still validate.
    reflection_lm: ReflectionLmSpec | None = None

    hints_file: Path | None = Field(
        default=None,
        description="YAML with language-specific rule-violation hints used by "
        "the metric's reflective-feedback string. See configs/hints/ko.yaml.",
    )
    hard_rules_file: Path | None = Field(
        default=None,
        description="YAML of non-negotiable hard rules (configs/hard_rules/"
        "<lang>.yaml). freeze=true rules are injected into the prompt as a "
        "constant field GEPA cannot mutate; enforce=true rules subtract a score "
        "penalty in the metric, removing GEPA's incentive to explore the "
        "disallowed form. See pipelines/hard_rules.py.",
    )

    @model_validator(mode="after")
    def _normalise_reflection(self) -> "OptimizationStageSpec":
        if self.default_reflection_model_key is None and self.reflection_candidates:
            self.default_reflection_model_key = self.reflection_candidates[0].model_key
        if self.default_reflection_model_key is not None:
            keys = [c.model_key for c in self.reflection_candidates]
            if self.default_reflection_model_key not in keys:
                raise ValueError(
                    f"default_reflection_model_key "
                    f"{self.default_reflection_model_key!r} is not in "
                    f"reflection_candidates {keys}"
                )
            dupes = [k for k in set(keys) if keys.count(k) > 1]
            if dupes:
                raise ValueError(
                    f"duplicate reflection model_key(s): {dupes}. Each must "
                    "be unique."
                )
        return self

    def resolve_reflection_candidate(
        self, override_key: str | None = None
    ) -> ReflectionCandidate:
        """Pick the reflection candidate for this run."""
        key = override_key or self.default_reflection_model_key
        if key is None:
            raise RuntimeError(
                "optimization has no reflection candidates configured — add "
                "at least one (or pass reflection_model_key on the flow step)."
            )
        for c in self.reflection_candidates:
            if c.model_key == key:
                return c
        listed = [c.model_key for c in self.reflection_candidates]
        raise RuntimeError(
            f"reflection model_key {key!r} not in candidates {listed}."
        )


class SmeReviewerSpec(BaseModel):
    kind: Literal["sonnet", "local_llm", "manual"] = "sonnet"
    model_key: str | None = None


class SmeStageSpec(BaseModel):
    sample_size: int = 100
    stratify_by: list[str] = Field(default_factory=lambda: ["modality"])
    output_dir: Path = Path("data/sme_review")
    reviewer: SmeReviewerSpec = SmeReviewerSpec()
    prepare_lookups: bool = True


# ---------------------------------------------------------------------------
# Project — the shared environment block referenced by flows
# ---------------------------------------------------------------------------


def _spec_from_file(cls, path: Path | str):
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    return cls, data


def _spec_save(self, path: Path | str) -> None:
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


# Environment fields that legacy flat project.json files carried inline, lifted
# into an inline :class:`EnvironmentSpec` so old files keep loading (#23).
_ENV_KEYS = ("language", "paths", "qdrant", "overlap_defaults", "default_model_key")


class EnvironmentSpec(BaseModel):
    """The run *context* a flow executes in (configs/environments/<name>.json).

    The 'where + how runs are wired' that doesn't change per experiment:
    language, filesystem paths, Qdrant/embedder, the overlap-resolution policy
    and the fallback model. A reusable, named block an :class:`InvestigationSpec`
    chooses as its default and a Run may override — so the same flow run under
    two environments is directly comparable (#22).
    """

    version: int = 1
    name: str = Field(
        default="default",
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Stable id; the configs/environments/<name>.json filename stem.",
    )
    description: str = Field(
        default="",
        description="Free-text note on what this run context is for.",
    )
    language: LanguageSpec
    paths: PathsSpec = PathsSpec()
    qdrant: QdrantSpec = QdrantSpec()
    overlap_defaults: OverlapDefaults = OverlapDefaults()
    default_model_key: str | None = None

    @classmethod
    def from_file(cls, path: Path | str) -> "EnvironmentSpec":
        cls, data = _spec_from_file(cls, path)
        return cls.model_validate(data)

    save = _spec_save


class RecipeSpec(BaseModel):
    """Translation-domain stage recipes + pool-composition defaults.

    Owned by the domain plugin, not the generic app: these ride as top-level
    keys on the investigation file and are read here (extra keys ignored) so the
    generic :class:`InvestigationSpec` never needs to know them (#16). The
    assembler reads recipe fields from this, environment fields from the
    :class:`EnvironmentSpec`.
    """

    model_config = ConfigDict(extra="ignore")

    # Pool-composition defaults; the flow picks which source ids to include.
    pool_output_csv: Path | None = None
    pool_dedup_key: list[str] = Field(default_factory=lambda: ["en_lower", "target"])

    # Stage recipes that rarely vary per flow (overridable per flow step).
    evaluation: EvalStageSpec = EvalStageSpec()
    optimization: OptimizationStageSpec | None = None
    sme: SmeStageSpec | None = None


class InvestigationSpec(BaseModel):
    """A research grouping: a question + the runs and results under it.

    Thin by design — it chooses a default :class:`EnvironmentSpec` (the run
    context) by name and optional default eval data; runs pick the environment
    at run time. The domain plugin's :class:`RecipeSpec` fields ride along as
    extra keys (``extra="allow"``) so they are preserved untouched on a UI
    round-trip even though the generic spec does not type them (#16).

    Back-compat: a legacy flat project.json (env fields inline, no
    ``environment`` key) is loaded by lifting those fields into an inline
    environment, so existing deployments keep working (#23).
    """

    model_config = ConfigDict(extra="allow")

    version: int = 1
    name: str = Field(
        default="investigation",
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Stable id; the configs/investigations/<name>.json filename stem.",
    )
    description: str = Field(
        default="",
        description="Free-text statement of the investigation's question / goal.",
    )
    environment: str | EnvironmentSpec = Field(
        default="default",
        description="Default run context: a configs/environments/<name>.json name, "
                    "or an inline environment (legacy flat files are lifted here).",
    )
    default_eval_set: str | None = Field(
        default=None,
        description="Default eval-set id for runs grouped under this investigation.",
    )

    @classmethod
    def from_file(cls, path: Path | str) -> "InvestigationSpec":
        cls, data = _spec_from_file(cls, path)
        if isinstance(data, dict) and "environment" not in data \
                and any(k in data for k in _ENV_KEYS):
            data = dict(data)
            env: dict = {"name": data.get("name", "default"), "description": ""}
            for k in _ENV_KEYS:
                if k in data:
                    env[k] = data.pop(k)
            data["environment"] = env
        return cls.model_validate(data)

    save = _spec_save


# Back-compat alias: the entity was called ``Project`` before the rename (#21).
ProjectSpec = InvestigationSpec


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class PipelineConfig(BaseModel):
    """Complete configuration for a single language's translation pipeline."""

    version: int = 1
    language: LanguageSpec
    paths: PathsSpec = PathsSpec()
    sources: SourcesSpec = SourcesSpec()
    eval_set: EvalSetSpec | None = Field(
        default=None,
        description=(
            "Inline default eval set. Optional — pipelines that never bake in "
            "a specific eval set are fine; the runner's --eval-set flag (or "
            "the wizard's Review-page picker) supplies one per run."
        ),
    )
    resources: list[ResourceSpec] = Field(default_factory=list)
    overlap_defaults: OverlapDefaults = OverlapDefaults()
    qdrant: QdrantSpec = QdrantSpec()
    models: dict[str, ModelSpec] = Field(default_factory=dict)
    jobs: dict[str, JobSpec] = Field(default_factory=dict)
    translation: TranslationStageSpec
    evaluation: EvalStageSpec = EvalStageSpec()
    optimization: OptimizationStageSpec | None = None
    sme: SmeStageSpec | None = None

    # ----- IO ----------------------------------------------------------------

    @classmethod
    def from_file(cls, path: Path | str) -> "PipelineConfig":
        path = Path(path)
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
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

    # ----- Helpers -----------------------------------------------------------

    def model_base_url(self, model_key: str) -> str:
        """Construct the OpenAI-compatible base URL for a model entry.

        Matches the convention used today in translate_korean_with_lookup.py
        (port 443 → https + omit port; otherwise http://host:port).
        """
        m = self.models[model_key]
        host = m.host or "localhost"
        if m.port == 443:
            return f"https://{host}/v1"
        return f"http://{host}:{m.port}/v1"

    def resolved_exemplar_collection(self) -> str:
        """Effective Qdrant collection name.

        If ``qdrant.exemplar_collection`` is explicitly set, return it verbatim
        (existing configs and intentional overrides win). Otherwise derive a
        deterministic name from the pool contents + embedder + language, so
        two configs that share a pool share a collection — no re-indexing,
        and changing a single source produces a new collection automatically.
        """
        if self.qdrant.exemplar_collection:
            return self.qdrant.exemplar_collection

        import hashlib

        # Pick which sources actually go into the pool. Empty pool.sources
        # means "all enabled data_sources" (matches BilingualPoolSpec docs).
        selected_ids = set(self.sources.pool.sources)
        picked = [
            s for s in self.sources.data_sources
            if s.enabled and (not selected_ids or s.id in selected_ids)
        ]
        picked.sort(key=lambda s: s.id)

        def fingerprint(s: "DataSourceSpec") -> str:
            kind = str(s.kind)
            if kind == "athena_vocabulary":
                key = f"{s.athena_vocabulary or ''}|{s.athena_language_concept_id or ''}"
            elif kind == "snomed_national_extension":
                key = f"{s.language_refset_id or ''}|{s.snomed_filter.model_dump_json() if s.snomed_filter else ''}"
            elif kind == "csv":
                key = str(s.csv_path or "")
            elif kind == "loinc_linguistic_variant":
                key = str(s.loinc_variant_file or "")
            else:
                key = ""
            return f"{s.id}::{kind}::{key}"

        canonical = "|".join([
            self.language.code,
            self.qdrant.bgem3.model_name,
            *(fingerprint(s) for s in picked),
        ])
        digest = hashlib.blake2b(canonical.encode("utf-8"), digest_size=3).hexdigest()
        return f"pool_{self.language.code}_{digest}"
