"""Provision a new language translation project from its raw ingredients.

This is the domain core behind the *new-language-project wizard* — the same
functions drive both the app's UI wizard and the MCP tools, so a human clicking
through and an LLM calling tools do exactly the same thing. It generalises the
manual steps taken to stand up the Estonian project (see
``docs/design/multi-language-and-data-layout.md``): scaffold a ``configs/<code>/``
bundle, lay out ``data/languages/<code>/``, and — the part worth automating —
**auto-detect the SNOMED language refset id** from an RF2 archive so nobody has
to hand-hunt it.

Everything here is pure (no FastAPI, no MCP): functions take explicit repo roots
and return plain dataclasses/dicts, so they're trivially testable and callable
from either front-end.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# RF2 Language refset column (0-based) holding the refset id, and the accept/ value
# columns we filter on. Tab-separated; header names are stable across editions.
_REFSET_ID_COL = "refsetId"
_ACTIVE_COL = "active"


# --------------------------------------------------------------------------- #
# 1. Archive detection — the automation win.
# --------------------------------------------------------------------------- #
@dataclass
class ArchiveInfo:
    """What we learned by inspecting an RF2 national-extension archive."""

    edition_dir: str          # the dir directly containing ``Snapshot/``
    description_file: str     # target-language Description snapshot (…-<code>…)
    language_refset_id: str   # detected from the Language refset snapshot
    term_count: int | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "edition_dir": self.edition_dir,
            "description_file": self.description_file,
            "language_refset_id": self.language_refset_id,
            "term_count": self.term_count,
            "warnings": self.warnings,
        }


def _find_edition_root(archive_path: Path) -> Path:
    """The directory that directly contains a ``Snapshot/`` subtree.

    ManagedService archives are often doubly nested
    (``X/X/Snapshot/…``); some are flat (``X/Snapshot/…``). We locate the
    shallowest dir with a ``Snapshot`` child so both shapes work."""
    if (archive_path / "Snapshot").is_dir():
        return archive_path
    candidates = sorted(
        (p.parent for p in archive_path.rglob("Snapshot") if p.is_dir()),
        key=lambda p: len(p.parts),
    )
    if not candidates:
        raise ValueError(
            f"no RF2 Snapshot/ found under {archive_path} — is this an unzipped "
            "RF2 release? (expected <edition>/Snapshot/Terminology/…)"
        )
    return candidates[0]


def _glob_one(base: Path, patterns: list[str], what: str) -> Path:
    """First file matching any of ``patterns`` under ``base`` (recursive)."""
    for pat in patterns:
        hits = sorted(base.rglob(pat))
        if hits:
            return hits[0]
    raise ValueError(f"could not find {what} (looked for {patterns} under {base})")


def detect_snomed_archive(archive_path: str | Path, code: str) -> ArchiveInfo:
    """Inspect an unzipped RF2 archive for the target language ``code``.

    Locates the edition dir, the ``…Description…-<code>…`` snapshot, and reads the
    ``…Language…-<code>…`` refset snapshot to auto-detect the language refset id
    (the active-row ``refsetId``; the modal value wins, with a warning if the file
    carries more than one). Returns an :class:`ArchiveInfo`; raises with an
    actionable message if the archive doesn't look like RF2."""
    root = Path(archive_path)
    if not root.exists():
        raise ValueError(f"archive path does not exist: {root}")
    edition = _find_edition_root(root)

    desc = _glob_one(
        edition / "Snapshot",
        # National extensions: "…Description_Snapshot-et_EE…". International
        # editions carry an infix before "Snapshot" (e.g. Spanish edition:
        # "…Description_SpanishExtensionSnapshot-es_INT…"), so allow "*" between.
        [f"*Description_Snapshot-{code}_*.txt", f"*Description_Snapshot-{code}.txt",
         f"*Description_*Snapshot-{code}_*.txt", f"*Description_*Snapshot-{code}.txt"],
        f"a Description snapshot for language '{code}'",
    )
    lang = _glob_one(
        edition / "Snapshot",
        [f"*LanguageSnapshot-{code}_*.txt", f"*Language_Snapshot-{code}_*.txt",
         f"*LanguageSnapshot-{code}.txt",
         f"*Language*Snapshot-{code}_*.txt", f"*Language*Snapshot-{code}.txt"],
        f"a Language refset snapshot for language '{code}'",
    )

    warnings: list[str] = []
    refset_ids: Counter = Counter()
    with lang.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            if row.get(_ACTIVE_COL) == "1" and row.get(_REFSET_ID_COL):
                refset_ids[row[_REFSET_ID_COL]] += 1
    if not refset_ids:
        raise ValueError(
            f"no active rows in the Language refset {lang.name} — cannot detect "
            "the language refset id"
        )
    language_refset_id, _ = refset_ids.most_common(1)[0]
    if len(refset_ids) > 1:
        warnings.append(
            f"multiple language refset ids present {dict(refset_ids)}; picked the "
            f"most common ({language_refset_id}) — confirm this is the target-language refset"
        )

    term_count: int | None = None
    try:
        with desc.open(encoding="utf-8") as fh:
            term_count = sum(1 for _ in fh) - 1  # minus header
    except OSError:
        pass

    return ArchiveInfo(
        edition_dir=str(edition),
        description_file=str(desc),
        language_refset_id=language_refset_id,
        term_count=term_count,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# 2. Data pool — sniff the bilingual CSV.
# --------------------------------------------------------------------------- #
def sniff_pool_columns(csv_path: str | Path, code: str) -> dict:
    """Guess the ``{en, target[, sctid, source]}`` column mapping of a bilingual
    pool CSV from its header. English is matched by common names; the target
    column prefers an exact/upper ``<code>`` match, else the first non-English
    column. Raises if the header can't be read."""
    header = _read_header(csv_path)
    if not header:
        raise ValueError(f"empty or unreadable CSV header: {csv_path}")
    lower = {h.lower(): h for h in header}

    en = next((lower[k] for k in ("en", "english", "source_term", "preferred_term", "en_term")
               if k in lower), None)
    target = None
    for cand in (code, code.upper(), code.lower(), "target", "translation", "tgt"):
        if cand.lower() in lower:
            target = lower[cand.lower()]
            break
    if target is None:
        target = next((h for h in header if h != en), None)
    if en is None:
        en = next((h for h in header if h != target), header[0])

    mapping = {"en": en, "target": target}
    if "sctid" in lower:
        mapping["sctid"] = lower["sctid"]
    if "source" in lower:
        mapping["source"] = lower["source"]
    return mapping


def _read_header(csv_path: str | Path) -> list[str]:
    with Path(csv_path).open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


# --------------------------------------------------------------------------- #
# 3. Scaffold the config bundle + data skeleton.
# --------------------------------------------------------------------------- #
@dataclass
class ScaffoldResult:
    code: str
    configs_dir: str
    data_dir: str
    style_guide_dir: str
    project_json: str
    created: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "configs_dir": self.configs_dir,
            "data_dir": self.data_dir,
            "style_guide_dir": self.style_guide_dir,
            "project_json": self.project_json,
            "created": self.created,
        }


