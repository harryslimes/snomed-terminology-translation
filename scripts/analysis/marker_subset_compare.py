#!/usr/bin/env python
import argparse
import csv
import difflib
import os
import random
import re
import shutil
import subprocess
from pathlib import Path


def _list_pdf_text_pairs(pdf_dir: Path, text_dir: Path, recursive: bool):
    pdfs = pdf_dir.rglob("*.pdf") if recursive else pdf_dir.glob("*.pdf")
    pairs = []
    for pdf in sorted(pdfs):
        stem = pdf.stem
        txt = text_dir / f"{stem}.txt"
        if txt.exists():
            pairs.append((pdf, txt))
    return pairs


def _pick_subset(pairs, limit: int | None, seed: int | None):
    if limit is None or limit >= len(pairs):
        return pairs
    rng = random.Random(seed)
    return rng.sample(pairs, limit)


def _ensure_marker_cli():
    if shutil.which("marker") is None:
        raise SystemExit(
            "marker CLI not found. Install with `pip install marker-pdf`."
        )


def _safe_symlink_or_copy(src: Path, dst: Path):
    try:
        os.symlink(src.resolve(), dst)
    except OSError:
        shutil.copy2(src, dst)


def _prepare_subset_dir(pairs, subset_dir: Path):
    subset_dir.mkdir(parents=True, exist_ok=True)
    for pdf, _ in pairs:
        target = subset_dir / pdf.name
        if target.exists():
            continue
        _safe_symlink_or_copy(pdf, target)


def _run_marker(
    subset_dir: Path,
    output_dir: Path,
    output_format: str,
    disable_image_extraction: bool,
    workers: int | None,
    page_range: str | None,
    skip_existing: bool,
    model_cache_dir: Path | None,
):
    cmd = [
        "marker",
        str(subset_dir),
        "--output_dir",
        str(output_dir),
        "--output_format",
        output_format,
    ]
    if disable_image_extraction:
        cmd.append("--disable_image_extraction")
    if workers is not None:
        cmd.extend(["--workers", str(workers)])
    if page_range:
        cmd.extend(["--page_range", page_range])
    if skip_existing:
        cmd.append("--skip_existing")
    env = os.environ.copy()
    if model_cache_dir is not None:
        env["MODEL_CACHE_DIR"] = str(model_cache_dir)
    subprocess.run(cmd, check=True, env=env)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}(#{1,6}|>|[-*+])\s+", "", text, flags=re.M)
    text = text.replace("|", " ")
    return text


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _token_set(text: str):
    return set(re.findall(r"\w+", text.lower()))


def _compare_texts(base_text: str, marker_text: str):
    ratio = difflib.SequenceMatcher(None, base_text, marker_text).ratio()
    base_tokens = _token_set(base_text)
    marker_tokens = _token_set(marker_text)
    union = base_tokens | marker_tokens
    jaccard = (len(base_tokens & marker_tokens) / len(union)) if union else 0.0
    return ratio, jaccard


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _marker_extension(output_format: str) -> str:
    if output_format == "markdown":
        return "md"
    if output_format in {"json", "chunks"}:
        return "json"
    return "html"


def _prepare_marker_text(raw: str, output_format: str) -> str:
    if output_format == "markdown":
        return _normalize(_strip_markdown(raw))
    if output_format == "html":
        return _normalize(_strip_html(raw))
    return _normalize(raw)


def _write_manifest(pairs, manifest_path: Path):
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pdf_path", "text_path"])
        for pdf, txt in pairs:
            writer.writerow([str(pdf), str(txt)])


def _compare_outputs(
    pairs,
    marker_out_dir: Path,
    compare_dir: Path,
    output_format: str,
):
    compare_dir.mkdir(parents=True, exist_ok=True)
    compare_csv = compare_dir / "compare.csv"
    ext = _marker_extension(output_format)

    with compare_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "pdf",
                "marker_output",
                "baseline_text",
                "char_ratio",
                "token_jaccard",
                "marker_chars",
                "baseline_chars",
            ],
        )
        writer.writeheader()

        for pdf, txt in pairs:
            stem = pdf.stem
            marker_path = marker_out_dir / f"{stem}.{ext}"
            if not marker_path.exists():
                nested_dir = marker_out_dir / stem
                marker_path = nested_dir / f"{stem}.{ext}"
            if not marker_path.exists():
                writer.writerow(
                    {
                        "pdf": str(pdf),
                        "marker_output": str(marker_path),
                        "baseline_text": str(txt),
                        "char_ratio": "",
                        "token_jaccard": "",
                        "marker_chars": "",
                        "baseline_chars": "",
                    }
                )
                continue

            baseline_raw = _read_text(txt)
            marker_raw = _read_text(marker_path)

            baseline = _normalize(baseline_raw)
            marker = _prepare_marker_text(marker_raw, output_format)

            ratio, jaccard = _compare_texts(baseline, marker)

            diff_path = compare_dir / f"{stem}.diff"
            diff_lines = difflib.unified_diff(
                baseline.splitlines(),
                marker.splitlines(),
                fromfile=str(txt),
                tofile=str(marker_path),
                lineterm="",
            )
            diff_path.write_text("\n".join(diff_lines), encoding="utf-8")

            writer.writerow(
                {
                    "pdf": str(pdf),
                    "marker_output": str(marker_path),
                    "baseline_text": str(txt),
                    "char_ratio": f"{ratio:.4f}",
                    "token_jaccard": f"{jaccard:.4f}",
                    "marker_chars": str(len(marker)),
                    "baseline_chars": str(len(baseline)),
                }
            )


