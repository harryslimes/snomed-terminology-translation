"""RunContext — per-invocation state shared by stage runners.

Carries the run_id, output log path, and a cancellation event so background
runners (wizard subprocess driver, future schedulers) can abort gracefully.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunContext:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    log_dir: Path | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def log_path(self) -> Path | None:
        if self.log_dir is None:
            return None
        return self.log_dir / f"{self.run_id}.log"

    def artifacts_dir(self) -> Path | None:
        """Run-scoped artifact directory (immutable run store).

        Stage outputs land here so re-runs never clobber earlier results.
        None when the run has no log_dir (bare CLI invocations) — stages then
        fall back to the shared ``paths.output_dir`` legacy location.
        """
        if self.log_dir is None:
            return None
        d = self.log_dir / "artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()


@dataclass
class StageResult:
    """Returned by each stage runner.

    ``outputs`` is a flat dict of named artifacts the stage produced — keys
    are stable names like ``output_csv`` / ``optimized_style_guide``;
    downstream flow steps reference them via ``$step.<key>``. Values are
    typically Paths but can be anything JSON-serialisable.

    ``output_paths`` is kept for backward compat — it's just the Path-typed
    subset of ``outputs.values()``.
    """

    stage: str
    ok: bool
    outputs: dict[str, object] = field(default_factory=dict)
    output_paths: list[Path] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""
