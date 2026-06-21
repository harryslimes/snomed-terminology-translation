"""
Run the agentic SNOMED CT translation loop.

Supports single-concept or batch mode, with Claude or vLLM backends.

Usage:
    # Single concept via vLLM (Gingivitis):
    python agent/main.py --vllm-url http://localhost:8000 \
        --model Qwen/Qwen3.5-35B-A3B-GPTQ-Int4 --sctid 66383009

    # Batch from CSV via vLLM:
    python agent/main.py --vllm-url http://localhost:8000 \
        --model Qwen/Qwen3.5-35B-A3B-GPTQ-Int4 \
        --input data/evals/sample/concepts/100_concepts.csv

    # Batch with Claude (needs ANTHROPIC_API_KEY):
    python agent/main.py --backend claude --input data/evals/wave_2/wave_2.csv
"""

import argparse
import csv
import logging
import os
import pickle
import time
from datetime import datetime
from pathlib import Path

import requests

from dotenv import load_dotenv

load_dotenv()

from agent import AgentConfig, build_agent
from models import State
from utils import (
    calculate_cost,
    get_best_translation,
    get_num_translation_iterations,
    render_as_md,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("snomed")
logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agentic SNOMED CT EN→ET translation loop"
    )

    # LLM backend
    parser.add_argument(
        "--backend",
        choices=["vllm", "claude"],
        default=None,
        help="LLM backend. Default: vllm if --vllm-url given, else claude",
    )
    parser.add_argument("--vllm-url", default="http://localhost:8000")
    parser.add_argument("--model", default="Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")
    parser.add_argument("--tools-server", default="http://localhost:8008")

    # Input: single concept or CSV
    parser.add_argument(
        "--sctid",
        type=int,
        default=None,
        help="Translate a single concept by SCTID",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="CSV file with sctid column for batch mode",
    )

    # Output
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/evals/agentic_translations"),
        help="Output directory for results",
    )

    # Loop parameters
    parser.add_argument("--max-reflection-steps", type=int, default=3)
    parser.add_argument("--max-extracts", type=int, default=3)
    parser.add_argument("--max-search-results", type=int, default=5)
    parser.add_argument("--min-extract-relevancy", type=float, default=0.4)

    parser.add_argument(
        "--no-paired-translations",
        action="store_true",
        help="Disable paired translation retrieval (to avoid data leakage)",
    )
    parser.add_argument(
        "--min-reflection-steps",
        type=int,
        default=0,
        help="Force at least N enrichment+reflection rounds even if confident",
    )

    # Suppression
    parser.add_argument(
        "--ee-extension",
        type=Path,
        default=None,
        help="EE national extension descriptions file (concepts to suppress)",
    )

    return parser.parse_args()


def build_config(args) -> AgentConfig:
    """Build AgentConfig from CLI args."""
    backend = args.backend
    if backend is None:
        backend = "vllm" if args.vllm_url else "claude"

    cohere_client = None
    cohere_key = os.getenv("COHERE_API_KEY")
    if cohere_key:
        try:
            import cohere

            cohere_client = cohere.ClientV2(api_key=cohere_key)
            logger.info("Cohere reranker enabled")
        except ImportError:
            logger.info("Cohere package not installed, skipping reranking")

    serpapi_key = os.getenv("SERPAPI_API_KEY")
    if serpapi_key:
        logger.info("SerpAPI web search enabled")

    return AgentConfig(
        backend=backend,
        vllm_url=args.vllm_url,
        vllm_model=args.model,
        tools_server=args.tools_server,
        use_cohere=cohere_client is not None,
        use_web_search=bool(serpapi_key),
        use_paired_translations=not args.no_paired_translations,
        min_reflection_steps=args.min_reflection_steps,
        cohere_client=cohere_client,
    )


def translate_one(agent, sctid: int, args) -> dict:
    """Run the agentic loop for a single concept."""
    initial_state = State(
        sctid=sctid,
        max_reflection_steps=args.max_reflection_steps,
        min_extract_relevancy_score=args.min_extract_relevancy,
        max_extracts=args.max_extracts,
        max_search_results=args.max_search_results,
    )
    return agent.invoke(initial_state)