_SUBDIRS = ("sources", "eval_sets", "investigations", "environments",
            "problems", "prompts", "flows", "hard_rules", "judge")
_DATA_SUBDIRS = ("snomed", "pool", "lexicons", "corpora", "evals", "derived", "sme_review")


def scaffold_language_project(
    *,
    code: str,
    name: str,
    configs_root: str | Path,
    data_root: str | Path,
    style_guide_root: str | Path,
    repo_root: str | Path | None = None,
    direction: str | None = None,
    tokenizer_lang: str = "en",
    qdrant_url: str = "http://localhost:6333",
    default_model_key: str = "gemma4-26b",
    archive: ArchiveInfo | None = None,
    seed_style_guide: bool = True,
    overwrite: bool = False,
) -> ScaffoldResult:
    """Create ``<configs_root>/<code>/`` (project.json, resources.yaml, hints.yaml,
    sources/, empty section dirs), the ``<data_root>/<code>/`` skeleton, and a seed
    style guide under ``<style_guide_root>/<code>/``.

    ``configs_root``/``data_root``/``style_guide_root`` are the shared repo roots
    (e.g. ``configs``, ``data/languages``, ``style_guide``). Paths written into
    project.json are repo-relative (``data/languages/<code>/…``) assuming the app
    runs from the plugin repo root. If ``archive`` is given, a
    ``sources/<code>_snomed.json`` is written with the detected rf2 paths + refset
    id. Errors if the bundle already exists unless ``overwrite``."""
    _validate_code(code)
    direction = direction or f"EN->{code.upper()}"
    configs_root, data_root, style_guide_root = map(Path, (configs_root, data_root, style_guide_root))
    cfg_dir = configs_root / code
    data_dir = data_root / code
    sg_dir = style_guide_root / code
    project_json_path = cfg_dir / "project.json"

    if project_json_path.exists() and not overwrite:
        raise ValueError(
            f"project '{code}' already exists at {project_json_path} (pass overwrite=True to replace)")

    created: list[str] = []

    def _mkdir(p: Path):
        p.mkdir(parents=True, exist_ok=True)

    _mkdir(cfg_dir)
    for sub in _SUBDIRS:
        _mkdir(cfg_dir / sub)
        keep = cfg_dir / sub / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
    for sub in _DATA_SUBDIRS:
        _mkdir(data_dir / sub)
    _mkdir(sg_dir)

    # Paths written into project.json are repo-relative (e.g. data/languages/<code>)
    # so they resolve from the repo root regardless of the app's cwd. Filesystem
    # ops above used the (possibly absolute) roots; here we relativise for the JSON.
    repo = Path(repo_root) if repo_root is not None else configs_root.parent
    data_rel = _relpath(data_dir, repo)
    code_cfg = _relpath(cfg_dir, repo)
    sg_rel = _relpath(sg_dir, repo)

    project = _project_json(
        code=code, name=name, direction=direction, tokenizer_lang=tokenizer_lang,
        qdrant_url=qdrant_url, default_model_key=default_model_key,
        data_rel=data_rel, code_cfg=code_cfg, sg_rel=sg_rel,
    )
    project_json_path.write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    created.append(str(project_json_path))

    (cfg_dir / "resources.yaml").write_text(_resources_yaml(code, sg_rel=sg_rel), encoding="utf-8")
    created.append(str(cfg_dir / "resources.yaml"))
    (cfg_dir / "hints.yaml").write_text(_hints_yaml(code), encoding="utf-8")
    created.append(str(cfg_dir / "hints.yaml"))

    if archive is not None:
        src = _snomed_source_spec(code, archive, data_rel, repo)
        p = cfg_dir / "sources" / f"{code}_snomed.json"
        p.write_text(json.dumps(src, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        created.append(str(p))

    if seed_style_guide:
        guide = sg_dir / f"style_guide_{code}_seed.md"
        if not guide.exists() or overwrite:
            guide.write_text(_seed_style_guide(name), encoding="utf-8")
            created.append(str(guide))

    return ScaffoldResult(
        code=code, configs_dir=str(cfg_dir), data_dir=str(data_dir),
        style_guide_dir=str(sg_dir), project_json=str(project_json_path), created=created,
    )


def register_bilingual_pool(
    *,
    code: str,
    csv_path: str | Path,
    configs_root: str | Path,
    columns: dict | None = None,
) -> dict:
    """Write ``<configs_root>/<code>/sources/<code>_pool.json`` for the bilingual
    pool CSV, sniffing the column mapping if not given. Returns the source spec."""
    _validate_code(code)
    columns = columns or sniff_pool_columns(csv_path, code)
    spec = {
        "id": f"{code}_pool",
        "kind": "csv",
        "enabled": True,
        "output_csv": str(csv_path),
        "csv_path": str(csv_path),
        "csv_columns": columns,
    }
    missing = [k for k in ("sctid", "source") if k not in columns]
    if missing:
        spec["notes"] = (
            f"Pool is missing {missing}; concept-keyed exemplar retrieval / multi-source "
            "dedup need sctid + source columns. Enrich via scripts/data_prep before indexing."
        )
    out = Path(configs_root) / code / "sources" / f"{code}_pool.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return spec


# --------------------------------------------------------------------------- #
# 4. Instantiate a project template (problem tree + plan + wired flows).
# --------------------------------------------------------------------------- #
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def list_templates() -> list[str]:
    """Names of the available project templates (dirs under ``templates/``)."""
    if not _TEMPLATES_DIR.is_dir():
        return []
    return sorted(p.name for p in _TEMPLATES_DIR.iterdir()
                  if p.is_dir() and (p / "manifest.json").exists())


def instantiate_template(
    *,
    code: str,
    name: str,
    configs_root: str | Path,
    template: str = "translation_project",
    model_key: str = "gemma4-26b",
    data_dir: str | None = None,
    seed_guide: str | None = None,
    rf2_relationship_file: str = "",
) -> dict:
    """Seed a scaffolded project with a curated template: the problem tree +
    ``.plan.json`` into ``configs/<code>/problems/``, the flows into
    ``configs/<code>/flows/`` (as ``<code>_<flow>.json``), the forward-declared
    sources into ``configs/<code>/sources/``, template conclusions (merged, never
    clobbered) into ``.conclusions.json``, and any verbatim ``files/`` payload
    (rule YAMLs etc. — ``__code__`` in a path is substituted) into the project
    config dir. Placeholders are rebound to THIS project's ids/paths so the flows
    are wired to its data. JSON files are validated before writing. Returns a
    summary of what was created."""
    _validate_code(code)
    tdir = _TEMPLATES_DIR / template
    if not tdir.is_dir():
        raise ValueError(f"unknown template {template!r} (have: {list_templates()})")

    data_dir = data_dir or f"data/languages/{code}"
    seed_guide = seed_guide or f"style_guide/{code}/style_guide_{code}_seed.md"
    subs = {
        "{{code}}": code,
        "{{lang_name}}": name,
        "{{data_dir}}": data_dir,
        "{{pool_source}}": f"{code}_pool",
        "{{test_split_source}}": f"{code}_test_split",
        "{{train_split_source}}": f"{code}_train_split",
        "{{dev_split_source}}": f"{code}_dev_split",
        "{{seed_guide}}": seed_guide,
        "{{model_key}}": model_key,
        "{{project}}": code,
        "{{configs_dir}}": str((Path(configs_root) / code).resolve()),
        "{{rf2_relationship_file}}": rf2_relationship_file,
    }

    def _render(text: str) -> str:
        for k, v in subs.items():
            text = text.replace(k, v)
        return text

    cfg = Path(configs_root) / code
    created: list[str] = []
    counts = {"problems": 0, "flows": 0, "sources": 0, "plan_tasks": 0}

    def _write_json(dest: Path, text: str) -> None:
        rendered = _render(text)
        json.loads(rendered)  # validate — never write malformed JSON
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rendered, encoding="utf-8")
        created.append(str(dest))

    for pf in sorted((tdir / "problems").glob("*.json")):
        _write_json(cfg / "problems" / pf.name, pf.read_text(encoding="utf-8"))
        counts["problems"] += 1

    plan = tdir / "plan.json"
    if plan.exists():
        text = plan.read_text(encoding="utf-8")
        _write_json(cfg / "problems" / ".plan.json", text)
        counts["plan_tasks"] = len(json.loads(_render(text)).get("tasks", []))

    for ff in sorted((tdir / "flows").glob("*.json")):
        _write_json(cfg / "flows" / f"{code}_{ff.name}", ff.read_text(encoding="utf-8"))
        counts["flows"] += 1

    for sf in sorted((tdir / "sources").glob("*.json")):
        _write_json(cfg / "sources" / f"{code}_{sf.name}", sf.read_text(encoding="utf-8"))
        counts["sources"] += 1

    # Template conclusions ("the laws") merge into the project's conclusion
    # store — appended, never clobbered, deduplicated by statement — so a new
    # operator inherits the method's standing findings.
    concl = tdir / "conclusions.json"
    if concl.exists():
        incoming = json.loads(_render(concl.read_text(encoding="utf-8"))).get("conclusions", [])
        dest = cfg / "problems" / ".conclusions.json"
        store = {"conclusions": []}
        if dest.exists():
            store = json.loads(dest.read_text(encoding="utf-8"))
        have = {c.get("statement", "").strip().lower() for c in store["conclusions"]}
        added = 0
        for c in incoming:
            if c.get("statement", "").strip().lower() in have:
                continue
            store["conclusions"].append(c)
            added += 1
        if added:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            created.append(str(dest))
        counts["conclusions"] = added

    # Verbatim payload files (rule YAMLs, seed CSVs): rendered for placeholders,
    # `__code__` in the relative path substituted, no JSON validation.
    files_dir = tdir / "files"
    if files_dir.is_dir():
        counts["files"] = 0
        for f in sorted(p for p in files_dir.rglob("*") if p.is_file()):
            rel = str(f.relative_to(files_dir)).replace("__code__", code)
            dest = cfg / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_render(f.read_text(encoding="utf-8")), encoding="utf-8")
            created.append(str(dest))
            counts["files"] += 1

    return {"template": template, "counts": counts, "created": created}


