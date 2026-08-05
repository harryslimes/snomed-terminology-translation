"""UI sections this plugin contributes to the app (``semi_automated_research.ui``).

The generic app hosts research primitives that make no assumption about LLMs or
API pricing; anything domain-specific — like estimating the cost of a bulk
*translation* run — belongs here, in the plugin, so a research project that
never touches an LLM doesn't see it. This is the plugin's first
:class:`~wizard.plugins.UIPlugin`: a nav item + router + template dir, wired
through the app's shared Jinja loader and data-driven nav (see
``wizard/plugins.py`` and ``wizard/templating.py``).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from wizard import prompts as store
from wizard.plugins import NavItem, UIPlugin
from wizard.templating import templates

_TEMPLATES_DIR = str(Path(__file__).parent / "templates")

router = APIRouter(tags=["cost"])


def estimate_tokens(text: str) -> int:
    """Provider-agnostic token estimate for ``text``.

    Uses the widely-cited ~4-characters-per-token rule of thumb. It is only an
    estimate: every model tokenises differently, and dense/non-Latin scripts
    (e.g. Korean, Estonian diacritics) run higher. Good enough for a cost
    *planning* figure; not a substitute for a real tokenizer when precision
    matters.
    """
    if not text:
        return 0
    return max(1, round(len(text) / 4))


@router.get("/cost-estimator", response_class=HTMLResponse)
def cost_estimator(request: Request) -> HTMLResponse:
    # Token-count every prompt once, server-side; the page does the cost
    # arithmetic client-side against this map so inputs recompute instantly.
    # ``list_all`` mirrors the Prompts page: stored templates plus legacy style
    # guides surfaced read-through, so every guide is selectable here too.
    prompts = []
    for t in store.list_all():
        body = t.body or ""
        prompts.append({
            "id": t.id,
            "kind": t.kind,
            "chars": len(body),
            "tokens": estimate_tokens(body),
        })
    prompts.sort(key=lambda p: (p["kind"], p["id"]))
    return templates.TemplateResponse(
        request,
        "cost_estimator.html",
        {
            "prompts": prompts,
            # Sensible starting points (all editable in the form):
            #  - output ~15 tok: measured from the `translate_run_1` outputs
            #    (621 Korean terms) — avg 14.9 chars/term, which is ~4 tok by the
            #    len/4 heuristic but ~10 (o200k) to ~18 (cl100k) under a real
            #    subword tokenizer; CJK packs far more tokens/char than the /4
            #    rule assumes. 15 is a middle-of-the-road figure; nudge it up for
            #    a term-heavy target script or a chattier model.
            #  - context ~130 tok: the per-term user message = the default
            #    5-exemplar |English|Korean| lookup table + boilerplate + the
            #    English term. Reconstructed from the real eval set + production
            #    template: avg ~415 chars ≈ 104 tok (len/4) / 130 (o200k) / 155
            #    (cl100k). Scales with translation.lookup_topn (≈130 at 5, ≈100
            #    at 3). The style guide is NOT here — it's the (cacheable) prompt.
            "defaults": {
                "terms": 10000,
                "context_tokens": 130,
                "output_tokens": 15,
                "input_price": 3.0,
                "output_price": 15.0,
                "cache_multiplier": 0.1,
                "bulk_multiplier": 0.5,
            },
        },
    )


plugin = UIPlugin(
    name="snomed_translation",
    nav=(NavItem("/cost-estimator", "Cost estimator", "Domain", scope="project"),),
    router=router,
    templates_dir=_TEMPLATES_DIR,
)
