#!/usr/bin/env python3
"""Analyse internal inconsistencies in KR imaging translations.

Runs four axes of analysis over the KR-imaging dataset
(build_kr_imaging_dataset.py) and, for each axis, identifies clusters where
the KR release uses multiple Korean renderings for what is logically the
same English-side element:

  Axis 1: body-site rendering  — procedures sharing a Procedure site attribute
                                 use different Korean forms of the site.
  Axis 2: modality rendering   — procedures sharing a Method attribute use
                                 different Korean modality tokens.
  Axis 3: suffix / action word — the terminal action morpheme (checkup /
                                 촬영 / 검사 / 술 / 영상 / etc.) varies within
                                 a single method group.
  Axis 4: contrast word order  — "with / without contrast" concepts vary
                                 between [contrast + site] and [site + contrast]
                                 in the Korean translation.

Outputs:
  data/analysis/imaging_inconsistencies/
    axis1_body_site.csv
    axis2_modality.csv
    axis3_suffix.csv
    axis4_contrast_order.csv
    clusters_for_llm.jsonl
    llm_verdicts.jsonl
  docs/imaging_inconsistencies_<date>.md
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from datetime import date

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
KR_BODY_SITES = ROOT_DIR / "data" / "korean" / "dictionaries" / "kr_body_sites.tsv"

SCOPES: dict[str, str] = {
    "imaging": "Imaging (procedure)",
    "procedure": "Procedure",
    "body_structure": "Body structure",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kr_inconsistencies")


# -- Known modality rendering variants (primary KR forms + common alternates) --
MODALITY_VARIANTS: dict[str, list[str]] = {
    # Method SCTID -> [Korean rendering candidates, ordered by specificity]
    "312251004": ["컴퓨터 단층 촬영", "컴퓨터단층촬영", "전산화 단층 촬영", "전산화단층촬영", "CT"],
    "312250003": ["자기 공명 영상", "자기공명영상", "자기 공명 촬영", "MRI"],
    "278292003": ["초음파 검사", "초음파 촬영", "초음파검사", "초음파촬영", "초음파"],
    "303563008": ["도플러 초음파 검사", "도플러 초음파 촬영", "도플러"],
    "44491008":  ["방사선 영상 촬영", "방사선 촬영", "방사선촬영", "X선 촬영", "X선촬영"],
    "168537006": ["일반 X선", "단순 X선", "일반 엑스레이", "X선"],
    "363680008": ["방사선 영상 촬영", "방사선 촬영", "방사선촬영", "X선 촬영"],
    "7659008":   ["투시", "형광 투시"],
    "118189007": ["방사성 핵종 영상", "방사성핵종 영상", "동위 원소 영상", "핵의학 영상"],
    "16635005":  ["조영", "조영상", "조영 촬영", "혈관 조영", "혈관조영"],
    "1112801006": ["에코카디오그래피", "심장 초음파 검사", "심장초음파검사"],
}
MODALITY_NAMES: dict[str, str] = {
    "312251004": "Computed tomography",
    "312250003": "Magnetic resonance imaging",
    "278292003": "Ultrasound imaging",
    "303563008": "Doppler ultrasound imaging",
    "44491008":  "Radiographic imaging (general)",
    "168537006": "Plain X-ray imaging",
    "363680008": "Radiographic imaging",
    "7659008":   "Fluoroscopy",
    "118189007": "Radionuclide imaging",
    "16635005":  "Contrast imaging",
    "1112801006": "Echocardiography",
}

# Common action-word terminals we want to discipline-check. Covers imaging
# and broader surgical / interventional procedure actions for Phase 2.
TERMINAL_TOKENS = {
    # Imaging
    "촬영", "영상", "검사", "조영", "조영상", "조영술", "촬영술", "측정",
    "스캔", "투시", "조영증강", "투시술",
    # Surgical / interventional
    "절제", "절제술", "절개", "절개술", "절단", "절단술", "봉합", "봉합술",
    "생검", "흡인", "배액", "삽입", "제거", "교체", "교환", "치환",
    "이식", "이식술", "연결", "연결술", "문합", "우회", "우회술",
    "재건", "복구", "성형", "성형술", "결찰", "소작", "소작술",
    "창냄술", "조성술", "형성술", "확장", "확장술", "세척",
    # Generic endings
    "술", "법", "요법", "치료", "교육", "상담",
}


def load_dataset(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def load_body_site_renderings() -> dict[str, dict]:
    """body-structure sctid -> {en, ko_preferred, ko_synonyms: [..]}"""
    # kr_body_sites.tsv keys are English FSNs, not SCTIDs. We need SCTID->forms.
    # Rebuild from KR descriptions + graph: already done in the dataset via
    # `site_direct_fsn`. But to get the site concept's OWN Korean forms we
    # need a parallel lookup from the KR description file.
    # Simplest: parse kr_body_sites.tsv and key by en (stripped of "(body structure)").
    data: dict[str, dict] = {}
    with KR_BODY_SITES.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            en = row["en"].strip()
            pref = row["ko_preferred"].strip()
            syns = [s.strip() for s in row["ko_synonyms"].split(";") if s.strip()]
            if en and pref:
                data[en] = {"ko_preferred": pref, "ko_synonyms": syns}
    return data


# ---------- Axis 1: body-site rendering ----------

def axis1_body_sites(rows: list[dict], site_forms: dict[str, dict]) -> list[dict]:
    """Group procedures by their primary body-site attribute target.

    For each group with ≥2 procedures, check which Korean rendering(s) of the
    body site are used. A "rendering" is detected by checking whether the
    body-structure concept's ko_preferred or any ko_synonym appears as a
    substring of the procedure's Korean translation.
    """
    # Group by site_direct_fsn (fallback through indirect, generic, finding).
    def site_fsn(r: dict) -> tuple[str, str]:
        for k in ("site_direct_fsn", "site_indirect_fsn", "site_generic_fsn", "finding_site_fsn"):
            if r.get(k):
                return (k, r[k])
        return ("", "")

    # Strip semantic tag to match kr_body_sites.tsv
    def strip_tag(fsn: str) -> str:
        return re.sub(r"\s*\([^)]+\)\s*$", "", fsn).strip()

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        kind, fsn = site_fsn(r)
        if not fsn:
            continue
        groups[fsn].append(r)

    findings: list[dict] = []
    for fsn, procs in groups.items():
        if len(procs) < 2:
            continue
        stripped = strip_tag(fsn)
        forms = site_forms.get(stripped)
        if not forms:
            continue  # body-structure not translated in KR, can't assess
        pref = forms["ko_preferred"]
        syns = forms["ko_synonyms"]
        all_forms = [pref, *syns]
        # Which form does each procedure use?
        usage: dict[str, list[dict]] = defaultdict(list)
        for p in procs:
            ko = p["ko_preferred"]
            # Pick longest form that appears in ko (to avoid false partial matches)
            matched = None
            for form in sorted(all_forms, key=lambda s: -len(s)):
                if form in ko:
                    matched = form
                    break
            if matched:
                usage[matched].append(p)
            else:
                usage["(none detected)"].append(p)
        forms_used = [f for f in usage if f != "(none detected)"]
        if len(forms_used) >= 2:
            findings.append({
                "body_site_en": stripped,
                "ko_preferred": pref,
                "ko_synonyms": "; ".join(syns),
                "n_procedures": len(procs),
                "forms_used": sorted(forms_used, key=lambda f: -len(usage[f])),
                "usage": {f: [p["sctid"] for p in usage[f]] for f in usage},
                "procedures": [
                    {"sctid": p["sctid"], "en": p["en_term"], "ko": p["ko_preferred"]}
                    for p in procs
                ],
            })
    # Sort by most procedures (bigger clusters = more impact)
    findings.sort(key=lambda f: -f["n_procedures"])
    return findings


# ---------- Axis 2: modality rendering ----------

def axis2_modality(rows: list[dict]) -> list[dict]:
    """For each Method attribute, enumerate distinct Korean modality renderings observed."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        mid = r.get("method_id")
        if mid:
            groups[mid].append(r)

    findings: list[dict] = []
    for mid, procs in groups.items():
        if len(procs) < 2:
            continue
        method_fsn = procs[0]["method_fsn"]
        variants = MODALITY_VARIANTS.get(mid)
        counts: Counter[str] = Counter()
        examples: dict[str, list[str]] = defaultdict(list)
        unmatched = 0
        for p in procs:
            ko = p["ko_preferred"]
            matched = None
            if variants:
                for form in sorted(variants, key=lambda s: -len(s)):
                    if form in ko:
                        matched = form
                        break
            if matched:
                counts[matched] += 1
                if len(examples[matched]) < 3:
                    examples[matched].append(f"{p['sctid']}: {p['ko_preferred']}")
            else:
                unmatched += 1
        if len(counts) >= 2 or (variants and unmatched > 0 and len(counts) >= 1):
            findings.append({
                "method_id": mid,
                "method_fsn": method_fsn,
                "friendly_name": MODALITY_NAMES.get(mid, method_fsn),
                "n_procedures": len(procs),
                "variants_observed": counts.most_common(),
                "unmatched_count": unmatched,
                "examples": dict(examples),
            })
    findings.sort(key=lambda f: -f["n_procedures"])
    return findings


