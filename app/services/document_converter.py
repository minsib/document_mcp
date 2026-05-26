"""
Document format conversion helpers.
"""
from __future__ import annotations

from io import BytesIO
from typing import List

from docx import Document as DocxDocument
from docx.document import Document as DocxDocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


def convert_docx_to_markdown(file_bytes: bytes) -> str:
    """Convert a DOCX payload into Markdown for downstream splitting."""
    document = DocxDocument(BytesIO(file_bytes))
    lines: List[str] = []

    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            rendered = _render_paragraph(block)
            if rendered:
                lines.extend(rendered)
        elif isinstance(block, Table):
            rendered = _render_table(block)
            if rendered:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.extend(rendered)
                lines.append("")

    markdown = "\n".join(lines).strip()
    return markdown + "\n" if markdown else ""


def _iter_block_items(parent: DocxDocumentType):
    """Yield paragraphs and tables in document order."""
    parent_elm = parent.element.body
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _render_paragraph(paragraph: Paragraph) -> List[str]:
    text = paragraph.text.strip()
    if not text:
        return [""]

    style_name = (paragraph.style.name or "").lower()
    if style_name.startswith("heading"):
        level = _heading_level(paragraph.style.name)
        return [f'{"#" * level} {text}', ""]

    if "list bullet" in style_name:
        return [f"- {text}"]

    if "list number" in style_name:
        return [f"1. {text}"]

    return [text, ""]


def _heading_level(style_name: str) -> int:
    parts = style_name.split()
    for part in reversed(parts):
        if part.isdigit():
            return max(1, min(6, int(part)))
    return 1


def _render_table(table: Table) -> List[str]:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", "<br>") for cell in row.cells]
        if any(cells):
            rows.append(cells)

    if not rows:
        return []

    column_count = max(len(row) for row in rows)
    normalized = [row + [""] * (column_count - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * column_count

    output = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in normalized[1:]:
        output.append("| " + " | ".join(row) + " |")

    return output
