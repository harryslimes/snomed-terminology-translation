#!/usr/bin/env python
import argparse
import csv
import json
import os
import time
from pathlib import Path

import requests


VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000")
DEFAULT_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head_len = max_chars // 2
    tail_len = max_chars - head_len
    truncated = text[:head_len] + "\n...\n" + text[-tail_len:]
    return truncated, True


def _build_prompt(
    baseline_text: str,
    marker_text: str,
    baseline_truncated: bool,
    marker_truncated: bool,
) -> list[dict]:
    trunc_note = []
    if baseline_truncated:
        trunc_note.append("baseline text truncated")
    if marker_truncated:
        trunc_note.append("marker text truncated")
    trunc_line = f"Note: {', '.join(trunc_note)}." if trunc_note else "Note: no truncation."

    system = (
        "You are a document comparison analyst. Compare baseline extracted text "
        "against Marker output. Provide a subjective analysis focused on: "
        "layout noise removal (headers/footers/sidebar), structure preservation, "
        "missing/extra content, readability, and overall usefulness. "
        "Return concise bullets with sections: Overall, Key Differences, Risks, Recommendation."
    )
    user = (
        f"{trunc_line}\n\n"
        "Baseline extracted text:\n"
        "-----\n"
        f"{baseline_text}\n"
        "-----\n\n"
        "Marker output text:\n"
        "-----\n"
        f"{marker_text}\n"
        "-----"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_content(data: dict) -> str:
    choices = data.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    return message.get("content") or ""


def _call_vllm(
    base_url: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    enable_thinking: bool,
    retries: int,
    backoff: float,
) -> str:
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=300)
            if resp.status_code == 200:
                return _extract_content(resp.json())
            last_error = f"vLLM API error {resp.status_code}: {resp.text}"
        except Exception as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(backoff * (2**attempt))
    raise RuntimeError(last_error or "vLLM API error")


def _wait_for_server(base_url: str, timeout: int) -> None:
    """Block until the vLLM health endpoint responds or timeout is reached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=5)
            if resp.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    raise RuntimeError(
        f"vLLM server at {base_url} did not become ready within {timeout}s"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run subjective LLM analysis on Marker vs baseline text pairs using a local vLLM server."
    )
    parser.add_argument(
        "--compare-csv",
        type=Path,
        default=Path("data/marker_outputs/haiglateliit/compare/compare.csv"),
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("data/marker_outputs/haiglateliit/compare/qwen_subjective.jsonl"),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=VLLM_BASE_URL)
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="Enable Qwen3 thinking mode (<think> blocks).",
    )
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--backoff", type=float, default=5.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--wait-for-server",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait up to N seconds for the vLLM server to become healthy before starting.",
    )
    args = parser.parse_args()

    if args.wait_for_server > 0:
        _wait_for_server(args.base_url, args.wait_for_server)

    if not args.compare_csv.exists():
        raise SystemExit(f"Missing compare.csv at {args.compare_csv}")

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    completed = set()
    if args.output_jsonl.exists() and not args.overwrite:
        for line in args.output_jsonl.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
                pdf = obj.get("pdf")
                if pdf:
                    completed.add(pdf)
            except Exception:
                continue

    with args.compare_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    mode = "w" if args.overwrite or not args.output_jsonl.exists() else "a"
    with args.output_jsonl.open(mode, encoding="utf-8") as out:
        for row in rows:
            if row.get("pdf") in completed:
                continue
            baseline_path = Path(row["baseline_text"])
            marker_path = Path(row["marker_output"])
            pdf_path = row["pdf"]

            record = {
                "pdf": pdf_path,
                "baseline_text": str(baseline_path),
                "marker_output": str(marker_path),
                "model": args.model,
            }

            if not baseline_path.exists() or not marker_path.exists():
                record["error"] = "missing_input_files"
                out.write(json.dumps(record) + "\n")
                continue

            baseline_raw = _read_text(baseline_path)
            marker_raw = _read_text(marker_path)

            baseline_text, baseline_trunc = _truncate_text(
                baseline_raw, args.max_chars
            )
            marker_text, marker_trunc = _truncate_text(marker_raw, args.max_chars)

            messages = _build_prompt(
                baseline_text, marker_text, baseline_trunc, marker_trunc
            )

            try:
                analysis = _call_vllm(
                    base_url=args.base_url,
                    model=args.model,
                    messages=messages,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    enable_thinking=args.enable_thinking,
                    retries=args.retries,
                    backoff=args.backoff,
                )
                record["analysis"] = analysis
                record["baseline_truncated"] = baseline_trunc
                record["marker_truncated"] = marker_trunc
            except Exception as exc:
                record["error"] = str(exc)

            out.write(json.dumps(record) + "\n")
            out.flush()
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
