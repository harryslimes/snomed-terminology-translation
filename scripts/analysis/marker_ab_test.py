#!/usr/bin/env python
import argparse
import csv
import difflib
import os
import random
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader


DEFAULT_MIN_PROCESSORS = [
    "marker.processors.order.OrderProcessor",
    "marker.processors.block_relabel.BlockRelabelProcessor",
    "marker.processors.line_merge.LineMergeProcessor",
    "marker.processors.list.ListProcessor",
    "marker.processors.page_header.PageHeaderProcessor",
    "marker.processors.sectionheader.SectionHeaderProcessor",
    "marker.processors.table.TableProcessor",
    "marker.processors.text.TextProcessor",
    "marker.processors.footnote.FootnoteProcessor",
    "marker.processors.ignoretext.IgnoreTextProcessor",
    "marker.processors.line_numbers.LineNumbersProcessor",
    "marker.processors.blank_page.BlankPageProcessor",
]


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


def _has_text_layer(pdf_path: Path, max_pages: int, min_chars: int) -> bool:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return False
    page_count = min(max_pages, len(reader.pages))
    for i in range(page_count):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            text = ""
        if len(text.strip()) >= min_chars:
            return True
    return False


def _run_marker_single(
    pdf_path: Path,
    output_dir: Path,
    processors: list[str],
    output_format: str,
    disable_image_extraction: bool,
    disable_ocr: bool,
    page_range: str | None,
):
    cmd = [
        "marker_single",
        str(pdf_path),
        "--output_dir",
        str(output_dir),
        "--output_format",
        output_format,
        "--processors",
        ",".join(processors),
    ]
    if disable_image_extraction:
        cmd.append("--disable_image_extraction")
    if disable_ocr:
        cmd.append("--disable_ocr")
    if page_range:
        cmd.extend(["--page_range", page_range])
    subprocess.run(cmd, check=True)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)
    return text


def _strip_sections(lines: list[str]) -> list[str]:
    keywords = (
        "references",
        "reference",
        "additional information",
        "additional info",
        "lisainfo",
        "viited",
        "allikad",
        "kasutatud kirjandus",
        "kirjandus",
        "used literature",
        "bibliography",
        "version",
        "koostaja",
        "author",
        "authors",
        "contact",
        "kontakt",
        "телефон",
        "контакты",
        "ссылки",
        "литература",
    )
    out = []
    skip = False
    skip_level = None
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip().lower()
            if skip and level <= (skip_level or level):
                skip = False
                skip_level = None
            if not skip and any(k in title for k in keywords):
                skip = True
                skip_level = level
                continue
        if skip:
            continue
        out.append(line)
    return out


def _clean_marker_text(text: str) -> str:
    text = _strip_markdown(text)
    lines = text.splitlines()
    lines = _strip_sections(lines)
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            cleaned.append("")
            continue
        if re.search(r"_page_\d+_Picture_\d+\.(png|jpe?g)", line, re.I):
            continue
        if re.search(r"https?://|www\.", line, re.I):
            continue
        if re.search(r"\b\w+@\w+\.", line):
            continue
        if re.search(
            r"\b(koostaja|author|authors|viited|allikad|references|literature)\b",
            line,
            re.I,
        ) and len(line) < 200:
            continue
        if re.search(r"(tel|telefon|phone|kontakt)", line, re.I) and re.search(
            r"\+?\d[\d\s().-]{6,}", line
        ):
            continue
        if re.match(r"^[-_=]{4,}$", line):
            continue
        cleaned.append(line)
    return _normalize("\n".join(cleaned))


def _marker_output_path(output_dir: Path, pdf_path: Path, ext: str) -> Path:
    stem = pdf_path.stem
    return output_dir / stem / f"{stem}.{ext}"


def _write_compare(
    pairs,
    marker_clean_dir: Path,
    compare_dir: Path,
    output_format: str,
):
    compare_dir.mkdir(parents=True, exist_ok=True)
    compare_csv = compare_dir / "compare.csv"
    ext = "md" if output_format == "markdown" else output_format

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
            marker_path = marker_clean_dir / f"{stem}.{ext}"
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

            baseline_raw = txt.read_text(encoding="utf-8", errors="replace")
            marker_raw = marker_path.read_text(encoding="utf-8", errors="replace")

            baseline = _normalize(baseline_raw)
            marker = _normalize(marker_raw)

            ratio = difflib.SequenceMatcher(None, baseline, marker).ratio()
            base_tokens = set(re.findall(r"\w+", baseline.lower()))
            marker_tokens = set(re.findall(r"\w+", marker.lower()))
            union = base_tokens | marker_tokens
            jaccard = (len(base_tokens & marker_tokens) / len(union)) if union else 0.0

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
        description="Run A/B test for Marker with minimal processors + cleanup."
    )
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--text-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output-format", default="markdown")
    parser.add_argument("--page-range", type=str)
    parser.add_argument("--disable-image-extraction", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--max-pages-check", type=int, default=3)
    parser.add_argument("--text-layer-min-chars", type=int, default=30)
    parser.add_argument("--processors", type=str)
    args = parser.parse_args()

    pdf_dir = args.pdf_dir
    text_dir = args.text_dir or pdf_dir
    out_dir = args.out_dir or Path("data/marker_outputs") / f"{pdf_dir.name}_minproc"
    marker_out_dir = out_dir / "marker"
    marker_clean_dir = out_dir / "marker_clean"
    compare_dir = out_dir / "compare"

    pairs = _list_pdf_text_pairs(pdf_dir, text_dir, args.recursive)
    if not pairs:
        raise SystemExit("No PDF + text pairs found for the provided paths.")

    pairs = _pick_subset(pairs, args.limit, args.seed)

    processors = (
        [p.strip() for p in args.processors.split(",") if p.strip()]
        if args.processors
        else DEFAULT_MIN_PROCESSORS
    )

    marker_out_dir.mkdir(parents=True, exist_ok=True)
    marker_clean_dir.mkdir(parents=True, exist_ok=True)

    for pdf, _ in pairs:
        stem = pdf.stem
        marker_path = _marker_output_path(marker_out_dir, pdf, "md")
        if args.skip_existing and marker_path.exists():
            pass
        else:
            has_text_layer = _has_text_layer(
                pdf, args.max_pages_check, args.text_layer_min_chars
            )
            _run_marker_single(
                pdf_path=pdf,
                output_dir=marker_out_dir,
                processors=processors,
                output_format=args.output_format,
                disable_image_extraction=args.disable_image_extraction,
                disable_ocr=has_text_layer,
                page_range=args.page_range,
            )

        if marker_path.exists():
            raw = marker_path.read_text(encoding="utf-8", errors="replace")
            cleaned = _clean_marker_text(raw)
            cleaned_path = marker_clean_dir / f"{stem}.md"
            cleaned_path.write_text(cleaned, encoding="utf-8")

    _write_compare(
        pairs=pairs,
        marker_clean_dir=marker_clean_dir,
        compare_dir=compare_dir,
        output_format=args.output_format,
    )


if __name__ == "__main__":
    main()