# --------------------------------------------------------------------------- #
# helpers / templates
# --------------------------------------------------------------------------- #
def _relpath(target: Path, base: Path) -> str:
    """``target`` relative to ``base`` in forward-slash form (for the project.json
    path fields). Falls back to the plain string if they share no common root."""
    try:
        return os.path.relpath(target, base).replace("\\", "/")
    except ValueError:
        return str(target).replace("\\", "/")


def _validate_code(code: str) -> None:
    if not code or not code.isascii() or not code.isalnum() or not code.islower():
        raise ValueError(
            f"invalid language code {code!r} — use a lowercase alphanumeric code (e.g. 'et', 'es', 'ptbr')")


def _snomed_source_spec(code: str, archive: ArchiveInfo, data_rel: str, repo: Path) -> dict:
    # Store rf2 paths repo-relative when the archive lives under the repo (like the
    # Korean kr_snomed.json), else keep the absolute path the caller supplied.
    def _maybe_rel(p: str) -> str:
        ap = Path(p)
        try:
            if ap.is_absolute() and repo.resolve() in ap.resolve().parents:
                return _relpath(ap, repo)
        except (OSError, ValueError):
            pass
        return p
    return {
        "id": f"{code}_snomed",
        "kind": "snomed_national_extension",
        "enabled": True,
        "output_csv": f"{data_rel}/pool/snomed_{code}.csv",
        "rf2_root": _maybe_rel(archive.edition_dir),
        "description_file": _maybe_rel(archive.description_file),
        "language_refset_id": archive.language_refset_id,
    }