def main():
    parser = argparse.ArgumentParser(
        description="Run Marker on a subset of PDFs and compare to existing text."
    )
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--text-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output-format", default="markdown")
    parser.add_argument("--page-range", type=str)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--disable-image-extraction", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compare-only", action="store_true")
    parser.add_argument("--model-cache-dir", type=Path)
    parser.add_argument("--clean-model-cache", action="store_true")
    args = parser.parse_args()

    pdf_dir = args.pdf_dir
    text_dir = args.text_dir or pdf_dir
    out_dir = args.out_dir or Path("data/marker_outputs") / pdf_dir.name
    subset_dir = out_dir / "subset_pdfs"
    marker_out_dir = out_dir / "marker"
    compare_dir = out_dir / "compare"

    if args.clean_model_cache and args.model_cache_dir is None:
        raise SystemExit("--clean-model-cache requires --model-cache-dir.")

    model_cache_dir = None
    if args.model_cache_dir is not None:
        model_cache_dir = args.model_cache_dir.expanduser().resolve()
        if args.clean_model_cache and model_cache_dir.exists():
            shutil.rmtree(model_cache_dir)
        model_cache_dir.mkdir(parents=True, exist_ok=True)

    pairs = _list_pdf_text_pairs(pdf_dir, text_dir, args.recursive)
    if not pairs:
        raise SystemExit("No PDF + text pairs found for the provided paths.")

    pairs = _pick_subset(pairs, args.limit, args.seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(pairs, out_dir / "subset_manifest.csv")

    if not args.compare_only:
        _ensure_marker_cli()
        _prepare_subset_dir(pairs, subset_dir)
        marker_out_dir.mkdir(parents=True, exist_ok=True)
        _run_marker(
            subset_dir=subset_dir,
            output_dir=marker_out_dir,
            output_format=args.output_format,
            disable_image_extraction=args.disable_image_extraction,
            workers=args.workers,
            page_range=args.page_range,
            skip_existing=args.skip_existing,
            model_cache_dir=model_cache_dir,
        )

    _compare_outputs(
        pairs=pairs,
        marker_out_dir=marker_out_dir,
        compare_dir=compare_dir,
        output_format=args.output_format,
    )


if __name__ == "__main__":
    main()
