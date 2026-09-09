#!/usr/bin/env python3
"""Build the organisation brief as a polished, editable DOCX.

This uses LibreOffice's native Writer API rather than converting the print
HTML. The result retains real headings, paragraphs, lists, tables, page
numbers, and an editable feedback diagram when imported into Google Docs.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.append("/usr/lib/python3/dist-packages")

import uno  # type: ignore  # noqa: E402


NAVY = 0x173B57
TEAL = 0x087E8B
TEAL_DARK = 0x09606D
TEAL_PALE = 0xE7F3F4
BLUE_PALE = 0xEAF0F7
AMBER_PALE = 0xFFF3D8
GREEN_PALE = 0xE8F4EB
GREY_050 = 0xF6F8F9
GREY_100 = 0xEDF1F3
GREY_300 = 0xCAD4DA
GREY_600 = 0x607582
WHITE = 0xFFFFFF
BLACK = 0x243746

PAGE_BEFORE = uno.Enum("com.sun.star.style.BreakType", "PAGE_BEFORE")
PARAGRAPH_BREAK = uno.getConstantByName(
    "com.sun.star.text.ControlCharacter.PARAGRAPH_BREAK"
)
CENTER = uno.Enum("com.sun.star.style.ParagraphAdjust", "CENTER")
RIGHT = uno.Enum("com.sun.star.style.ParagraphAdjust", "RIGHT")
LEFT = uno.Enum("com.sun.star.style.ParagraphAdjust", "LEFT")


def _property(name: str, value: object):
    item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    item.Name = name
    item.Value = value
    return item


def _set(obj: object, **properties: object) -> None:
    for name, value in properties.items():
        try:
            setattr(obj, name, value)
        except Exception:
            pass


def _plain(value: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"`(.*?)`", r"\1", value)
    return value.strip()


def _metadata(source: str) -> tuple[str, list[str]]:
    lines = source.splitlines()
    title = lines[0].removeprefix("# ").strip()
    start = next(i for i, line in enumerate(lines) if line.startswith("## "))
    return title, lines[start:]


class WriterDocument:
    def __init__(self, doc: object):
        self.doc = doc
        self.text = doc.Text
        self.cursor = self.text.createTextCursor()
        self._configure_styles()
        self._configure_pages()

    def _configure_styles(self) -> None:
        styles = self.doc.StyleFamilies.getByName("ParagraphStyles")
        standard = styles.getByName("Standard")
        line_spacing = uno.createUnoStruct("com.sun.star.style.LineSpacing")
        line_spacing.Mode = 0
        line_spacing.Height = 118
        _set(
            standard,
            CharFontName="Arial",
            CharHeight=10.5,
            CharColor=BLACK,
            ParaLineSpacing=line_spacing,
            ParaBottomMargin=205,
        )

        title = styles.getByName("Title")
        _set(
            title,
            CharFontName="Arial",
            CharHeight=30.0,
            CharWeight=150.0,
            CharColor=NAVY,
            ParaAdjust=CENTER,
            ParaTopMargin=2650,
            ParaBottomMargin=420,
        )
        heading1 = styles.getByName("Heading 1")
        _set(
            heading1,
            CharFontName="Arial",
            CharHeight=17.0,
            CharWeight=150.0,
            CharColor=TEAL_DARK,
            ParaTopMargin=520,
            ParaBottomMargin=220,
            ParaKeepWithNext=True,
        )
        heading2 = styles.getByName("Heading 2")
        _set(
            heading2,
            CharFontName="Arial",
            CharHeight=12.5,
            CharWeight=150.0,
            CharColor=NAVY,
            ParaTopMargin=360,
            ParaBottomMargin=130,
            ParaKeepWithNext=True,
        )

    def _configure_pages(self) -> None:
        page_styles = self.doc.StyleFamilies.getByName("PageStyles")
        normal = page_styles.getByName("Default Page Style")
        _set(
            normal,
            Width=21000,
            Height=29700,
            LeftMargin=2050,
            RightMargin=2050,
            TopMargin=1900,
            BottomMargin=1750,
            HeaderIsOn=True,
            HeaderHeightAuto=True,
            HeaderBodyDistance=450,
            FooterIsOn=True,
            FooterHeightAuto=True,
            FooterBodyDistance=400,
            NumberingType=4,
        )
        header = normal.HeaderText
        header.String = "SNOMED CT, in Any Language"
        hcursor = header.createTextCursor()
        _set(
            hcursor,
            CharFontName="Arial",
            CharHeight=8.0,
            CharColor=GREY_600,
            ParaAdjust=RIGHT,
            ParaBottomMargin=100,
        )
        footer = normal.FooterText
        footer.String = "Organisational brief   •   "
        fcursor = footer.createTextCursor()
        fcursor.gotoEnd(False)
        field = self.doc.createInstance("com.sun.star.text.TextField.PageNumber")
        field.NumberingType = 4
        footer.insertTextContent(fcursor, field, False)
        fcursor.gotoStart(False)
        fcursor.gotoEnd(True)
        _set(
            fcursor,
            CharFontName="Arial",
            CharHeight=8.0,
            CharColor=GREY_600,
            ParaAdjust=RIGHT,
        )

        first = page_styles.getByName("First Page")
        _set(
            first,
            Width=21000,
            Height=29700,
            LeftMargin=2300,
            RightMargin=2300,
            TopMargin=2000,
            BottomMargin=2000,
            HeaderIsOn=False,
            FooterIsOn=False,
            FollowStyle="Default Page Style",
            NumberingType=4,
        )

    def _at_end(self):
        self.cursor.gotoEnd(False)
        return self.cursor

    def _insert_inline(
        self,
        value: str,
        *,
        font: str,
        size: float,
        weight: float,
        color: int,
    ) -> None:
        cursor = self._at_end()
        tokens = re.split(r"(\*\*.*?\*\*|`.*?`)", value)
        for token in tokens:
            if not token:
                continue
            _set(
                cursor,
                CharFontName=font,
                CharHeight=size,
                CharWeight=weight,
                CharColor=color,
                CharBackTransparent=True,
            )
            if token.startswith("**") and token.endswith("**"):
                cursor.CharWeight = 150.0
                token = token[2:-2]
            elif token.startswith("`") and token.endswith("`"):
                cursor.CharFontName = "Liberation Mono"
                cursor.CharHeight = min(size, 9.4)
                cursor.CharBackTransparent = False
                cursor.CharBackColor = GREY_100
                token = token[1:-1]
            self.text.insertString(cursor, token, False)

    def paragraph(
        self,
        value: str,
        *,
        style: str = "Standard",
        before: int | None = None,
        after: int | None = None,
        left: int | None = None,
        first_line: int | None = None,
        adjust: int | None = None,
        break_before: bool = False,
        keep_with_next: bool | None = None,
        page_style: str | None = None,
    ) -> None:
        cursor = self._at_end()
        cursor.ParaStyleName = style
        _set(
            cursor,
            ParaAdjust=LEFT if adjust is None else adjust,
            ParaTopMargin=0 if before is None else before,
            ParaBottomMargin=205 if after is None else after,
            ParaLeftMargin=0 if left is None else left,
            ParaFirstLineIndent=0 if first_line is None else first_line,
            ParaKeepWithNext=False if keep_with_next is None else keep_with_next,
        )
        if break_before:
            cursor.BreakType = PAGE_BEFORE
        if page_style:
            cursor.PageDescName = page_style
        character_style = {
            "Title": ("Arial", 30.0, 150.0, NAVY),
            "Heading 1": ("Arial", 17.0, 150.0, TEAL_DARK),
            "Heading 2": ("Arial", 12.5, 150.0, NAVY),
        }.get(style, ("Arial", 10.5, 100.0, BLACK))
        self._insert_inline(
            value,
            font=character_style[0],
            size=character_style[1],
            weight=character_style[2],
            color=character_style[3],
        )
        self.text.insertControlCharacter(self._at_end(), PARAGRAPH_BREAK, False)

    def title_page(self, title: str) -> None:
        self.paragraph(
            title,
            style="Title",
            adjust=CENTER,
            before=7500,
            after=500,
            keep_with_next=True,
            page_style="First Page",
        )
        cursor = self._at_end()
        _set(
            cursor,
            CharFontName="Arial",
            CharHeight=18.0,
            CharColor=TEAL,
            ParaAdjust=CENTER,
            ParaTopMargin=50,
            ParaBottomMargin=0,
        )
        self.text.insertString(cursor, "━━━━━━━━━━━━", False)
        self.text.insertControlCharacter(self._at_end(), PARAGRAPH_BREAK, False)

    def section_heading(self, value: str, level: int, *, break_before: bool = False) -> None:
        self.paragraph(
            value,
            style="Heading 1" if level == 2 else "Heading 2",
            before=480 if level == 2 else 320,
            after=190 if level == 2 else 120,
            break_before=break_before,
            keep_with_next=True,
        )

    def bullet(self, value: str) -> None:
        self.paragraph(f"•  {value}", left=700, first_line=-420, before=0, after=90)

    def numbered(self, number: str, value: str) -> None:
        self.paragraph(
            f"{number}.  {value}", left=760, first_line=-500, before=0, after=100
        )

    def callout(self, value: str, *, color: int = TEAL_PALE, border: int = TEAL) -> None:
        table = self._new_table(1, 1)
        cell = table.getCellByName("A1")
        self._format_cell(cell, value, background=color, bold=False, color=NAVY)
        self._table_borders(table, border, width=28)
        self._after_table(170)

    def code_block(self, value: str) -> None:
        table = self._new_table(1, 1)
        cell = table.getCellByName("A1")
        cell.String = value
        ccursor = cell.Text.createTextCursor()
        ccursor.gotoEnd(True)
        _set(
            ccursor,
            CharFontName="Liberation Mono",
            CharHeight=8.8,
            CharColor=BLACK,
            ParaBottomMargin=0,
        )
        _set(cell, BackColor=GREY_100, BackTransparent=False)
        self._table_borders(table, GREY_300, width=18)
        self._after_table(180)

    def _new_table(self, rows: int, columns: int):
        table = self.doc.createInstance("com.sun.star.text.TextTable")
        table.initialize(rows, columns)
        _set(table, IsWidthRelative=True, RelativeWidth=100, Split=False)
        self.text.insertTextContent(self._at_end(), table, False)
        return table

    def _format_cell(
        self,
        cell: object,
        value: str,
        *,
        background: int,
        bold: bool,
        color: int,
        size: float = 9.5,
        align: int = LEFT,
    ) -> None:
        cell.String = _plain(value)
        _set(
            cell,
            BackColor=background,
            BackTransparent=False,
            VertOrient=0,
            LeftBorderDistance=150,
            RightBorderDistance=150,
            TopBorderDistance=120,
            BottomBorderDistance=120,
        )
        ccursor = cell.Text.createTextCursor()
        ccursor.gotoEnd(True)
        _set(
            ccursor,
            CharFontName="Arial",
            CharHeight=size,
            CharWeight=150.0 if bold else 100.0,
            CharColor=color,
            ParaAdjust=align,
            ParaBottomMargin=0,
            ParaTopMargin=0,
        )

    def _table_borders(self, table: object, color: int, *, width: int) -> None:
        try:
            line = uno.createUnoStruct("com.sun.star.table.BorderLine2")
            line.Color = color
            line.LineWidth = width
            border = table.TableBorder2
            for edge in (
                "TopLine",
                "BottomLine",
                "LeftLine",
                "RightLine",
                "HorizontalLine",
                "VerticalLine",
            ):
                setattr(border, edge, line)
                setattr(border, f"Is{edge}Valid", True)
            table.TableBorder2 = border
        except Exception:
            pass

    def _after_table(self, margin: int = 200) -> None:
        self.text.insertControlCharacter(self._at_end(), PARAGRAPH_BREAK, False)
        cursor = self._at_end()
        _set(cursor, ParaBottomMargin=margin, ParaTopMargin=0)

    def contents(self, headings: list[str]) -> None:
        self.section_heading("Contents", 2, break_before=True)
        table = self._new_table(len(headings), 2)
        for index, heading in enumerate(headings):
            number = "—" if heading == "Executive summary" else heading.split(".", 1)[0]
            label = heading if heading == "Executive summary" else heading.split(".", 1)[1].strip()
            shade = WHITE if index % 2 == 0 else GREY_050
            self._format_cell(
                table.getCellByName(f"A{index + 1}"),
                number,
                background=shade,
                bold=True,
                color=TEAL,
                size=12.0,
                align=CENTER,
            )
            self._format_cell(
                table.getCellByName(f"B{index + 1}"),
                label,
                background=shade,
                bold=True,
                color=NAVY,
                size=10.5,
            )
        try:
            separators = table.TableColumnSeparators
            separators[0].Position = 1500
            table.TableColumnSeparators = separators
        except Exception:
            pass
        self._table_borders(table, GREY_300, width=12)
        self._after_table(0)

    def data_table(self, rows: list[list[str]]) -> None:
        table = self._new_table(len(rows), len(rows[0]))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                cell_name = f"{chr(65 + column_index)}{row_index + 1}"
                is_header = row_index == 0
                full_bold = value.startswith("**") and value.endswith("**")
                shade = TEAL_DARK if is_header else (GREY_050 if row_index % 2 == 0 else WHITE)
                self._format_cell(
                    table.getCellByName(cell_name),
                    value,
                    background=shade,
                    bold=is_header or full_bold,
                    color=WHITE if is_header else BLACK,
                    size=8.8 if len(rows[0]) >= 4 else 9.2,
                    align=CENTER if is_header else LEFT,
                )
        self._table_borders(table, GREY_300, width=14)
        self._after_table(210)

    def feedback_flow(self) -> None:
        self.section_heading(
            "Default SME feedback loop for improving the translation agent", 3
        )
        table = self._new_table(2, 3)
        cells = [
            ("A1", "1. Translate a fresh subset  →\nUse a representative, previously unseen concept sample.", TEAL_PALE),
            ("B1", "2. Run the translation agent  →\nApply the current prompt, guide, rules, retrieval pool, and model.", TEAL_PALE),
            ("C1", "3. SME review  ↓\nRate quality, supply canonical translations, and explain recurring problems.", AMBER_PALE),
            ("A2", "6. Held-out quality gate\nTest the revised agent on fresh concepts using SME-aligned measures.", BLUE_PALE),
            ("B2", "←  5. Improve the agent\nApply deterministic fixes first; use GEPA for remaining prompt-sensitive issues.", TEAL_PALE),
            ("C2", "←  4. Convert feedback into assets\nUpdate gold data, rules, style guidance, glossary, and retrieval examples.", TEAL_PALE),
        ]
        for name, value, shade in cells:
            self._format_cell(
                table.getCellByName(name),
                value,
                background=shade,
                bold=False,
                color=NAVY,
                size=8.9,
            )
        self._table_borders(table, TEAL, width=18)
        self._after_table(100)
        self.callout(
            "Quality gate not met  ↺  Repeat from step 1 with another fresh subset.",
            color=AMBER_PALE,
            border=0xD39A32,
        )
        self.callout(
            "Quality gate met  →  Freeze the versioned flow  →  broader production run  →  final SME sign-off.",
            color=GREEN_PALE,
            border=0x5A9968,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        properties = self.doc.DocumentProperties
        properties.Title = "SNOMED CT, in Any Language: AI-Assisted Translation with SME Feedback"
        properties.Subject = "Organisational brief for an AI-assisted SNOMED CT translation programme"
        self.doc.storeAsURL(
            uno.systemPathToFileUrl(str(path.resolve())),
            (_property("FilterName", "Office Open XML Text"), _property("Overwrite", True)),
        )


def _connect(profile: Path):
    pipe_name = f"snomed_docx_{os.getpid()}"
    process = subprocess.Popen(
        [
            "libreoffice",
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            f"--accept=pipe,name={pipe_name};urp;StarOffice.ComponentContext",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--norestore",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    last_error: Exception | None = None
    for _ in range(80):
        try:
            context = resolver.resolve(
                f"uno:pipe,name={pipe_name};urp;StarOffice.ComponentContext"
            )
            return process, context
        except Exception as error:
            last_error = error
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError("Could not connect to LibreOffice") from last_error


def _parse_body(writer: WriterDocument, lines: list[str]) -> None:
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            writer.paragraph(" ".join(part.strip() for part in paragraph))
            paragraph.clear()

    index = 0
    first_heading = True
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            flush()
            index += 1
            continue
        if line.startswith("<figure class=\"feedback-flow\""):
            flush()
            while index < len(lines) and "</figure>" not in lines[index]:
                index += 1
            writer.feedback_flow()
            index += 1
            continue
        if line.startswith("## "):
            flush()
            writer.section_heading(line[3:].strip(), 2, break_before=first_heading)
            first_heading = False
            index += 1
            continue
        if line.startswith("### "):
            flush()
            writer.section_heading(line[4:].strip(), 3)
            index += 1
            continue
        if line.startswith("> "):
            flush()
            quote = [line[2:].strip()]
            index += 1
            while index < len(lines) and lines[index].startswith("> "):
                quote.append(lines[index][2:].strip())
                index += 1
            writer.callout(" ".join(quote))
            continue
        if line.startswith("```"):
            flush()
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            writer.code_block("\n".join(code))
            index += 1
            continue
        if line.startswith("|"):
            flush()
            raw_rows: list[str] = []
            while index < len(lines) and lines[index].startswith("|"):
                raw_rows.append(lines[index])
                index += 1
            rows = [
                [cell.strip() for cell in row.strip().strip("|").split("|")]
                for row in raw_rows
                if not re.match(r"^\|[\s:|-]+\|$", row)
            ]
            writer.data_table(rows)
            continue
        bullet = re.match(r"^-\s+(.*)$", line)
        if bullet:
            flush()
            writer.bullet(bullet.group(1))
            index += 1
            continue
        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if numbered:
            flush()
            writer.numbered(numbered.group(1), numbered.group(2))
            index += 1
            continue
        paragraph.append(line)
        index += 1
    flush()


def build(markdown_path: Path, docx_path: Path) -> None:
    source = markdown_path.read_text(encoding="utf-8")
    title, body_lines = _metadata(source)
    headings = [line[3:].strip() for line in body_lines if line.startswith("## ")]

    with tempfile.TemporaryDirectory(prefix="snomed-docx-") as profile_name:
        process, context = _connect(Path(profile_name))
        doc = None
        try:
            desktop = context.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", context
            )
            doc = desktop.loadComponentFromURL(
                "private:factory/swriter", "_blank", 0, (_property("Hidden", True),)
            )
            writer = WriterDocument(doc)
            writer.title_page(title)
            writer.contents(headings)
            _parse_body(writer, body_lines)
            writer.save(docx_path)
        finally:
            if doc is not None:
                doc.close(True)
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("docx", type=Path)
    args = parser.parse_args()
    build(args.markdown, args.docx)


if __name__ == "__main__":
    main()
