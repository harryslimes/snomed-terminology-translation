"""Reference-free SME-acceptability judge — an LLM MT error gate.

Estimates whether a Korean-speaking SNOMED terminologist would accept an
EN->KO translation, labelling each pair ACCEPTABLE / PARTIAL / WRONG with a
0..1 score + a one-line reason. This is the layer that catches *semantic*
errors a distance metric cannot — e.g. ``Mammogram - symptomatic`` rendered
``유방 촬영 증상치료`` ('mammogram symptom TREATMENT'), which embedding
similarity ranks mid-pack but a judge flags as WRONG.

The rubric mirrors ``configs/ko/judge/sme_acceptability_judge_v1.md``. The node
routes on ``model``: a Claude alias (opus/sonnet/fable/claude*) goes through the
Claude Agent SDK (reusing host subscription auth); anything else is treated as
a vLLM ``hf_id`` and hit over the OpenAI-compatible ``base_url`` — so the same
node serves the local gemma arm and the frontier (Sonnet) arm.

When the input dataset carries an SME-rating column, the metrics include
agreement with the SME (3-way + binary accept/reject).
"""
from __future__ import annotations

import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pipelines.context import RunContext
from pipelines.llm_accounting import record_completion
from pipelines.functions import FunctionResult

DEFAULT_SYSTEM = """You are a senior Korean clinical terminologist reviewing machine translations of SNOMED CT terms for the Korean edition. For each (english, korean) pair, judge how you would rate the Korean rendering of the English concept.

Weigh, in priority order:
1. Adequacy — is the full clinical meaning preserved? No sense added, dropped, or changed.
2. Terminology — is the correct, established Korean medical term used for each component (anatomy, modality, procedure, morphology)? A plausible but non-standard term is a defect.
3. Completeness of modifiers — laterality, contrast (with/without), approach, guidance, quantifier, modality qualifiers all present and attached to the right head.
4. Word order — Korean is head-final; the action/modality comes last.

Do NOT penalise spacing (띄어쓰기) or a native-vs-Sino-Korean stylistic choice when the meaning and term are correct. Penalise them only when they change or obscure meaning.

Output STRICT JSON only, no prose around it:
{"label": "ACCEPTABLE|PARTIAL|WRONG", "score": <float 0-1>, "reason": "<one short sentence>"}
label: ACCEPTABLE = a terminologist would use it as-is; PARTIAL = mostly right, needs an edit; WRONG = wrong meaning or wrong core concept.
score: continuous confidence in clinical correctness (ACCEPTABLE ≥0.85, PARTIAL 0.4–0.85, WRONG <0.4).
Judge only from your own knowledge. Do not look anything up."""

_CLAUDE_RE = re.compile(r"^(opus|sonnet|haiku|fable|claude)", re.I)


def _is_claude(model: str) -> bool:
    return bool(_CLAUDE_RE.match(model.strip()))


