#!/usr/bin/env python3
"""Reproduce and characterise the vLLM engine hang, with fast detection.

The engine has hung twice during long sampling runs (7,500 and 4,000 calls in),
both times the same way: generation throughput drops to 0 tokens/s while
requests sit in "Running", KV cache is ~1.5% (no pressure), and the GPU reports
~96% utilisation at ~17W (a spinning kernel, not compute). No error is logged.

This harness drives the server directly with the REAL prompt shape (a captured
5.2k-token production prompt) so a reproduction is meaningful, and — the point
of the exercise — it detects the stall within `--stall-seconds` instead of the
hours a completion-only waiter takes, then snapshots the evidence.

Vary ONE factor per invocation to find the trigger:
    --concurrency 16|8|4     request fan-out
    --temperature 0.7|0.0    sampling vs greedy
    --prefix same|unique     shared long system prompt (exercises prefix cache)
                             vs a per-request unique prefix (bypasses it)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "http://localhost:8086"


def metrics() -> dict:
    try:
        raw = urllib.request.urlopen(f"{BASE}/metrics", timeout=5).read().decode()
    except Exception as exc:
        return {"error": str(exc)}
    out = {}
    for line in raw.splitlines():
        for key in ("vllm:num_requests_running", "vllm:num_requests_waiting"):
            if line.startswith(key + "{"):
                try:
                    out[key.split(":")[1]] = float(line.rsplit(" ", 1)[1])
                except Exception:
                    pass
    return out


def snapshot(tag: str) -> None:
    """Everything worth having at the moment of the hang."""
    print(f"\n=== STALL SNAPSHOT ({tag}) ===", flush=True)
    print("metrics:", metrics(), flush=True)
    for cmd in (["nvidia-smi", "--query-gpu=utilization.gpu,power.draw,memory.used",
                 "--format=csv,noheader"],
                ["docker", "logs", "--tail", "6", "snomed-gemma4-qat"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            print(f"$ {' '.join(cmd[:3])}\n{(r.stdout or r.stderr).strip()[:600]}", flush=True)
        except Exception as exc:
            print(f"$ {' '.join(cmd[:3])} -> {exc}", flush=True)
    # Where is the engine stuck? py-spy if present tells us Python-level vs CUDA.
    try:
        r = subprocess.run(["docker", "exec", "snomed-gemma4-qat", "py-spy", "dump",
                            "--pid", "1"], capture_output=True, text=True, timeout=45)
        out = (r.stdout or r.stderr).strip()
        print("py-spy dump:\n" + (out[:1500] if out else "(no output)"), flush=True)
    except Exception as exc:
        print(f"py-spy unavailable: {exc}", flush=True)


def load_prompt() -> tuple[str, str]:
    """A real captured production prompt (system + one user turn)."""
    root = Path(__file__).resolve().parents[2]
    runs = root.parent / "wizard-data/wizard_runs"
    for p in sorted(runs.glob("*/artifacts/prompts_*.jsonl"), reverse=True):
        lines = p.read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            continue
        meta = json.loads(lines[0])
        row = json.loads(lines[1])
        if meta.get("system") and row.get("user"):
            return meta["system"], row["user"]
    raise SystemExit("no captured prompt found — run a translate flow first")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=8000)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--prefix", choices=["same", "unique"], default="same")
    ap.add_argument("--stall-seconds", type=int, default=90)
    ap.add_argument("--model", default="cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4")
    # Faithful mode: send the EXACT llm_params the flow sends. Run A passed with
    # a bare request, so any difference here is a live suspect.
    ap.add_argument("--faithful", action="store_true",
                    help="include stop sequences + chat_template_kwargs + "
                         "enable_thinking, as translate_consistency does")
    args = ap.parse_args()

    system, user = load_prompt()
    print(f"config: calls={args.calls} concurrency={args.concurrency} "
          f"temp={args.temperature} prefix={args.prefix} "
          f"system={len(system)}chars", flush=True)

    done = [0]
    errors = [0]
    last = [time.monotonic()]
    lock = threading.Lock()
    stop = threading.Event()

    def one(i: int) -> None:
        if stop.is_set():
            return
        sys_prompt = system if args.prefix == "same" else f"[variant {i}]\n{system}"
        payload = {
            "model": args.model, "temperature": args.temperature,
            "max_tokens": 256, "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user}]}
        if args.faithful:
            payload.update({
                "stop": ["\n\n", "English:"],
                "chat_template_kwargs": {"enable_thinking": False},
                "enable_thinking": False,
            })
        body = json.dumps(payload).encode()
        try:
            req = urllib.request.Request(f"{BASE}/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=300).read()
        except Exception:
            with lock:
                errors[0] += 1
        with lock:
            done[0] += 1
            last[0] = time.monotonic()
            if done[0] % 200 == 0:
                print(f"  {done[0]}/{args.calls} done, {errors[0]} errors, "
                      f"{metrics()}", flush=True)

    def watchdog() -> None:
        """The thing I should have had from the start."""
        while not stop.is_set():
            time.sleep(5)
            idle = time.monotonic() - last[0]
            if idle > args.stall_seconds:
                print(f"\n!!! STALL: no completion for {idle:.0f}s at "
                      f"{done[0]}/{args.calls} calls", flush=True)
                snapshot(f"{done[0]} calls, concurrency={args.concurrency}, "
                         f"temp={args.temperature}, prefix={args.prefix}")
                stop.set()
                return

    t0 = time.monotonic()
    threading.Thread(target=watchdog, daemon=True).start()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        list(ex.map(one, range(args.calls)))
    stop.set()
    elapsed = time.monotonic() - t0
    print(f"\nRESULT: {done[0]}/{args.calls} completed in {elapsed:.0f}s "
          f"({done[0]/elapsed:.1f}/s), {errors[0]} errors, "
          f"stalled={done[0] < args.calls}", flush=True)
    return 0 if done[0] >= args.calls else 1


if __name__ == "__main__":
    sys.exit(main())
