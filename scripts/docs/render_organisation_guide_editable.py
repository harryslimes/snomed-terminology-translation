#!/usr/bin/env python3
"""Render the organisation guide as HTML suitable for DOCX conversion.

The print renderer uses CSS layout that browsers reproduce well but office
applications do not.  This renderer keeps the document semantic and replaces
the SME feedback diagram with a styled HTML table, so headings, lists, tables,
and every part of the diagram remain editable after LibreOffice converts the
HTML to DOCX or Google Docs imports it.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

import markdown

from render_organisation_guide import _metadata


FLOW_TABLE = """
<h3 class="flow-heading">Default SME feedback loop for improving the translation agent</h3>
<table class="feedback-flow" aria-label="Default SME feedback loop for improving the translation agent">
  <tr>
    <td class="flow-step"><b>1. Translate a fresh subset</b><br>Use a representative, previously unseen concept sample.</td>
  </tr>
  <tr><td class="flow-arrow">&#8595;</td></tr>
  <tr><td class="flow-step"><b>2. Run the translation agent</b><br>Apply the current prompt, guide, rules, retrieval pool, and model.</td></tr>
  <tr><td class="flow-arrow">&#8595;</td></tr>
  <tr><td class="flow-step flow-sme"><b>3. SME review</b><br>Rate quality, supply canonical translations, and explain recurring problems.</td></tr>
  <tr><td class="flow-arrow">&#8595;</td></tr>
  <tr><td class="flow-step"><b>4. Convert feedback into assets</b><br>Update gold data, rules, style guidance, glossary, and retrieval examples.</td></tr>
  <tr><td class="flow-arrow">&#8595;</td></tr>
  <tr><td class="flow-step"><b>5. Improve the agent</b><br>Apply deterministic fixes first; use GEPA for remaining prompt-sensitive issues.</td></tr>
  <tr><td class="flow-arrow">&#8595;</td></tr>
  <tr>
    <td class="flow-step flow-gate"><b>6. Held-out quality gate</b><br>Test the revised agent on fresh concepts using SME-aligned measures.</td>
  </tr>
  <tr>
    <td class="flow-outcome flow-loop"><b>Quality gate not met:</b> repeat from step 1 with another fresh subset. &#8634;</td>
  </tr>
  <tr>
    <td class="flow-outcome flow-promote"><b>Quality gate met:</b> freeze the versioned flow &#8594; broader production run &#8594; final SME sign-off.</td>
  </tr>
</table>
"""


EDITABLE_CSS = """
@page { size: A4; margin: 2.2cm; }
body {
  color: #243746;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 11pt;
  line-height: 1.35;
  max-width: 17cm;
  margin: 0 auto;
}
h1 { color: #123b59; font-size: 25pt; line-height: 1.12; margin: 1.5cm 0 0.8cm; }
h2 { color: #0a6074; font-size: 17pt; margin: 1em 0 0.4em; }
h3 { color: #123b59; font-size: 13pt; margin: 0.9em 0 0.3em; }
p { margin: 0 0 0.65em; }
li { margin-bottom: 0.25em; }
blockquote {
  background: #eaf4f6;
  border-left: 5px solid #19a3a5;
  margin: 0.8em 0;
  padding: 0.65em 0.9em;
}
table { border-collapse: collapse; margin: 0.8em 0 1em; width: 100%; }
th {
  background: #0a6074;
  border: 1px solid #d2dce2;
  color: #ffffff;
  padding: 0.45em;
  text-align: left;
}
td { border: 1px solid #d2dce2; padding: 0.45em; vertical-align: top; }
tr:nth-child(even) td { background: #f4f7f8; }
code { background: #eef1f3; padding: 0.05em 0.2em; }
pre { background: #eef1f3; border: 1px solid #d2dce2; padding: 0.7em; }
.contents { background: #f4f7f8; border: 1px solid #d2dce2; padding: 0.4em 1em 0.7em; }
.contents a { color: #0a6074; text-decoration: none; }
.flow-heading {
  color: #123b59;
  font-size: 12pt;
  font-weight: bold;
  page-break-before: always;
}
.feedback-flow { page-break-inside: avoid; }
.feedback-flow td { font-size: 9pt; }
.feedback-flow .flow-step { background: #eaf4f6; border: 1px solid #77b8c2; }
.feedback-flow .flow-sme { background: #fff1d6; border-color: #dfa94b; }
.feedback-flow .flow-gate { background: #e8eef7; border-color: #7695c4; }
.feedback-flow .flow-arrow {
  background: #ffffff;
  border: 0;
  color: #0a6074;
  font-size: 13pt;
  font-weight: bold;
  padding: 0.08em;
  text-align: center;
  vertical-align: middle;
}
.feedback-flow .flow-outcome { border-width: 2px; font-size: 10pt; text-align: center; }
.feedback-flow .flow-loop { background: #fff1d6; border-color: #dfa94b; }
.feedback-flow .flow-promote { background: #e5f3e9; border-color: #6ea77c; }
"""


def render(markdown_path: Path, html_path: Path) -> None:
    source = markdown_path.read_text(encoding="utf-8")
    title, _, body_lines = _metadata(source.splitlines())
    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}},
    )
    body = converter.convert("\n".join(body_lines))
    body, replacements = re.subn(
        r'<figure class="feedback-flow".*?</figure>',
        FLOW_TABLE,
        body,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise ValueError("Expected exactly one SME feedback flow diagram")

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>{EDITABLE_CSS}</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <section class="contents">
    <h2>Contents</h2>
    {converter.toc}
  </section>
  {body}
</body>
</html>
"""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("html", type=Path)
    args = parser.parse_args()
    render(args.markdown, args.html)


if __name__ == "__main__":
    main()
