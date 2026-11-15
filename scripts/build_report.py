"""Render the submission R&D report with ReportLab."""
from html import escape
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
NAVY = HexColor("#18354A")


def page_footer(canvas, document):
    canvas.setStrokeColor(HexColor("#CBD8DE"))
    canvas.line(62, 46, A4[0] - 62, 46)
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(62, 31, "GIGBID  /  AI-4016")
    canvas.drawRightString(A4[0] - 62, 31, f"{document.page:02d}")


def main():
    source = ROOT / "docs" / "RD_REPORT.md"
    target = source.with_name("GigBid-RD-Report.pdf")
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=10.6, leading=16,
                          textColor=HexColor("#1D2731"), spaceAfter=10)
    title = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=32, leading=36,
                           textColor=NAVY, spaceAfter=7)
    heading = ParagraphStyle("Heading", fontName="Helvetica-Bold", fontSize=13, leading=18,
                             textColor=NAVY, spaceBefore=12, spaceAfter=5, keepWithNext=True)
    blocks = []
    for block in source.read_text(encoding="utf-8").strip().split("\n\n"):
        if block.startswith("|"):
            lines = block.splitlines()
            cells = [[Paragraph(escape(cell.strip()), body) for cell in line.strip("|").split("|")]
                     for line in [lines[0], *lines[2:]]]
            width = A4[0] - 124
            columns = [width * .34] + [width * .66 / (len(cells[0]) - 1)] * (len(cells[0]) - 1)
            blocks.append(Table(cells, colWidths=columns, repeatRows=1, style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#EAF0F5")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, HexColor("#CBD8DE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]), spaceAfter=10))
            continue
        style = title if block.startswith("# ") else heading if block.startswith("## ") else body
        blocks.append(Paragraph(escape(block.lstrip("# ").strip()).replace("\n", " "), style))
    report = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=62, rightMargin=62,
                               topMargin=66, bottomMargin=60, title="GigBid | AI-4016 R&D review")
    report.build(blocks, onFirstPage=page_footer, onLaterPages=page_footer)
    pages = PdfReader(target).pages
    if not 1 <= len(pages) <= 10:
        raise RuntimeError(f"Expected at most ten report pages. Got {len(pages)}.")
    print(f"Wrote {target.relative_to(ROOT)} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