def _project_json(*, code, name, direction, tokenizer_lang, qdrant_url,
                  default_model_key, data_rel, code_cfg, sg_rel) -> dict:
    return {
        "version": 1,
        "name": name,
        "description": f"English -> {name} SNOMED CT terminology translation.",
        "language": {"code": code, "name": name, "direction": direction,
                     "tokenizer_lang": tokenizer_lang},
        "paths": {
            "root": ".",
            "data_dir": data_rel,
            "output_dir": f"{data_rel}/evals",
            "lookup_cache": f"{data_rel}/evals/lookup_cache.json",
        },
        "qdrant": {
            "url": qdrant_url,
            "bgem3": {"model_name": "BAAI/bge-m3", "use_fp16": False,
                      "batch_size": 256, "max_length": 512},
        },
        "overlap_defaults": {
            "prompt_addendum": "additive", "term_dictionary": "most_specific",
            "retrieval_corpus": "additive", "exemplar_set": "union_dedupe",
        },
        "pool_output_csv": f"{data_rel}/pool/all_bilingual_pairs.csv",
        "pool_dedup_key": ["en_lower", "target"],
        "evaluation": {
            "scorers": [
                {"kind": "exact_match", "weight": 0.2, "params": {}},
                {"kind": "chrf", "weight": 0.5, "params": {}},
                {"kind": "cosine_similarity", "weight": 0.3, "params": {}},
            ],
            "multi_ref": True,
            "judge": {"kind": "none", "labels": ["ACCEPTABLE", "PARTIAL", "WRONG"],
                      "concurrency": 8},
        },
        "optimization": {
            "seed_style_guide": f"{sg_rel}/style_guide_{code}_seed.md",
            "splits_dir": f"{data_rel}/evals/dspy_splits",
            "lookup_cache": f"{data_rel}/evals/lookup_cache.json",
            "gepa": {"auto": "medium", "track_stats": True},
            "reflection_candidates": [],
            "reflection_lm": {
                "model_id": "openai/qwen3.7-max",
                "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "api_key_env": "DASHSCOPE_API_KEY", "disable_thinking": True,
                "temperature": 1.0, "max_tokens": 4000,
            },
            "hints_file": f"{code_cfg}/hints.yaml",
        },
        "sme": {
            "sample_size": 100, "stratify_by": ["modality", "hierarchy"],
            "output_dir": f"{data_rel}/sme_review",
            "reviewer": {"kind": "sonnet"}, "prepare_lookups": True,
        },
        "default_model_key": default_model_key,
    }