# ---------- Axis 3: suffix / action word ----------

def axis3_suffix(rows: list[dict]) -> list[dict]:
    """For each Method attribute group, count terminal action tokens in ko_preferred."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        mid = r.get("method_id")
        if mid:
            groups[mid].append(r)

    findings: list[dict] = []
    for mid, procs in groups.items():
        if len(procs) < 2:
            continue
        term_counts: Counter[str] = Counter()
        examples: dict[str, list[str]] = defaultdict(list)
        for p in procs:
            ko = p["ko_preferred"]
            # Take last whitespace-separated token; if it ends in a known
            # TERMINAL_TOKENS suffix, count that suffix; otherwise count the token itself.
            toks = ko.split()
            if not toks:
                continue
            last = toks[-1]
            term = None
            for t in sorted(TERMINAL_TOKENS, key=lambda s: -len(s)):
                if last.endswith(t):
                    term = t
                    break
            if term is None:
                term = f"(other: {last})"
            term_counts[term] += 1
            if len(examples[term]) < 3:
                examples[term].append(f"{p['sctid']}: {ko}")
        if len(term_counts) >= 2:
            findings.append({
                "method_id": mid,
                "method_fsn": procs[0]["method_fsn"],
                "friendly_name": MODALITY_NAMES.get(mid, procs[0]["method_fsn"]),
                "n_procedures": len(procs),
                "terminal_counts": term_counts.most_common(),
                "examples": dict(examples),
            })
    findings.sort(key=lambda f: -f["n_procedures"])
    return findings


# ---------- Axis 4: contrast + site word order ----------

CONTRAST_EN_RE = re.compile(r"\b(with|without)\s+(contrast|radiopaque\s+contrast)", re.IGNORECASE)
CONTRAST_KO_PREFIX_RE = re.compile(r"^\s*(조영제|조영|비조영|조영 ?증강|비조영 ?증강)")


def axis4_contrast_order(rows: list[dict]) -> dict:
    """Count procedures whose English mentions contrast, split by whether Korean
    starts with the contrast phrase (contrast-first) or the body-site (site-first)."""
    contrast_first = 0
    site_first = 0
    examples_cf: list[dict] = []
    examples_sf: list[dict] = []
    for r in rows:
        if not CONTRAST_EN_RE.search(r["en_term"]):
            continue
        ko = r["ko_preferred"]
        if CONTRAST_KO_PREFIX_RE.match(ko):
            contrast_first += 1
            if len(examples_cf) < 5:
                examples_cf.append({"sctid": r["sctid"], "en": r["en_term"], "ko": ko})
        else:
            site_first += 1
            if len(examples_sf) < 5:
                examples_sf.append({"sctid": r["sctid"], "en": r["en_term"], "ko": ko})
    return {
        "total_contrast_procedures": contrast_first + site_first,
        "contrast_first": contrast_first,
        "site_first": site_first,
        "examples_contrast_first": examples_cf,
        "examples_site_first": examples_sf,
    }


# ---------- LLM interpretation ----------

LLM_SYSTEM = """\
You are a senior Korean medical-terminology reviewer. You will be shown a
cluster of Korean SNOMED translations that share a common element (body site
or imaging modality) but render it differently across concepts.