def _parse(text: str) -> dict:
    m = re.search(r'\{.*\}', text, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            lbl = str(d.get("label", "")).strip().upper()
            if lbl in ("ACCEPTABLE", "PARTIAL", "WRONG"):
                sc = d.get("score")
                return {"label": lbl,
                        "score": float(sc) if sc is not None else "",
                        "reason": str(d.get("reason", ""))[:300]}
        except Exception:
            pass
    return {"label": "?", "score": "", "reason": text.strip()[:200]}


def _judge_local(english: str, korean: str, *, model: str, base_url: str,
                 system: str, max_tokens: int,
                 ctx: "RunContext | None" = None) -> dict:
    import urllib.request
    body = json.dumps({
        "model": model, "temperature": 0.0, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": f"english: {english}\nkorean: {korean}"}],
    }).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
    record_completion(ctx, model=model, usage=resp.get("usage"))
    return _parse(resp["choices"][0]["message"]["content"])


def _judge_claude(english: str, korean: str, *, model: str, system: str,
                  ctx: "RunContext | None" = None) -> dict:
    from snomed_translation.generate import run_query
    text = run_query(f"english: {english}\nkorean: {korean}",
                     model=model, system=system, thinking=False, ctx=ctx)
    return _parse(text)


def _dataset_path(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ("_primary", "dataset", "rows", "path"):
            if isinstance(value.get(k), str):
                return value[k]
    return None


def _roles(value: Any) -> dict[str, str]:
    return value.get("roles", {}) if isinstance(value, dict) else {}


def _col(params, roles, param_name, role, fallback) -> str:
    return str(params.get(param_name) or roles.get(role) or fallback)


def acceptability_judge(ctx: RunContext, inputs: dict[str, Any],
                        params: dict[str, Any]) -> FunctionResult:
    t0 = time.monotonic()
    tpath = _dataset_path(inputs.get("translations"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False,
                              message="acceptability_judge: no `translations` dataset wired")
    model = str(params.get("model") or "").strip()
    if not model:
        return FunctionResult(ok=False, message="acceptability_judge needs a `model`")
    base_url = str(params.get("base_url") or "http://localhost:8086")
    system = str(params.get("system") or DEFAULT_SYSTEM)
    max_tokens = int(params.get("max_tokens") or 220)
    concurrency = int(params.get("concurrency") or (4 if _is_claude(model) else 16))
    limit = int(params.get("limit") or 0)

    roles = _roles(inputs.get("translations"))
    id_col = _col(params, roles, "id_col", "sctid", "sctid")
    en_col = _col(params, roles, "en_col", "en", "en")
    ko_col = _col(params, roles, "ko_col", "target", "translation")
    label_col = str(params.get("label_col") or "sme_rating")

    with Path(tpath).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        has_label = label_col in (reader.fieldnames or [])
        src = list(reader)
    if limit:
        src = src[:limit]
    rows = [r for r in src if (r.get(en_col) or "").strip() and (r.get(ko_col) or "").strip()]
    if not rows:
        return FunctionResult(ok=False,
                              message=f"acceptability_judge: no usable rows in {tpath} "
                                      f"(en_col={en_col!r}, ko_col={ko_col!r})")

    def one(r: dict) -> dict:
        en, ko = r[en_col].strip(), r[ko_col].strip()
        try:
            v = (_judge_claude(en, ko, model=model, system=system, ctx=ctx)
                 if _is_claude(model)
                 else _judge_local(en, ko, model=model, base_url=base_url,
                                   system=system, max_tokens=max_tokens, ctx=ctx))
        except Exception as exc:
            v = {"label": "?", "score": "", "reason": f"judge error: {exc}"[:200]}
        out = {id_col: (r.get(id_col) or "").strip(), "english": en, "korean": ko,
               "judge_label": v["label"], "judge_score": v["score"],
               "judge_reason": v["reason"]}
        if has_label:
            out["sme_rating"] = (r.get(label_col) or "").strip().upper()
        return out

    results: list[dict] = [None] * len(rows)  # type: ignore
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = {ex.submit(one, r): i for i, r in enumerate(rows)}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()

    out = Path(ctx.log_dir) / "acceptability_judgements.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    n = len(results)
    elapsed = time.monotonic() - t0
    dist = {lab: sum(1 for r in results if r["judge_label"] == lab)
            for lab in ("ACCEPTABLE", "PARTIAL", "WRONG")}
    metrics = {"n_judged": float(n), "model_is_claude": float(_is_claude(model)),
               "elapsed_seconds": round(elapsed, 3),
               "throughput_rps": round(n / elapsed, 3) if elapsed else 0.0,
               "judged_acceptable": float(dist["ACCEPTABLE"]),
               "judged_partial": float(dist["PARTIAL"]),
               "judged_wrong": float(dist["WRONG"]),
               "judge_parse_fail": float(sum(1 for r in results if r["judge_label"] == "?"))}
    if has_label:
        paired = [r for r in results if r.get("sme_rating") in ("ACCEPTABLE", "PARTIAL", "WRONG")
                  and r["judge_label"] != "?"]
        m = len(paired)
        if m:
            three = sum(1 for r in paired if r["judge_label"] == r["sme_rating"])
            binp = sum(1 for r in paired
                       if (r["judge_label"] == "ACCEPTABLE") == (r["sme_rating"] == "ACCEPTABLE"))
            wrong_gold = [r for r in paired if r["sme_rating"] == "WRONG"]
            wrong_caught = sum(1 for r in wrong_gold if r["judge_label"] == "WRONG")
            metrics.update({
                "n_vs_sme": float(m),
                "agreement_3way_pct": round(100.0 * three / m, 2),
                "agreement_binary_pct": round(100.0 * binp / m, 2),
                "sme_wrong_n": float(len(wrong_gold)),
                "sme_wrong_caught": float(wrong_caught),
            })

    return FunctionResult(ok=True, outputs={"judgements": str(out)},
                          metrics=metrics,
                          message=(f"judged {n} pairs via {model} "
                                   f"(A/P/W = {dist['ACCEPTABLE']}/{dist['PARTIAL']}/{dist['WRONG']})"))
