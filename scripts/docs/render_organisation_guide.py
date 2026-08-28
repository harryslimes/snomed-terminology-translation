#!/usr/bin/env python3
"""Render the organisation-facing Markdown guide to print-ready HTML.

Chromium can then print the HTML to PDF. The source Markdown remains the
authoritative document; this script and the accompanying CSS make the PDF
layout reproducible without committing generated binary files.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

import markdown


def _metadata(lines: list[str]) -> tuple[str, dict[str, str], list[str]]:
    title = lines[0].removeprefix("# ").strip()
    values: dict[str, str] = {}
    body_at = 1
    pattern = re.compile(r"^\*\*(?P<key>[^:]+):\*\*\s*(?P<value>.*?)\s{0,2}$")
    for index, line in enumerate(lines[1:], start=1):
        match = pattern.match(line)
        if match:
            values[match.group("key").lower()] = match.group("value")
        if line.startswith("## "):
            body_at = index
            break
    return title, values, lines[body_at:]


def render(markdown_path: Path, css_path: Path, html_path: Path) -> None:
    source = markdown_path.read_text(encoding="utf-8")
    title, metadata, body_lines = _metadata(source.splitlines())

    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}},
    )
    body = converter.convert("\n".join(body_lines))
    toc = converter.toc

    # Give the three document landmarks intentional print treatment.
    body = body.replace('<h2 id="executive-summary">', '<h2 id="executive-summary">', 1)
    body = re.sub(
        r'(<h2 id="(?:6-ways-to-make-it-available|8-sources-and-notes|11-making-the-platform-available-to-users|12-costs-resources-and-a-managed-service-charging-model|17-sources-and-pricing-notes)")',
        r'\1 class="major-break"',
        body,
    )
    executive_start = body.find('<h2 id="executive-summary">')
    first_numbered_section = re.search(r'<h2 id="1-[^"]+">', body)
    first_section = first_numbered_section.start() if first_numbered_section else -1
    if executive_start >= 0 and first_section > executive_start:
        body = (
            body[:executive_start]
            + '<section class="executive-summary">'
            + body[executive_start:first_section]
            + "</section>"
            + body[first_section:]
        )

    purpose = metadata.get("purpose", "")
    audience = metadata.get("audience", "")
    status = metadata.get("status", "Draft for organisational review")
    subtitle = metadata.get(
        "subtitle",
        "A repeatable, expert-led method for creating, evaluating, and delivering a new SNOMED CT language translation.",
    )
    css = css_path.read_text(encoding="utf-8")

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head>
<body>
  <section class="cover">
    <div class="cover-inner">
      <p class="cover-kicker">Translation programme guide</p>
      <h1>{html.escape(title)}</h1>
      <div class="cover-rule"></div>
      <p class="cover-deck">{html.escape(subtitle)}</p>
      <div class="cover-meta">
        <div><strong>Status</strong> {html.escape(status)}</div>
        <div><strong>Audience</strong> {html.escape(audience)}</div>
        <div><strong>Purpose</strong> {html.escape(purpose)}</div>
      </div>
    </div>
  </section>
  <section class="contents-page">
    <h2>Contents</h2>
    <nav class="toc">{toc}</nav>
  </section>
  <main class="document-body">{body}</main>
</body>
</html>
"""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("html", type=Path)
    parser.add_argument(
        "--css",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs" / "organisation_guide_print.css",
    )
    args = parser.parse_args()
    render(args.markdown, args.css, args.html)


if __name__ == "__main__":
    main()