def _resources_yaml(code: str, sg_rel: str) -> str:
    return f"""# {code} SNOMED translation resource manifest (generated by the project wizard).
# Mirrors configs/resources_ko.yaml (see it for the full kind / scope / key_path DSL).
# Minimal seed: a base style guide + exemplar retrieval over the bilingual pool.
# Add {code}-specific term_dictionary / prompt_addendum / retrieval_corpus entries
# as SME-validated resources become available.

version: 1
language: {code}

defaults:
  overlap:
    prompt_addendum: additive
    term_dictionary: most_specific
    retrieval_corpus: additive
    exemplar_set: union_dedupe

resources:

  - id: base_style_guide
    kind: prompt_addendum
    scope: "<<138875005"
    payload:
      path: {sg_rel}/style_guide_{code}_seed.md

  - id: pool_exemplars
    kind: exemplar_set
    scope: "<<138875005"
    payload:
      source: {code}_pool
"""


def _hints_yaml(code: str) -> str:
    return f"""# {code} rule-violation hints used by the GEPA metric (generated by the wizard).
# Carries data, not logic. Empty lists are fine — chrF and exact-match work
# without any hints. Populate as SME feedback identifies systematic rules.

language: {code}

solid_compounds: []
"""


def _seed_style_guide(name: str) -> str:
    return f"""# {name} SNOMED CT translation — seed style guide

Seed guide for English -> {name} translation of SNOMED CT clinical terms.
Generated by the new-project wizard; replace with a GEPA-optimised or SME-induced
guide as evidence accrues.

## Scope
Translate the English SNOMED CT term into clinical {name} as used in {name}
healthcare records and the SNOMED CT {name} national extension.

## Principles
- Preserve the clinical meaning exactly; do not add, drop, or reinterpret detail.
- Use the term a clinician would write, not a literal word-for-word calque.
- Match the register and orthography of the national extension where a concept
  already has a {name} description.
- Keep the FSN semantic type consistent (a procedure stays a procedure); do not
  translate the parenthetical semantic tag as clinical text.
- Prefer established {name} medical terminology; fall back to a transparent
  Latinate/loan form only where no settled term exists.
- Output the translation only — no explanation, transliteration, or English echo.

> Populate concrete rules (compounding, abbreviation handling, term selection)
> from {name} SME review once available.
"""
