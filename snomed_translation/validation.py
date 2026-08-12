"""Output validation: check the translations we are about to ship.

The hard-rules file already had two consumers — the PROMPT (rules injected
verbatim via ``frozen_block``) and the OPTIMISER (violations penalised in the
GEPA metric). Nothing checked the OUTPUT. So a ruling could sit in the prompt,
be enforced during optimisation, and still ship broken: the 5,012-term
production deliverable shipped 42 rows with the contrast modifier out of
position, 4 with the deprecated ``x선`` form and 3 with raw RF2 caret markup,
every one of them covered by a rule we had already written down.

These nodes close that loop. One rule definition, three consumers.

``validate_translations``  — rule violations + output hygiene over a
                             translations dataset, split blocker/warning.
``hierarchy_consistency``  — SNOMED is-a consistency: where an ancestor's
                             English term is contained in a descendant's, the
                             ancestor's Korean should be reused. Doubles as a
                             wrong-referent detector: it is what surfaced
                             "sacrum" rendered as 엉덩뼈 (ilium) while the
                             same concept's contrast-free sibling was correct.
"""
from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pipelines.context import RunContext
from pipelines.functions import FunctionResult

from snomed_translation.hard_rules import find_violations, load_hard_rules
from snomed_translation.scoring import norm_text

log = logging.getLogger(__name__)

IS_A = "116680003"

# Output hygiene that a forbidden-substring rule cannot express.
LATIN_RUN = re.compile(r"[A-Za-z]{4,}")
REPEATED_TOKEN = re.compile(r"\b(\S+)\s+\1\b")


