"""Stall watchdog for long LLM stages.

Two 25k-call runs died silently on 2026-08-11: every worker thread blocked on
an infinite read timeout, so the run made no progress, logged nothing, and
raised nothing. A completion-only waiter cannot tell that apart from work in
progress — the stall was found hours later by a human asking.

This makes silence loud. Wrap a stage's work in ``progress_watchdog`` and call
``tick()`` on each completion; if nothing ticks for ``stall_seconds`` it logs a
loud ERROR with a diagnostic snapshot, and keeps warning so the run's tail is
unambiguous. It does NOT abort — a finite request timeout is what recovers the
run; this exists so nobody has to notice by hand.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)


def _snapshot(base_url: str | None) -> str:
    bits: list[str] = []
    if base_url:
        try:
            import urllib.request
            raw = urllib.request.urlopen(
                base_url.rstrip("/") + "/metrics", timeout=5).read().decode()
            for line in raw.splitlines():
                if line.startswith(("vllm:num_requests_running{",
                                    "vllm:num_requests_waiting{")):
                    bits.append(line.split("{")[0] + "=" + line.rsplit(" ", 1)[1])
        except Exception as exc:
            bits.append(f"metrics unavailable: {exc}")
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
        bits.append("gpu=" + (r.stdout or "").strip())
    except Exception:
        pass
    return " | ".join(bits) or "(no diagnostics available)"


@contextmanager
def progress_watchdog(label: str, stall_seconds: float = 120.0,
                      base_url: str | None = None):
    """Yield a ``tick`` callable; log loudly if it goes quiet."""
    last = [time.monotonic()]
    count = [0]
    stop = threading.Event()
    lock = threading.Lock()

    def tick() -> None:
        with lock:
            last[0] = time.monotonic()
            count[0] += 1

    def watch() -> None:
        warned = False
        while not stop.wait(10.0):
            idle = time.monotonic() - last[0]
            if idle >= stall_seconds:
                log.error("[%s] STALLED: no progress for %.0fs after %d "
                          "completions — %s", label, idle, count[0],
                          _snapshot(base_url))
                warned = True
            elif warned:
                log.warning("[%s] recovered after a stall (%d completions)",
                            label, count[0])
                warned = False

    t = threading.Thread(target=watch, daemon=True, name=f"watchdog-{label}")
    t.start()
    try:
        yield tick
    finally:
        stop.set()