Decide whether the variation is:
  INTENTIONAL — different clinical contexts legitimately use different forms
                (e.g. anatomical vs functional; formal vs colloquial).
  ARBITRARY   — the variation appears to be author inconsistency with no
                clinical justification; a single canonical form would be
                preferable.
  UNCLEAR     — insufficient information to judge.

Also recommend which form (if any) should be canonical, based on frequency
and clinical convention.

Return ONLY a single JSON object (no extra text):
{
  "classification": "INTENTIONAL" | "ARBITRARY" | "UNCLEAR",
  "recommended_canonical": "<one of the observed forms, or empty>",
  "reasoning": "<one or two short sentences>"
}
"""


def build_llm_prompts(axis1: list[dict], axis2: list[dict], axis3: list[dict],
                     max_per_axis: int = 20) -> list[dict]:
    """Pick the highest-impact clusters per axis for LLM review."""
    tasks: list[dict] = []
    for f in axis1[:max_per_axis]:
        proc_lines = "\n".join(
            f"- {p['sctid']}: {p['en']} → {p['ko']}" for p in f["procedures"][:12]
        )
        text = (
            f"Body site: {f['body_site_en']} (KR preferred Korean: {f['ko_preferred']}; "
            f"acceptable synonyms: {f['ko_synonyms']})\n\n"
            f"{len(f['procedures'])} procedures reference this site. "
            f"Forms used: {', '.join(f['forms_used'])}.\n\n"
            f"Sample procedures:\n{proc_lines}"
        )
        tasks.append({"axis": "body_site", "key": f["body_site_en"], "prompt": text})
    for f in axis2[:max_per_axis]:
        variants_text = ", ".join(f"{v} ({n})" for v, n in f["variants_observed"])
        ex_lines = []
        for v, exs in f["examples"].items():
            for e in exs[:2]:
                ex_lines.append(f"- [{v}] {e}")
        text = (
            f"Modality (Method attribute): {f['friendly_name']} "
            f"({f['method_fsn']})\n\n"
            f"{f['n_procedures']} procedures use this method. Korean renderings "
            f"observed: {variants_text}. Unmatched: {f['unmatched_count']}.\n\n"
            f"Examples:\n" + "\n".join(ex_lines[:20])
        )
        tasks.append({"axis": "modality", "key": f["method_id"], "prompt": text})
    for f in axis3[:max_per_axis]:
        variants_text = ", ".join(f"{t} ({n})" for t, n in f["terminal_counts"])
        ex_lines = []
        for t, exs in f["examples"].items():
            for e in exs[:2]:
                ex_lines.append(f"- [{t}] {e}")
        text = (
            f"Action-suffix within modality: {f['friendly_name']}\n\n"
            f"Terminal action tokens observed across {f['n_procedures']} procedures: "
            f"{variants_text}.\n\n"
            f"Examples:\n" + "\n".join(ex_lines[:20])
        )
        tasks.append({"axis": "suffix", "key": f["method_id"], "prompt": text})
    return tasks


def wait_for_server(base_url: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    raise SystemExit(f"LLM backend not ready within {timeout}s")


def call_llm(base_url: str, model_id: str, prompt: str) -> tuple[str, str, str]:
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 256,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    content = (msg.get("content") or msg.get("reasoning") or "").strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    classification = "UNKNOWN"
    canonical = ""
    reasoning = content[:300]
    try:
        obj = json.loads(content)
        classification = str(obj.get("classification", "UNKNOWN")).upper()
        canonical = str(obj.get("recommended_canonical", "")).strip()
        reasoning = str(obj.get("reasoning", "")).strip()
    except json.JSONDecodeError:
        pass
    return classification, canonical, reasoning


def run_llm(tasks: list[dict], model_key: str, concurrency: int = 8) -> list[dict]:
    cfg = json.loads((ROOT_DIR / "configs" / "models.json").read_text())
    model_cfg = cfg["models"][model_key]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]
    wait_for_server(base_url)
    log.info("Judging %d clusters with %s...", len(tasks), model_key)

    results: list[dict] = []
    lock = Lock()

    def one(task: dict) -> dict:
        try:
            cls, canonical, reasoning = call_llm(base_url, model_id, task["prompt"])
        except Exception as exc:
            cls, canonical, reasoning = "ERROR", "", str(exc)[:200]
        return {**task, "classification": cls,
                "recommended_canonical": canonical, "reasoning": reasoning}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(one, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            with lock:
                results.append(r)
                done += 1
                if done % 10 == 0:
                    log.info("  %d/%d judged", done, len(tasks))
    return results


# ---------- Report rendering ----------

def render_report(
    rows: list[dict],
    axis1: list[dict],
    axis2: list[dict],
    axis3: list[dict],
    axis4: dict,
    verdicts: list[dict],
    *,
    scope_name: str = "imaging",
    scope_label: str = "Imaging (procedure)",
) -> str:
    verdict_by_axis_key: dict[tuple[str, str], dict] = {
        (v["axis"], v["key"]): v for v in verdicts
    }
    today = date.today().isoformat()

    lines = [
        f"# KR SNOMED {scope_name} — internal inconsistency report ({today})",
        "",
        "## Scope",
        "",
        f"{len(rows)} concepts in the `{scope_label}` hierarchy that have "
        f"an active Korean preferred synonym in the KR SNOMED release "
        f"(`KR1000267_20251215`). This is the **complete KR-covered set** "
        f"under this root for this release.",
        "",
        "## Why this report exists",
        "",
        "Our imaging-resources ablation (see "
        "`imaging_resources_ablation_findings_2026-04-20.md`) showed that "
        "even a body-site dictionary extracted from the KR release itself "
        "cannot beat pure exemplar retrieval. The diagnosis was that the KR "
        "release is **internally inconsistent**: the same anatomical site or "
        "imaging modality is rendered differently across procedures. This "
        "report enumerates those inconsistencies so they can feed back into "
        "style-guide v4 and into KR release curation.",
        "",
        "## Axis 1 — Body-site rendering",
        "",
        f"Procedures sharing the same body-site attribute target were grouped "
        f"and checked for whether they use the body-structure concept's "
        f"preferred Korean form, an acceptable synonym, or neither. "
        f"{len(axis1)} body sites show **≥2 distinct renderings** across "
        f"their procedures. Top clusters by procedure count:",
        "",
        "| Body site | Procedures | Forms used (count) |",
        "|---|---|---|",
    ]
    for f in axis1[:15]:
        forms = ", ".join(f"`{form}` ({len(f['usage'][form])})" for form in f["forms_used"])
        if f["usage"].get("(none detected)"):
            forms += f", _no site form detected_ ({len(f['usage']['(none detected)'])})"
        lines.append(f"| {f['body_site_en']} | {f['n_procedures']} | {forms} |")
    lines.append("")
    lines.append("### Example clusters with LLM verdicts")
    lines.append("")
    for f in axis1[:8]:
        lines.append(f"**{f['body_site_en']}** — KR preferred: `{f['ko_preferred']}`; "
                     f"synonyms: {f['ko_synonyms'] or '_none_'}")
        lines.append("")
        lines.append("| SCTID | English | Korean |")
        lines.append("|---|---|---|")
        for p in f["procedures"][:8]:
            lines.append(f"| {p['sctid']} | {p['en']} | {p['ko']} |")
        v = verdict_by_axis_key.get(("body_site", f["body_site_en"]))
        if v:
            lines.append("")
            lines.append(f"**Verdict ({v['classification']})** — recommended canonical: "
                         f"`{v['recommended_canonical'] or '—'}`. "
                         f"_{v['reasoning']}_")
        lines.append("")

    lines.extend([
        "## Axis 2 — Modality rendering",
        "",
        f"Grouped by the SNOMED `Method` attribute. For each modality with "
        f"≥2 observed Korean renderings, counts are shown below. "
        f"Total methods with variance: {len(axis2)}.",
        "",
        "| Modality | Procedures | Variants (count) | Unmatched |",
        "|---|---|---|---|",
    ])
    for f in axis2:
        variants = ", ".join(f"`{v}` ({n})" for v, n in f["variants_observed"])
        lines.append(f"| {f['friendly_name']} | {f['n_procedures']} | {variants} | {f['unmatched_count']} |")
    lines.append("")
    lines.append("### Per-modality LLM verdicts")
    lines.append("")
    for f in axis2:
        v = verdict_by_axis_key.get(("modality", f["method_id"]))
        if not v:
            continue
        lines.append(f"- **{f['friendly_name']}** — {v['classification']}; "
                     f"canonical: `{v['recommended_canonical'] or '—'}`. "
                     f"_{v['reasoning']}_")
    lines.append("")

    lines.extend([
        "## Axis 3 — Action-suffix discipline",
        "",
        f"Terminal action tokens (`촬영 / 영상 / 검사 / 조영(술/상) / 측정 / 스캔 / 술 / …`) "
        f"within each method group. "
        f"Methods with mixed terminals: {len(axis3)}.",
        "",
        "| Modality | Procedures | Terminal tokens (count) |",
        "|---|---|---|",
    ])
    for f in axis3:
        terms = ", ".join(f"`{t}` ({n})" for t, n in f["terminal_counts"])
        lines.append(f"| {f['friendly_name']} | {f['n_procedures']} | {terms} |")
    lines.append("")
    lines.append("### Per-modality suffix LLM verdicts")
    lines.append("")
    for f in axis3:
        v = verdict_by_axis_key.get(("suffix", f["method_id"]))
        if not v:
            continue
        lines.append(f"- **{f['friendly_name']}** — {v['classification']}; "
                     f"canonical: `{v['recommended_canonical'] or '—'}`. "
                     f"_{v['reasoning']}_")
    lines.append("")

    lines.extend([
        "## Axis 4 — Contrast word-order",
        "",
        f"For procedures whose English FSN contains `with contrast` or "
        f"`without contrast`, we check whether the Korean puts the contrast "
        f"phrase first or the body site first.",
        "",
        f"- Total contrast procedures: **{axis4['total_contrast_procedures']}**",
        f"- Contrast-first (`조영제 … 부위 …`): **{axis4['contrast_first']}**",
        f"- Site-first (`부위 … 조영제 …`): **{axis4['site_first']}**",
        "",
        "**Contrast-first examples:**",
    ])
    for e in axis4["examples_contrast_first"]:
        lines.append(f"- {e['sctid']}: {e['en']} → {e['ko']}")
    lines.append("")
    lines.append("**Site-first examples:**")
    for e in axis4["examples_site_first"]:
        lines.append(f"- {e['sctid']}: {e['en']} → {e['ko']}")
    lines.append("")

    # Summary
    n_arbitrary = sum(1 for v in verdicts if v.get("classification") == "ARBITRARY")
    n_intentional = sum(1 for v in verdicts if v.get("classification") == "INTENTIONAL")
    n_unclear = sum(1 for v in verdicts if v.get("classification") == "UNCLEAR")

    lines.extend([
        "## Summary",
        "",
        f"- Clusters reviewed by LLM: **{len(verdicts)}**",
        f"  - classified ARBITRARY: {n_arbitrary}",
        f"  - classified INTENTIONAL: {n_intentional}",
        f"  - classified UNCLEAR / other: {n_unclear}",
        "",
        "### Implications",
        "",
        "- Arbitrary clusters are candidates for KR release curation "
        "(canonicalise to the recommended form, add the other form as an "
        "acceptable synonym) or for explicit style-guide rules.",
        "- Intentional clusters inform the style guide: document the "
        "contextual rule so translators can reproduce it.",
        "- Unclear clusters need SME input from KHIS.",
        "",
        "### Caveats",
        "",
        "- LLM verdicts are directional, not authoritative. They reflect one "
        "model's reading; disagreements with KHIS's own policy should be "
        "resolved by KHIS.",
        "- Axis 1 uses substring matching of body-structure-concept synonyms "
        "to detect the 'which rendering was used' signal. Procedures that "
        "re-phrase the body site without reusing the canonical terms will be "
        "counted as `(none detected)` — that column is itself a useful "
        "signal about free-form anatomical rendering.",
        "- Axis 2's modality variant list is hand-curated. Unmatched rows "
        "may indicate either modality renderings we forgot or procedures "
        "that deviate in unexpected ways.",
        "",
    ])

    return "\n".join(lines)


# ---------- Main ----------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=list(SCOPES), default="imaging",
                        help="Named hierarchy scope. Determines input / output paths.")
    parser.add_argument("--llm-model", type=str, default="gemma4-26b")
    parser.add_argument("--llm-concurrency", type=int, default=8)
    parser.add_argument("--max-clusters-per-axis", type=int, default=15)
    parser.add_argument("--skip-llm", action="store_true",
                        help="Produce CSVs and report without LLM interpretation")
    args = parser.parse_args()

    dataset_path = ROOT_DIR / "data" / "analysis" / f"{args.scope}_inconsistencies" / f"kr_{args.scope}_dataset.csv"
    out_dir = ROOT_DIR / "data" / "analysis" / f"{args.scope}_inconsistencies"
    scope_label = SCOPES[args.scope]

    log.info("Scope: %s (%s)", args.scope, scope_label)
    log.info("Loading dataset from %s...", dataset_path.relative_to(ROOT_DIR))
    rows = load_dataset(dataset_path)
    site_forms = load_body_site_renderings()
    log.info("  %d concepts, %d body-structure entries in KR dict", len(rows), len(site_forms))

    log.info("Axis 1: body-site renderings...")
    axis1 = axis1_body_sites(rows, site_forms)
    log.info("  %d body sites with ≥2 renderings across their procedures", len(axis1))

    log.info("Axis 2: modality renderings...")
    axis2 = axis2_modality(rows)
    log.info("  %d modalities with variance", len(axis2))

    log.info("Axis 3: action-suffix discipline...")
    axis3 = axis3_suffix(rows)
    log.info("  %d modalities with mixed terminals", len(axis3))

    log.info("Axis 4: contrast word order...")
    axis4 = axis4_contrast_order(rows)
    log.info("  total contrast procedures: %d (cf=%d, sf=%d)",
             axis4["total_contrast_procedures"],
             axis4["contrast_first"], axis4["site_first"])

    # Write CSVs
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "axis1_body_site.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["body_site", "ko_preferred", "ko_synonyms", "n_procedures",
                    "form", "n_uses", "example_sctids"])
        for fi in axis1:
            for form, sctids in fi["usage"].items():
                w.writerow([fi["body_site_en"], fi["ko_preferred"],
                            fi["ko_synonyms"], fi["n_procedures"],
                            form, len(sctids), "; ".join(sctids[:5])])

    with (out_dir / "axis2_modality.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method_id", "method_fsn", "n_procedures",
                    "variant", "count"])
        for fi in axis2:
            for var, n in fi["variants_observed"]:
                w.writerow([fi["method_id"], fi["method_fsn"],
                            fi["n_procedures"], var, n])
            if fi["unmatched_count"]:
                w.writerow([fi["method_id"], fi["method_fsn"],
                            fi["n_procedures"], "(unmatched)", fi["unmatched_count"]])

    with (out_dir / "axis3_suffix.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method_id", "method_fsn", "n_procedures", "terminal", "count"])
        for fi in axis3:
            for term, n in fi["terminal_counts"]:
                w.writerow([fi["method_id"], fi["method_fsn"],
                            fi["n_procedures"], term, n])

    with (out_dir / "axis4_contrast_order.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order", "count"])
        w.writerow(["contrast_first", axis4["contrast_first"]])
        w.writerow(["site_first", axis4["site_first"]])

    # LLM tasks
    tasks = build_llm_prompts(axis1, axis2, axis3,
                              max_per_axis=args.max_clusters_per_axis)
    log.info("Prepared %d LLM tasks", len(tasks))
    (out_dir / "clusters_for_llm.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in tasks),
        encoding="utf-8",
    )

    verdicts: list[dict] = []
    if not args.skip_llm:
        verdicts = run_llm(tasks, args.llm_model, args.llm_concurrency)
        (out_dir / "llm_verdicts.jsonl").write_text(
            "\n".join(json.dumps(v, ensure_ascii=False) for v in verdicts),
            encoding="utf-8",
        )

    # Report
    report = render_report(rows, axis1, axis2, axis3, axis4, verdicts,
                           scope_name=args.scope, scope_label=scope_label)
    today = date.today().isoformat()
    report_path = ROOT_DIR / "docs" / f"{args.scope}_inconsistencies_{today}.md"
    report_path.write_text(report, encoding="utf-8")
    log.info("Wrote report to %s", report_path.relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