def _dataset_path(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("path") or value.get("dataset") or value.get("csv")
    return value if isinstance(value, str) else None


def _hygiene(en: str, ko: str) -> list[tuple[str, str, str]]:
    """(check_id, severity, message) for structural defects in one output."""
    out: list[tuple[str, str, str]] = []
    if not ko.strip():
        out.append(("empty-output", "blocker", "translation is empty"))
        return out
    if ko.strip().startswith("ERROR"):
        out.append(("error-output", "blocker", "translation is an ERROR marker"))
        return out
    m = REPEATED_TOKEN.search(ko)
    if m:
        out.append(("repeated-token", "blocker",
                    f"token {m.group(1)!r} repeated adjacently"))
    # Latin script is legitimate for eponyms/gene symbols/isotopes, so only
    # flag a Latin run that was NOT carried over from the source term.
    for run in LATIN_RUN.findall(ko):
        if run.lower() not in en.lower():
            out.append(("untranslated-latin", "blocker",
                        f"Latin run {run!r} absent from the source term"))
            break
    return out


def validate_translations(ctx: RunContext, inputs: dict[str, Any],
                          params: dict[str, Any]) -> FunctionResult:
    """Validate a translations dataset against the hard rules + hygiene checks."""
    tpath = _dataset_path(inputs.get("translations"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False,
                              message="validate_translations: no `translations` wired")
    rules_file = params.get("rules_file")
    # Every enabled rule, enforced or not: `enforce` is the optimiser's switch,
    # `severity` is the validator's. load_hard_rules already drops enabled:false
    # rules, which is the only "do not look at this" signal.
    rules = load_hard_rules(rules_file) if rules_file else []
    en_col = str(params.get("en_col") or "preferred_term")
    ko_col = str(params.get("ko_col") or "translation")
    id_col = str(params.get("id_col") or "sctid")
    fail_on_blocker = bool(params.get("fail_on_blocker", False))

    findings: list[dict] = []
    n = 0
    with Path(tpath).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            en = (row.get(en_col) or "").strip()
            ko = (row.get(ko_col) or "").strip()
            sid = (row.get(id_col) or "").strip()
            n += 1
            for cid, sev, msg in _hygiene(en, ko):
                findings.append({"sctid": sid, "english": en, "korean": ko,
                                 "check": cid, "severity": sev, "message": msg})
            # require_enforce=False: the validator checks every rule. `enforce`
            # is the optimiser's switch (does GEPA pay a penalty), `severity`
            # is ours (does this block shipping) — see find_violations.
            for rule, msg in find_violations(ko, rules, require_enforce=False,
                                             source=en):
                findings.append({"sctid": sid, "english": en, "korean": ko,
                                 "check": rule.id, "severity": rule.severity,
                                 "message": msg})

    tag = str(params.get("output_tag") or "").strip()
    out = Path(ctx.log_dir) / (f"validation_findings{'_' + tag if tag else ''}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sctid", "english", "korean", "check",
                                          "severity", "message"])
        w.writeheader()
        w.writerows(findings)

    blockers = [f for f in findings if f["severity"] == "blocker"]
    warnings = [f for f in findings if f["severity"] != "blocker"]
    by_check: dict[str, int] = defaultdict(int)
    for f in findings:
        by_check[f["check"]] += 1
    metrics = {"n_rows": float(n), "n_findings": float(len(findings)),
               "n_blockers": float(len(blockers)),
               "n_warnings": float(len(warnings)),
               "n_rows_with_blocker": float(len({f["sctid"] for f in blockers})),
               "blocker_rate_pct": round(
                   100.0 * len({f["sctid"] for f in blockers}) / n, 3) if n else 0.0}
    for check, count in by_check.items():
        metrics[f"check_{check}".replace("-", "_")] = float(count)

    msg = (f"{len(blockers)} blocker(s) across "
           f"{len({f['sctid'] for f in blockers})} rows, {len(warnings)} warning(s) "
           f"over {n} translations"
           + (f"; top: {', '.join(k for k, _ in sorted(by_check.items(), key=lambda x: -x[1])[:3])}"
              if by_check else "; clean"))
    ok = not (fail_on_blocker and blockers)
    if not ok:
        msg = "GATE FAILED — " + msg
    return FunctionResult(ok=ok, outputs={"findings": str(out)},
                          metrics=metrics, message=msg)


def _load_isa_parents(rf2_relationship_file: str, wanted: set[str]
                      ) -> dict[str, set[str]]:
    """child -> {direct parents}, restricted to active is-a rows."""
    parents: dict[str, set[str]] = defaultdict(set)
    with Path(rf2_relationship_file).open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("active") != "1" or row.get("typeId") != IS_A:
                continue
            src = row.get("sourceId", "")
            if src in wanted:
                parents[src].add(row.get("destinationId", ""))
    return parents


def hierarchy_consistency(ctx: RunContext, inputs: dict[str, Any],
                          params: dict[str, Any]) -> FunctionResult:
    """Flag descendants that fail to reuse an ancestor's Korean rendering.

    Only fires where the ancestor's ENGLISH term is contained in the
    descendant's — i.e. the descendant genuinely restates the ancestor's
    concept and should restate its translation. Spacing is ignored (the SME
    rules spacing is never itself an error).
    """
    tpath = _dataset_path(inputs.get("translations"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False,
                              message="hierarchy_consistency: no `translations` wired")
    rel_file = params.get("rf2_relationship_file")
    if not rel_file or not Path(rel_file).exists():
        return FunctionResult(
            ok=False, message=f"hierarchy_consistency: rf2_relationship_file "
                              f"not found: {rel_file}")
    en_col = str(params.get("en_col") or "preferred_term")
    ko_col = str(params.get("ko_col") or "translation")
    max_depth = int(params.get("max_depth") or 4)

    rows: dict[str, dict] = {}
    with Path(tpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = (r.get("sctid") or "").strip()
            if sid:
                rows[sid] = {"en": (r.get(en_col) or "").strip(),
                             "ko": (r.get(ko_col) or "").strip()}
    parents = _load_isa_parents(str(rel_file), set(rows))

    # Walk up to `max_depth` ancestors, keeping only those inside this batch.
    findings: list[dict] = []
    n_pairs = 0
    for sid, rec in rows.items():
        seen: set[str] = set()
        frontier = set(parents.get(sid, ()))
        for _ in range(max_depth):
            if not frontier:
                break
            nxt: set[str] = set()
            for anc in frontier:
                if anc in seen:
                    continue
                seen.add(anc)
                nxt |= set(parents.get(anc, ()))
                arec = rows.get(anc)
                if not arec or not arec["en"] or not arec["ko"]:
                    continue
                # The descendant must genuinely restate the ancestor's term.
                if arec["en"].lower() not in rec["en"].lower():
                    continue
                n_pairs += 1
                if norm_text(arec["ko"]) not in norm_text(rec["ko"]):
                    findings.append({
                        "sctid": sid, "english": rec["en"], "korean": rec["ko"],
                        "ancestor_sctid": anc, "ancestor_english": arec["en"],
                        "ancestor_korean": arec["ko"],
                        "message": "ancestor rendering not reused",
                    })
            frontier = nxt

    # Namespaced: a flow may contain two instances of this node (detect +
    # recheck), and an unqualified filename silently overwrites the first.
    tag = str(params.get("output_tag") or "").strip()
    out = Path(ctx.log_dir) / (f"hierarchy_consistency{'_' + tag if tag else ''}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sctid", "english", "korean",
                                          "ancestor_sctid", "ancestor_english",
                                          "ancestor_korean", "message"])
        w.writeheader()
        w.writerows(findings)

    metrics = {"n_rows": float(len(rows)),
               "n_containment_pairs": float(n_pairs),
               "n_inconsistent": float(len(findings)),
               "inconsistency_rate_pct": round(
                   100.0 * len(findings) / n_pairs, 2) if n_pairs else 0.0,
               "n_rows_flagged": float(len({f["sctid"] for f in findings}))}
    msg = (f"{len(findings)}/{n_pairs} containment pairs reuse no ancestor "
           f"rendering ({metrics['inconsistency_rate_pct']}%), across "
           f"{int(metrics['n_rows_flagged'])} rows")
    return FunctionResult(ok=True, outputs={"findings": str(out)},
                          metrics=metrics, message=msg)


def _harmonise(descendant_ko: str, ancestor_ko: str) -> str | None:
    """Rewrite a descendant so it reuses the ancestor's rendering, or None.

    Korean is head-final and the ancestor IS the head concept, so a descendant
    is normally ``[extra modifiers] + [ancestor rendering]``. The substitution
    keeps the descendant's own tokens (its added laterality/contrast/site
    modifiers) in their original order and appends the ancestor's rendering
    verbatim. Purely mechanical — no model, so it cannot hallucinate; it can
    only be wrong in ways a rule check or a human can see.

    Returns None when there is nothing to do (the descendant contributes no
    tokens of its own, or the result would equal the input).
    """
    anc_tokens = ancestor_ko.split()
    anc_norm = {norm_text(t) for t in anc_tokens if t.strip()}
    extra = [t for t in descendant_ko.split() if norm_text(t) not in anc_norm]
    candidate = " ".join([*extra, *anc_tokens]).strip()
    if not candidate or norm_text(candidate) == norm_text(descendant_ko):
        return None
    return candidate


def hierarchy_harmonise(ctx: RunContext, inputs: dict[str, Any],
                        params: dict[str, Any]) -> FunctionResult:
    """Apply deterministic ancestor substitution to inconsistent descendants.

    Consumes ``hierarchy_consistency`` findings and rewrites each flagged
    descendant to reuse its ancestor's rendering. Emits the full translations
    dataset with substitutions applied, plus a before/after audit, so the
    result can be validated and scored exactly like any other translation set.

    This is the cheap half of the hierarchy proposal: it buys consistency with
    no model in the loop, versus top-down context injection which serialises
    the pipeline and lets one bad ancestor contaminate its whole subtree.
    """
    tpath = _dataset_path(inputs.get("translations"))
    fpath = _dataset_path(inputs.get("findings"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False, message="hierarchy_harmonise: no `translations`")
    if not fpath or not Path(fpath).exists():
        return FunctionResult(ok=False, message="hierarchy_harmonise: no `findings`")
    ko_col = str(params.get("ko_col") or "translation")

    # One substitution per descendant: the DEEPEST (longest English) ancestor,
    # which is the most specific shared concept.
    best: dict[str, dict] = {}
    with Path(fpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["sctid"]
            prev = best.get(sid)
            if prev is None or len(r["ancestor_english"]) > len(prev["ancestor_english"]):
                best[sid] = r

    rows: list[dict] = []
    audit: list[dict] = []
    changed = skipped = 0
    with Path(tpath).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        for row in reader:
            sid = (row.get("sctid") or "").strip()
            hit = best.get(sid)
            if hit:
                new = _harmonise(row.get(ko_col, ""), hit["ancestor_korean"])
                if new:
                    audit.append({"sctid": sid, "english": hit["english"],
                                  "before": row.get(ko_col, ""), "after": new,
                                  "ancestor_korean": hit["ancestor_korean"]})
                    row[ko_col] = new
                    changed += 1
                else:
                    skipped += 1
            rows.append(row)

    out_dir = Path(ctx.artifacts_dir() or ctx.log_dir)
    out = out_dir / f"harmonised_{params.get('output_tag') or 'run'}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    aud = Path(ctx.log_dir) / "harmonisation_audit.csv"
    with aud.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sctid", "english", "before", "after",
                                          "ancestor_korean"])
        w.writeheader()
        w.writerows(audit)

    metrics = {"n_rows": float(len(rows)), "n_flagged": float(len(best)),
               "n_substituted": float(changed), "n_skipped": float(skipped),
               "substitution_rate_pct": round(
                   100.0 * changed / len(best), 2) if best else 0.0}
    return FunctionResult(ok=True,
                          outputs={"translations": str(out), "audit": str(aud)},
                          metrics=metrics,
                          message=f"substituted {changed}/{len(best)} flagged rows "
                                  f"({skipped} no-ops) over {len(rows)} translations")


def build_ancestor_context(ctx: RunContext, inputs: dict[str, Any],
                           params: dict[str, Any]) -> FunctionResult:
    """Build the ancestor-context map, filtered so bad ancestors can't teach.

    An ancestor may condition a descendant's translation only if it is:
      1. UNANIMOUS  — its own samples agreed (``routed == kept``). Unanimous
         concepts score 57.7% exact vs 14.6% when samples disagree.
      2. VALID      — it has no blocker-severity finding from
         ``validate_translations``.

    (1) alone is not enough: unanimity is CONFIDENCE, not correctness. The
    malformed ancestor 439101006 ("X-ray tomography" -> 단순 촬영 단층 촬영,
    a repeated-modality blocker) is unanimous and has 19 in-batch descendants,
    so it passes a confidence gate and would have been allowed to teach them.

      3. SELF-CONSISTENT — not itself flagged by hierarchy_consistency, and
         carrying no repeated content token.

    (3) exists because the TEACHING bar must be stricter than the SHIPPING
    bar: an ancestor's defects multiply across its descendants, so a rendering
    good enough to ship is not automatically good enough to teach. It is also
    what actually catches 439101006 ("X-ray tomography" -> 단순 촬영 단층 촬영,
    19 in-batch descendants): that string repeats 촬영 NON-adjacently, so the
    shipping-side repeated-token check misses it, and a blanket repeated-token
    rule cannot be promoted to a blocker because it fires on 7.7% of rows,
    many legitimately (유방 촬영술 유도하 … 유방; 피부 경유 … 혈관 경유).

    A poisoning probe found the model adopts a FLUENT but wrong ancestor 0/25
    times, so this filter is not the main line of defence — it covers the
    malformed-ancestor distribution the probe did not test.
    """
    from collections import Counter as _Counter
    import json as _json

    fpath = _dataset_path(inputs.get("findings"))          # hierarchy_consistency
    tpath = _dataset_path(inputs.get("translations"))      # for routed/unanimity
    vpath = _dataset_path(inputs.get("validation"))        # blocker findings
    if not fpath or not Path(fpath).exists():
        return FunctionResult(ok=False, message="build_ancestor_context: no `findings`")
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False, message="build_ancestor_context: no `translations`")

    require_unanimous = bool(params.get("require_unanimous", True))
    out_path = params.get("output_json")
    if not out_path:
        out_path = str(Path(ctx.log_dir) / "ancestor_context.json")

    rows = {}
    with Path(tpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[(r.get("sctid") or "").strip()] = r
    blocked: set[str] = set()
    if vpath and Path(vpath).exists():
        with Path(vpath).open(encoding="utf-8") as f:
            blocked = {r["sctid"] for r in csv.DictReader(f)
                       if r.get("severity") == "blocker"}

    strict = bool(params.get("strict_ancestor", True))
    self_flagged = set()
    with Path(fpath).open(encoding="utf-8") as f:
        self_flagged = {r["sctid"] for r in csv.DictReader(f)}

    def _repeats(text: str) -> bool:
        counts = _Counter(t for t in text.split() if len(t) > 1)
        return any(n > 1 for n in counts.values())

    ctx_map: dict[str, dict] = {}
    skipped = {"not_unanimous": 0, "blocker": 0, "missing": 0,
               "self_inconsistent": 0, "repeated_token": 0}
    with Path(fpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            anc_id = (r.get("ancestor_sctid") or "").strip()
            anc = rows.get(anc_id)
            if anc is None:
                skipped["missing"] += 1
                continue
            if anc_id in blocked:
                skipped["blocker"] += 1
                continue
            if require_unanimous and (anc.get("routed") or "kept") != "kept":
                skipped["not_unanimous"] += 1
                continue
            if strict and anc_id in self_flagged:
                skipped["self_inconsistent"] += 1
                continue
            if strict and _repeats(r.get("ancestor_korean", "")):
                skipped["repeated_token"] += 1
                continue
            sid = r["sctid"]
            prev = ctx_map.get(sid)
            # deepest (longest English) ancestor = most specific shared concept
            if prev is None or len(r["ancestor_english"]) > len(prev["ancestor_english"]):
                ctx_map[sid] = {"ancestor_english": r["ancestor_english"],
                                "ancestor_korean": r["ancestor_korean"]}

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(_json.dumps(ctx_map, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    # The work-list: exactly the concepts that will be re-translated. Emitted
    # here, from the same pass that decided admission, so the repair subset is
    # derived by a tracked run rather than by a side script that could drift
    # out of step with the filter.
    terms_path = params.get("output_terms_csv")
    if terms_path:
        Path(terms_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(terms_path).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sctid", "preferred_term"])
            w.writeheader()
            for sid in ctx_map:
                w.writerow({"sctid": sid,
                            "preferred_term": (rows.get(sid, {})
                                               .get("preferred_term") or "")})

    metrics = {"n_context": float(len(ctx_map)),
               "skipped_not_unanimous": float(skipped["not_unanimous"]),
               "skipped_blocker": float(skipped["blocker"]),
               "skipped_self_inconsistent": float(skipped["self_inconsistent"]),
               "skipped_repeated_token": float(skipped["repeated_token"]),
               "skipped_missing_ancestor": float(skipped["missing"])}
    return FunctionResult(
        ok=True, outputs={"context": str(out_path)}, metrics=metrics,
        message=(f"{len(ctx_map)} descendants may draw on an ancestor "
                 f"(skipped {skipped['not_unanimous']} non-unanimous, "
                 f"{skipped['blocker']} blocker-violating, "
                 f"{skipped['self_inconsistent']} self-inconsistent, "
                 f"{skipped['repeated_token']} with a repeated token, "
                 f"{skipped['missing']} absent)"))


def splice_translations(ctx: RunContext, inputs: dict[str, Any],
                        params: dict[str, Any]) -> FunctionResult:
    """Overlay a patch translation set onto a base set, keyed by sctid.

    Exists so a targeted repair can be measured IN CONTEXT. A repair run over
    a subset scores its own subset, and for anything relational — hierarchy
    consistency above all — that number is meaningless: run over the 342
    ancestor-repair rows alone, only 31 of the batch's 1,774 containment pairs
    survive, because a row's ancestor is usually outside the subset. The
    repair must be spliced back into the full batch before the detector can
    say whether it helped.

    Rows present only in the patch are ignored, not appended: a patch is an
    overlay on a fixed deliverable, and a patch-only sctid means the two sets
    disagree about the population, which is a bug worth surfacing rather than
    silently widening the batch.
    """
    bpath = _dataset_path(inputs.get("base"))
    ppath = _dataset_path(inputs.get("patch"))
    if not bpath or not Path(bpath).exists():
        return FunctionResult(ok=False, message="splice_translations: no `base`")
    if not ppath or not Path(ppath).exists():
        return FunctionResult(ok=False, message="splice_translations: no `patch`")

    col = str(params.get("ko_col") or "translation")
    tag = str(params.get("output_tag") or "spliced")

    with Path(ppath).open(encoding="utf-8") as f:
        patch = {(r.get("sctid") or "").strip(): r for r in csv.DictReader(f)}

    # Optional allow-list: apply only the patch rows that a prior pass showed
    # to be beneficial. Without it every changed row ships, including those
    # that changed the text without fixing anything — 95 of the ancestor
    # repair's 233 changes cleared no flag, so they carry the intervention's
    # regression risk (3 of 16 worsened on gold) with no measured upside.
    rpath = _dataset_path(inputs.get("restrict"))
    n_restricted = 0
    if rpath and Path(rpath).exists():
        with Path(rpath).open(encoding="utf-8") as f:
            allow = {(r.get("sctid") or "").strip() for r in csv.DictReader(f)}
        n_restricted = len(patch) - len(allow & set(patch))
        patch = {k: v for k, v in patch.items() if k in allow}

    # Safety property of splicing, independent of any allow-list: a patch may
    # never INTRODUCE a blocker the base row did not already have. The repair
    # still emits 위팔/엉덩이 on its own even after the offending ancestors were
    # excluded, so filtering the teaching signal is not sufficient — the
    # adoption step has to refuse the change too. Pre-existing violations are
    # left alone: fixing those is a separate job, and withholding a patch row
    # because the BASE was already broken would just freeze the defect in.
    rules_file = params.get("rules_file")
    blocker_rules = [r for r in load_hard_rules(rules_file)
                     if r.severity == "blocker"] if rules_file else []
    n_refused = 0
    if blocker_rules:
        # The English matters: _hygiene only calls a Latin run untranslated if
        # it is ABSENT from the source term, so eponyms and forms like "A-mode"
        # stay legitimate. Passing "" here would condemn every one of them.
        def _blockers(text: str, en: str) -> set[str]:
            found = {r.id for r, _ in find_violations(text, blocker_rules,
                                                      require_enforce=False,
                                                      source=en)}
            return found | {cid for cid, sev, _ in _hygiene(en, text)
                            if sev == "blocker"}

    out_path = Path(ctx.artifacts_dir() or ".") / f"translations_{tag}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_rows = n_applied = n_identical = 0
    seen: set[str] = set()
    with Path(bpath).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        if "spliced" not in fields:
            fields.append("spliced")
        with out_path.open("w", encoding="utf-8", newline="") as g:
            w = csv.DictWriter(g, fieldnames=fields)
            w.writeheader()
            for row in reader:
                n_rows += 1
                sid = (row.get("sctid") or "").strip()
                seen.add(sid)
                p = patch.get(sid)
                row["spliced"] = ""
                if p is not None and (p.get(col) or "").strip():
                    new_text = (p[col] or "").strip()
                    old_text = (row.get(col) or "").strip()
                    if blocker_rules and new_text != old_text:
                        en = (row.get("preferred_term") or "").strip()
                        introduced = _blockers(new_text, en) - _blockers(old_text, en)
                        if introduced:
                            n_refused += 1
                            log.warning("splice_translations: refusing %s — "
                                        "patch introduces %s: %r", sid,
                                        ",".join(sorted(introduced)), new_text)
                            w.writerow(row)
                            continue
                    if new_text == old_text:
                        n_identical += 1
                    else:
                        n_applied += 1
                    row[col] = p[col]
                    row["spliced"] = "1"
                w.writerow(row)

    orphans = sorted(set(patch) - seen)
    if orphans:
        log.warning("splice_translations: %d patch rows absent from base "
                    "(ignored): %s", len(orphans), ", ".join(orphans[:5]))

    return FunctionResult(
        ok=True,
        outputs={"translations": str(out_path), "dataset": str(out_path)},
        metrics={"n_rows": float(n_rows),
                 "n_patch": float(len(patch)),
                 "n_changed": float(n_applied),
                 "n_unchanged": float(n_identical),
                 "n_withheld_by_restrict": float(n_restricted),
                 "n_refused_new_blocker": float(n_refused),
                 "n_patch_orphans": float(len(orphans))},
        message=(f"{n_rows} rows, {n_applied} replaced by the patch "
                 f"({n_identical} patch rows identical to base, "
                 f"{n_restricted} withheld by the restrict list, "
                 f"{n_refused} refused for introducing a blocker, "
                 f"{len(orphans)} patch rows absent from base)"))


def diff_findings(ctx: RunContext, inputs: dict[str, Any],
                  params: dict[str, Any]) -> FunctionResult:
    """Split a before/after findings pair into what was FIXED and what REGRESSED.

    A net count hides the trade. The ancestor repair moved hierarchy flags
    580 -> 442, but "net -138" is equally consistent with 138 clean fixes and
    with 200 fixes bought at the cost of 62 new breaks. Only the row-level
    difference distinguishes them, and the second case is not shippable.

    ``fixed`` is also the selection signal for a second, restricted splice:
    a patch row that changed the text without clearing a flag bought nothing
    measurable and is pure regression risk, so it should not ship.
    """
    bpath = _dataset_path(inputs.get("before"))
    apath = _dataset_path(inputs.get("after"))
    if not bpath or not Path(bpath).exists():
        return FunctionResult(ok=False, message="diff_findings: no `before`")
    if not apath or not Path(apath).exists():
        return FunctionResult(ok=False, message="diff_findings: no `after`")

    # Key on (sctid, check), not sctid alone. A row that swaps blocker A for
    # blocker B is neither fixed nor regressed under a bare sctid key — it is
    # invisible churn, and for validate_translations findings (several checks
    # per row) that is the common case, not a corner case.
    def keys(p: str) -> set[tuple[str, str]]:
        with Path(p).open(encoding="utf-8") as f:
            return {((r.get("sctid") or "").strip(),
                     (r.get("check") or r.get("issue") or "").strip())
                    for r in csv.DictReader(f)}

    before_k, after_k = keys(bpath), keys(apath)
    # Row-level: a row counts as fixed only when ALL its findings cleared, so
    # the allow-list never adopts a change that merely traded one defect for
    # another.
    before_rows = {s for s, _ in before_k}
    after_rows = {s for s, _ in after_k}
    fixed, regressed = sorted(before_rows - after_rows), sorted(after_rows - before_rows)
    before, after = before_rows, after_rows
    n_traded = len({s for s, _ in (before_k - after_k)} &
                   {s for s, _ in (after_k - before_k)})

    tag = str(params.get("output_tag") or "diff")
    out_dir = Path(ctx.artifacts_dir() or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    fixed_path = out_dir / f"fixed_{tag}.csv"
    regressed_path = out_dir / f"regressed_{tag}.csv"
    for path, rows in ((fixed_path, fixed), (regressed_path, regressed)):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sctid"])
            w.writeheader()
            for sid in rows:
                w.writerow({"sctid": sid})

    return FunctionResult(
        ok=True,
        outputs={"fixed": str(fixed_path), "regressed": str(regressed_path),
                 "dataset": str(fixed_path)},
        metrics={"n_before": float(len(before)), "n_after": float(len(after)),
                 "n_fixed": float(len(fixed)), "n_regressed": float(len(regressed)),
                 "n_traded": float(n_traded),
                 "n_findings_before": float(len(before_k)),
                 "n_findings_after": float(len(after_k)),
                 "n_net": float(len(after) - len(before))},
        message=(f"{len(before)} -> {len(after)} flagged rows: {len(fixed)} fixed, "
                 f"{len(regressed)} newly broken, {n_traded} traded one finding "
                 f"for another (net {len(after) - len(before):+d})"))


# Severity order for aggregation: higher wins when a row trips several checks.
_SEVERITY_RANK = {"blocker": 2, "warning": 1}


def qa_gate(ctx: RunContext, inputs: dict[str, Any],
            params: dict[str, Any]) -> FunctionResult:
    """Aggregate every detector's findings into one verdict + one worklist.

    Replaces "run four detectors and eyeball four CSVs". Two outputs:

    ``verdict``  — metrics, chiefly ``n_blockers`` and ``shippable`` (1.0/0.0),
                   suitable for wiring to the research app's project gate.
    ``worklist`` — one row per defective concept, most severe first, carrying
                   every check that fired. This is what a human triages and
                   what packaging sorts by, so review effort goes to the worst
                   rows rather than to whatever a CSV happened to list first.

    Findings arrive on numbered ports (``findings1``..``findings6``) because a
    flow graph has no variadic input. Any findings dataset works as long as it
    carries ``sctid`` and ``check``; ``severity`` defaults to warning so a
    detector that predates the severity field still aggregates sensibly.

    This node is also the reason the repair loop is trustworthy. A repair is
    optimised against ONE detector, so accepting it on that detector's own
    evidence is circular — the ancestor repair improved every consistency
    metric while reversing two translations the SME had explicitly ruled on.
    Running the whole family here makes acceptance Pareto: a change must clear
    its target defect AND introduce nothing new on any other axis.
    """
    rows: dict[str, dict] = {}
    per_check: dict[str, int] = {}
    n_sources = 0

    for port in sorted(k for k in inputs if k.startswith("findings")):
        path = _dataset_path(inputs.get(port))
        if not path or not Path(path).exists():
            continue
        n_sources += 1
        with Path(path).open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sid = (r.get("sctid") or "").strip()
                if not sid:
                    continue
                # THE FINDINGS CONTRACT. Two shapes exist in the detector
                # family and both are legitimate:
                #   subset  — one row per finding (validate_translations,
                #             hierarchy_consistency)
                #   scored  — every row, with a `flag` column (contrast_
                #             fidelity_detect, transliteration_detect)
                # Reading the second shape as the first counts a clean batch
                # as wholly defective: the gate's first run reported "5012
                # defective rows, 4977 warnings" from 4 real contrast flags
                # and 1 transliteration flag. Honour `flag` when present.
                if "flag" in r:
                    val = (r.get("flag") or "").strip().lower()
                    if val in ("", "0", "false", "no", "n"):
                        continue
                # `issue` is the scored shape's reason column; fall back to the
                # port name so an unlabelled detector is still attributable.
                check = (r.get("check") or r.get("issue") or port).strip() or port
                sev = (r.get("severity") or "warning").strip().lower()
                per_check[check] = per_check.get(check, 0) + 1
                row = rows.setdefault(sid, {
                    "sctid": sid,
                    "english": r.get("english") or r.get("preferred_term") or "",
                    "korean": r.get("korean") or r.get("translation") or "",
                    "checks": [], "max_severity": "warning", "n_checks": 0,
                })
                if check not in row["checks"]:
                    row["checks"].append(check)
                row["n_checks"] = len(row["checks"])
                if _SEVERITY_RANK.get(sev, 1) > _SEVERITY_RANK.get(row["max_severity"], 1):
                    row["max_severity"] = sev
                # Backfill text from whichever detector carries it.
                for key, src in (("english", ("english", "preferred_term")),
                                 ("korean", ("korean", "translation"))):
                    if not row[key]:
                        for c in src:
                            if r.get(c):
                                row[key] = r[c]
                                break

    ordered = sorted(
        rows.values(),
        key=lambda r: (-_SEVERITY_RANK.get(r["max_severity"], 1),
                       -r["n_checks"], r["sctid"]))
    for i, r in enumerate(ordered, 1):
        r["review_priority"] = i
        r["checks"] = ";".join(r["checks"])

    tag = str(params.get("output_tag") or "qa").strip()
    out = Path(ctx.artifacts_dir() or ctx.log_dir) / f"qa_worklist_{tag}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["review_priority", "sctid", "english", "korean",
              "max_severity", "n_checks", "checks"]
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in ordered:
            w.writerow({k: r[k] for k in fields})

    n_blockers = sum(1 for r in ordered if r["max_severity"] == "blocker")
    n_warnings = len(ordered) - n_blockers
    max_blockers = int(params.get("max_blockers") or 0)
    shippable = n_blockers <= max_blockers
    fail_if_not = bool(params.get("fail_if_not_shippable", False))

    metrics = {
        "n_defective_rows": float(len(ordered)),
        "n_blocker_rows": float(n_blockers),
        "n_warning_rows": float(n_warnings),
        "n_detectors": float(n_sources),
        "shippable": 1.0 if shippable else 0.0,
    }
    metrics.update({f"check_{k.replace('-', '_')}": float(v)
                    for k, v in per_check.items()})

    verdict = ("SHIPPABLE" if shippable else
               f"NOT SHIPPABLE — {n_blockers} blocker row(s) > {max_blockers} allowed")
    return FunctionResult(
        ok=(shippable or not fail_if_not),
        outputs={"worklist": str(out), "dataset": str(out)},
        metrics=metrics,
        message=(f"{verdict}; {len(ordered)} defective row(s) over "
                 f"{n_sources} detector(s): {n_blockers} blocker, "
                 f"{n_warnings} warning"))


def build_rule_repair_context(ctx: RunContext, inputs: dict[str, Any],
                              params: dict[str, Any]) -> FunctionResult:
    """Turn rule violations into per-concept repair guidance + a work-list.

    The counterpart to ``build_ancestor_context``, and the reason the repair
    loop is general rather than ancestor-specific: it emits the SAME context
    map shape the translate stage already injects, so a rules-based defect is
    repaired by the existing cascade, verified by the existing splice/diff, and
    accepted by the existing gate. No new repair machinery.

    Guidance names what is wrong and, where the rule declares a ``canonical``
    form, what to use instead. It deliberately does NOT hand over a finished
    string: deterministic whole-phrase substitution was measured and lost
    (7/22 -> 1/22), and two of these defects are word-order faults that a
    term swap cannot fix (유방 유방 촬영술 유도하 생검).

    Only blocker-severity findings are repaired by default. Warnings are review
    priorities, not errors, and re-translating on a warning would churn rows
    that are probably fine.
    """
    fpath = _dataset_path(inputs.get("findings"))
    tpath = _dataset_path(inputs.get("translations"))
    if not fpath or not Path(fpath).exists():
        return FunctionResult(ok=False, message="build_rule_repair_context: no `findings`")

    rules = {r.id: r for r in load_hard_rules(params.get("rules_file"))}
    severities = {s.strip().lower() for s in
                  str(params.get("severities") or "blocker").split(",") if s.strip()}

    per_row: dict[str, list[str]] = defaultdict(list)
    english: dict[str, str] = {}
    with Path(fpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("severity") or "warning").strip().lower() not in severities:
                continue
            sid = (r.get("sctid") or "").strip()
            if not sid:
                continue
            english.setdefault(sid, (r.get("english") or "").strip())
            check = (r.get("check") or "").strip()
            rule = rules.get(check)
            if rule is not None and rule.description:
                line = " ".join(rule.description.split())
            else:
                line = (r.get("message") or check or "").strip()
            if rule is not None and rule.canonical:
                line += f" Use {' or '.join(rule.canonical)} instead."
            if line and line not in per_row[sid]:
                per_row[sid].append(line)

    ctx_map = {
        sid: {"guidance": (
            "A previous translation of this term was REJECTED in review. "
            + " ".join(lines)
            + " Produce a corrected translation of the term below; keep "
              "everything that was already right and change only what the "
              "objection requires.")}
        for sid, lines in per_row.items()
    }

    out_json = params.get("output_json") or str(
        Path(ctx.artifacts_dir() or ctx.log_dir) / "rule_repair_context.json")
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(
        __import__("json").dumps(ctx_map, ensure_ascii=False, indent=1),
        encoding="utf-8")

    # Work-list in the shape the translate datasource expects. Prefer the
    # English from the translations dataset when wired, since a findings row
    # only carries whatever its detector happened to record.
    if tpath and Path(tpath).exists():
        with Path(tpath).open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sid = (r.get("sctid") or "").strip()
                if sid in ctx_map and (r.get("preferred_term") or "").strip():
                    english[sid] = r["preferred_term"].strip()

    terms_csv = params.get("output_terms_csv")
    if terms_csv:
        Path(terms_csv).parent.mkdir(parents=True, exist_ok=True)
        with Path(terms_csv).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sctid", "preferred_term"])
            w.writeheader()
            for sid in ctx_map:
                w.writerow({"sctid": sid, "preferred_term": english.get(sid, "")})

    by_check: dict[str, int] = defaultdict(int)
    for lines in per_row.values():
        by_check[str(len(lines))] += 1
    return FunctionResult(
        ok=True,
        outputs={"context": str(out_json),
                 "terms": str(terms_csv) if terms_csv else str(out_json)},
        metrics={"n_rows_to_repair": float(len(ctx_map)),
                 "n_multi_objection": float(sum(
                     1 for v in per_row.values() if len(v) > 1))},
        message=(f"{len(ctx_map)} row(s) need repair "
                 f"({sum(1 for v in per_row.values() if len(v) > 1)} with more "
                 f"than one objection)"))


def rule_substitute(ctx: RunContext, inputs: dict[str, Any],
                    params: dict[str, Any]) -> FunctionResult:
    """Repair rule violations by MINIMAL substitution: forbidden -> canonical.

    The conservative counterpart to re-translation, and the right tool whenever
    a rule's objection is a term choice rather than a structure. Re-translating
    hands the model licence to rewrite the whole string, and it takes it: asked
    to fix 엉덩이 in a DEXA term it returned 고관절 양방사선 골밀도검사, silently
    replacing 이중 에너지 X선 흡수 계측법 and breaking consistency with four
    sibling rows; asked to fix caret markup in a SPECT term it dropped 방출, so
    "single photon EMISSION CT" stopped saying emission. Both cleared the rule
    that prompted them, because no detector watches the rest of the string.

    A substitution cannot do that. It touches exactly the offending span, so
    the diff is auditable and everything else is preserved by construction.
    Rows whose rule has no ``canonical`` form, or whose defect is structural
    (word order, a repeated token), are left untouched and reported in
    ``n_unfixable`` — they are what re-translation is FOR.
    """
    tpath = _dataset_path(inputs.get("translations"))
    fpath = _dataset_path(inputs.get("findings"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False, message="rule_substitute: no `translations`")
    if not fpath or not Path(fpath).exists():
        return FunctionResult(ok=False, message="rule_substitute: no `findings`")

    rules = {r.id: r for r in load_hard_rules(params.get("rules_file"))}
    extra = params.get("substitutions") or {}
    ko_col = str(params.get("ko_col") or "translation")

    targets: dict[str, set[str]] = defaultdict(set)
    with Path(fpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("severity") or "").strip().lower() != "blocker":
                continue
            sid = (r.get("sctid") or "").strip()
            if sid:
                targets[sid].add((r.get("check") or "").strip())

    def substitute(text: str, checks: set[str]) -> tuple[str, list[str]]:
        applied: list[str] = []
        for check in sorted(checks):
            # Explicit regex substitutions first: they express transforms a
            # forbidden/canonical pair cannot, such as unwrapping RF2 carets.
            if check in extra:
                pat, repl = extra[check]
                new = re.sub(pat, repl, text)
                if new != text:
                    text, _ = new, applied.append(check)
                continue
            rule = rules.get(check)
            if rule is None or not rule.canonical:
                continue
            target = rule.canonical[0]
            new = text
            for bad in rule.forbidden:
                new = new.replace(bad, target)
            for pat in rule.forbidden_regex:
                new = re.sub(pat, target, new)
            if new != text:
                text, _ = new, applied.append(check)
        return text, applied

    out_path = Path(ctx.artifacts_dir() or ctx.log_dir) / (
        f"substituted_{params.get('output_tag') or 'patch'}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_fixed = 0
    unfixable: list[str] = []
    rows_out: list[dict] = []
    with Path(tpath).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        for row in reader:
            sid = (row.get("sctid") or "").strip()
            if sid not in targets:
                continue
            new, applied = substitute(row.get(ko_col) or "", targets[sid])
            if applied:
                row[ko_col] = new
                n_fixed += 1
                rows_out.append(row)
            else:
                unfixable.append(sid)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    return FunctionResult(
        ok=True,
        outputs={"translations": str(out_path), "dataset": str(out_path)},
        metrics={"n_targets": float(len(targets)), "n_fixed": float(n_fixed),
                 "n_unfixable": float(len(unfixable))},
        message=(f"{n_fixed}/{len(targets)} blocker row(s) repaired by minimal "
                 f"substitution; {len(unfixable)} need re-translation "
                 f"(structural, or no canonical form)"))