def print_trace(final_state: dict):
    """Print a human-readable trace of the translation loop."""
    print("\n" + "=" * 70)
    print(
        f"  {final_state['sctid']} | {final_state['preferred_term']} "
        f"({final_state['hierarchy']})"
    )
    print("=" * 70)

    it = final_state["initial_translation"]
    print(f"\n  INITIAL: {it['translation']}")
    print(f"  Confident: {it['confident']}")
    print(f"  Reasoning: {it.get('reasoning', '')}")
    if it.get("unverified_words"):
        print(f"  Unverified: {it['unverified_words']}")

    for i, rev in enumerate(final_state.get("revised_translations", []), 1):
        print(f"\n  REFLECTION {i}: {rev['translation']}")
        print(f"  Confident: {rev['confident']}")
        print(f"  Reasoning: {rev.get('reasoning', '')}")
        changed = rev.get("changed", "")
        if changed:
            print(f"  Changed: {changed}")

    for i, rev in enumerate(final_state.get("forced_revisions", []), 1):
        print(f"\n  FORCED REVISION {i}: {rev['translation']}")
        print(f"  Reasoning: {rev.get('reasoning', '')}")

    best = get_best_translation(final_state)
    steps = get_num_translation_iterations(final_state)
    print(f"\n  FINAL: {best['translation']}")
    print(f"  Steps: {steps}  |  Confident: {best['confident']}")
    print("=" * 70)


def main():
    args = parse_args()

    if args.sctid is None and args.input is None:
        raise SystemExit("Provide --sctid for single concept or --input for batch CSV")

    config = build_config(args)
    agent = build_agent(config)

    # Wait for vLLM if using it
    if config.backend == "vllm":
        logger.info("Checking vLLM at %s ...", config.vllm_url)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                r = requests.get(f"{config.vllm_url}/v1/models", timeout=5)
                if r.ok:
                    logger.info("vLLM ready")
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError(f"vLLM not reachable at {config.vllm_url}")

    # Check tools server
    try:
        r = requests.get(f"{config.tools_server}/check_concept", params={"sctid": 0}, timeout=5)
    except Exception:
        raise RuntimeError(
            f"Tools server not reachable at {config.tools_server}. "
            f"Start it with: cd agent && python tools.py"
        )

    # ── Single concept mode ──
    if args.sctid is not None:
        logger.info("Translating single concept: SCTID %d", args.sctid)
        start = time.monotonic()
        final_state = translate_one(agent, args.sctid, args)
        elapsed = time.monotonic() - start

        print_trace(final_state)
        print(f"\n  Elapsed: {elapsed:.1f}s")

        # Save markdown trace
        args.output_dir.mkdir(parents=True, exist_ok=True)
        md_path = args.output_dir / f"{args.sctid}.md"
        md_path.write_text(render_as_md(final_state))
        logger.info("Saved trace to %s", md_path)
        return

    # ── Batch mode ──
    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    # Optional suppression of EE extension concepts
    suppression_set = set()
    if args.ee_extension and args.ee_extension.exists():
        import pandas as pd

        ee_df = pd.read_csv(args.ee_extension, delimiter="\t")
        suppression_set = set(ee_df["conceptId"].values)
        logger.info("Suppressing %d EE extension concepts", len(suppression_set))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    translations = {}
    total_cost = 0
    start = time.monotonic()

    for i, row in enumerate(rows, 1):
        sctid = int(row["sctid"])
        preferred_term = row.get("preferred_term", "")

        if sctid in suppression_set:
            logger.info("[%d/%d] Skipping %s (in EE extension)", i, len(rows), preferred_term)
            continue

        logger.info("[%d/%d] Translating [%s] %s", i, len(rows), sctid, preferred_term)

        try:
            final_state = translate_one(agent, sctid, args)
            translations[sctid] = final_state
            cost = calculate_cost(final_state)
            total_cost += cost

            # Save individual markdown
            md_path = args.output_dir / "markdown" / f"{sctid}.md"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(render_as_md(final_state))

            best = get_best_translation(final_state)
            logger.info(
                "  → %s (confident=%s, steps=%d)",
                best["translation"],
                best["confident"],
                get_num_translation_iterations(final_state),
            )
        except Exception as e:
            logger.error("  Failed: %s", e)

        # Checkpoint
        with open(args.output_dir / "translations_cache.pkl", "wb") as f:
            pickle.dump(translations, f)

    elapsed = time.monotonic() - start
    logger.info("Finished %d concepts in %.1fs (cost: $%.4f)", len(translations), elapsed, total_cost)

    # Write summary CSV
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    csv_path = args.output_dir / f"translations_{ts}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sctid", "preferred_term", "hierarchy", "translation",
                "confident", "num_steps", "context_used",
            ],
        )
        writer.writeheader()
        for sctid, state in translations.items():
            best = get_best_translation(state)
            writer.writerow({
                "sctid": sctid,
                "preferred_term": state["preferred_term"],
                "hierarchy": state.get("hierarchy", ""),
                "translation": best["translation"],
                "confident": best["confident"],
                "num_steps": get_num_translation_iterations(state),
                "context_used": "agentic_loop",
            })

    logger.info("Wrote %s", csv_path)


if __name__ == "__main__":
    main()
