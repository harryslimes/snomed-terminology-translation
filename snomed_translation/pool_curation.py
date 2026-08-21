"""Declarative, tracked curation of the bilingual exemplar pool.

The raw pool is a derived artifact (built from per-source CSVs by
``scripts/data_prep/build_en_ko_pairs.py``) and is treated as IMMUTABLE. All
changes are expressed as rules in ``configs/<lang>/pool_rules/<lang>.yaml`` and
applied by the ``curate_exemplar_pool`` node, which writes a NEW csv and
reports per-rule counts as run metrics.

Why a node rather than a script: the run ledger then records what changed, why
(each rule carries a rationale + evidence links), and against which rules
version (content hash) — and because the exemplar collection name is derived
from CSV content, every curated variant automatically gets its own Qdrant
collection, so raw-vs-curated is a genuine A/B rather than a file mutation.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from pipelines.context import RunContext
from pipelines.functions import FunctionResult

# Post-ruling rewrites applied to `ruling_updated_only` additions.
#
# The batch-2 entry ((일반 )?x선 -> 단순 촬영) was REMOVED 2026-08-21: the
# reviewer's round-3 return (run 4e0bdfa92d98) lists 일반 x선 / 단순 x선 as
# acceptable and corrects BARE 단순 촬영 to the 방사선 forms — the transform
# had become a machine that converts acceptable forms into the current defect.
# Second supersession of a batch-2 x-ray ruling; see the retired
# no-deprecated-xray-lowercase hard rule for the first.
RULING_UPDATES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"조영상"), "영상"),
]


class PoolRulesError(Exception):
    """Raised when the rules file is missing or malformed."""


def _dataset_path(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("path") or value.get("dataset") or value.get("csv")
    return value if isinstance(value, str) else None


def load_rules(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise PoolRulesError(f"pool rules file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if "rules" not in data and "additions" not in data:
        raise PoolRulesError(f"{p} declares neither `rules` nor `additions`")
    return data


def rules_digest(path: str | Path) -> str:
    return hashlib.blake2b(Path(path).read_bytes(), digest_size=6).hexdigest()


def _compile(rule: dict) -> dict:
    m = rule.get("match") or {}
    return {
        "id": rule.get("id") or "unnamed",
        "action": (rule.get("action") or "drop").lower(),
        "en": re.compile(m["en_regex"]) if m.get("en_regex") else None,
        "target": re.compile(m["target_regex"]) if m.get("target_regex") else None,
        "sources": set(m.get("source_in") or []) or None,
        "replacement": (rule.get("replace") or {}).get("replacement"),
    }


def _fires(c: dict, en: str, ko: str, source: str) -> bool:
    if c["sources"] is not None and source not in c["sources"]:
        return False
    if c["en"] is not None and not c["en"].search(en):
        return False
    if c["target"] is not None and not c["target"].search(ko):
        return False
    # A rule with no conditions must never match everything.
    return any(c[k] is not None for k in ("en", "target")) or c["sources"] is not None


def apply_ruling_updates(text: str) -> str:
    out = text
    for pattern, replacement in RULING_UPDATES:
        out = pattern.sub(replacement, out)
    return " ".join(out.split())


def curate_exemplar_pool(ctx: RunContext, inputs: dict[str, Any],
                         params: dict[str, Any]) -> FunctionResult:
    """Filter + augment the raw pool per the rules file; write a new CSV."""
    raw_path = _dataset_path(inputs.get("pool"))
    if not raw_path or not Path(raw_path).exists():
        return FunctionResult(
            ok=False, message="curate_exemplar_pool: no `pool` dataset wired")
    rules_path = params.get("rules_file")
    if not rules_path:
        return FunctionResult(
            ok=False, message="curate_exemplar_pool: `rules_file` param required")
    out_path = params.get("output_csv")
    if not out_path:
        return FunctionResult(
            ok=False, message="curate_exemplar_pool: `output_csv` param required")

    try:
        spec = load_rules(rules_path)
    except PoolRulesError as exc:
        return FunctionResult(ok=False, message=str(exc))

    active = [_compile(r) for r in (spec.get("rules") or [])
              if r.get("enabled", True)]
    disabled = [r.get("id") for r in (spec.get("rules") or [])
                if not r.get("enabled", True)]

    counts = {c["id"]: 0 for c in active}
    kept: list[dict] = []
    with Path(raw_path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or ["EN", "KO", "source", "sctid"]
        n_raw = 0
        for row in reader:
            n_raw += 1
            en = (row.get("EN") or "").strip()
            ko = (row.get("KO") or "").strip()
            src = (row.get("source") or "").strip()
            if not en or not ko:
                continue
            dropped = False
            for c in active:
                if not _fires(c, en, ko, src):
                    continue
                counts[c["id"]] += 1
                if c["action"] == "drop":
                    dropped = True
                    break
                if c["action"] == "rewrite" and c["replacement"] is not None \
                        and c["target"] is not None:
                    ko = " ".join(c["target"].sub(c["replacement"], ko).split())
                    row["KO"] = ko
            if not dropped:
                kept.append(row)

    # Additions, applied AFTER filtering so a ruling-updated addition can never
    # be removed by the same rules that justified updating it.
    added = 0
    add_ids: list[str] = []
    # An EVAL-safe variant of the same rules: additions (notably SME gold) must
    # NOT enter a pool used to evaluate on those very concepts — self-exclusion
    # only removes a concept's OWN sctid, so sibling gold still leaks (measured:
    # ~50% of eval concepts saw an SME_gold exemplar). Production keeps them.
    include_additions = params.get("include_additions", True)
    seen = {(r.get("EN", "").strip().lower(), r.get("KO", "").strip(),
             r.get("source", ""), r.get("sctid", "")) for r in kept}
    for add in (spec.get("additions") or []) if include_additions else []:
        if not add.get("enabled", True):
            continue
        csv_path = Path(add["csv"])
        if not csv_path.exists():
            return FunctionResult(
                ok=False, message=f"addition {add.get('id')!r}: missing {csv_path}")
        cols = add.get("columns") or {}
        en_col = cols.get("en", "en")
        tgt_col = cols.get("target", "target")
        sctid_col = cols.get("sctid")
        tag = add.get("source_tag") or add.get("id") or "addition"
        update = bool(add.get("ruling_updated_only"))
        with csv_path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                en = (r.get(en_col) or "").strip()
                ko = (r.get(tgt_col) or "").strip()
                if not en or not ko:
                    continue
                if update:
                    ko = apply_ruling_updates(ko)
                sctid = (r.get(sctid_col) or "").strip() if sctid_col else ""
                key = (en.lower(), ko, tag, sctid)
                if key in seen:
                    continue
                seen.add(key)
                new = {k: "" for k in fields}
                new.update({"EN": en, "KO": ko, "source": tag, "sctid": sctid})
                kept.append(new)
                added += 1
        add_ids.append(str(add.get("id")))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(kept)

    metrics: dict[str, float] = {
        "rows_in": float(n_raw),
        "rows_out": float(len(kept)),
        "rows_dropped": float(n_raw - (len(kept) - added)),
        "rows_added": float(added),
    }
    for rid, n in counts.items():
        metrics[f"matched_{rid}".replace("-", "_")] = float(n)

    metrics["additions_included"] = float(bool(include_additions))
    msg = (f"{n_raw:,} -> {len(kept):,} rows "
           f"(dropped {int(metrics['rows_dropped']):,}, added {added:,}) "
           f"via {len(active)} active rule(s)"
           + (f"; {len(disabled)} documented-but-disabled" if disabled else "")
           + f"; rules@{rules_digest(rules_path)}")
    return FunctionResult(ok=True, outputs={"pool": str(out)},
                          metrics=metrics, message=msg)
