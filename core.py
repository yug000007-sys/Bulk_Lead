"""
core.py — HYDAC Lead Formatter engine (no Streamlit, no API keys needed).

Everything here works fully offline:
- the 54-column HYDAC Excel header
- building / cleaning rows
- exporting one Excel for many records at once
- a CSV template for bulk entry + reading uploaded CSV/Excel files
- merging PDFs and images into a single PDF
"""

from __future__ import annotations

import io
import re
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from openpyxl import Workbook

# ── The official HYDAC lead header (54 columns, order matters) ─────────────────
EXCEL_HEADER: List[str] = [
    "Referral", "Brand", "Product", "ReceivedDateTime", "FirstName", "LastName",
    "ContactTitle", "Email", "Company", "Address", "County", "City", "State",
    "ZipCode", "Country", "LeadSource1", "LeadSource2", "LeadSource3",
    "LeadComments", "Summary", "PhoneSupplied", "PhSuppliedExtension", "PhoneResearched",
    "CSRName", "PDF", "DUNS", "WebAddress", "Linkedin_Title", "Linkedin_Link",
    "SIC", "NAICS", "noOfEmployees", "ParentName", "LineOfBusiness", "PQ",
    "Latitude", "Longitude", "DemoLead", "ScreenReason", "about_me", "college_1",
    "college_1_degree", "college_1_start", "college_1_end", "college_2",
    "college_2_degree", "college_2_start", "college_2_end", "month_of_joining",
    "about_experience", "searched_on_google", "linkedin_city", "linkedin_state",
    "linkedin_country",
]

# The columns most people actually fill in by hand. These drive the manual form,
# the dashboard grid and the downloadable CSV template. Everything else stays in
# the export but is left blank unless provided.
PRIMARY_COLS: List[str] = [
    "FirstName", "LastName", "ContactTitle", "Email", "Company",
    "Address", "City", "State", "ZipCode", "Country",
    "PhoneSupplied", "WebAddress", "Product", "Brand", "PQ",
    "LeadSource1", "LeadSource2", "LeadSource3",
    "LeadComments", "Summary", "ReceivedDateTime", "PDF", "CSRName",
]

LEAD_SOURCE_COLS = ["LeadSource1", "LeadSource2", "LeadSource3"]


def new_row(**values) -> Dict[str, str]:
    """Return a full 54-key row, blank by default, updated with any given values."""
    row = {h: "" for h in EXCEL_HEADER}
    for k, v in values.items():
        if k in row and v is not None:
            row[k] = str(v)
    return row


# ── Reading uploaded tables (bulk entry) ───────────────────────────────────────

def _norm(name: str) -> str:
    """Loose, case/space-insensitive key for matching column names."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# precompute a lookup from normalised header -> canonical header
_HEADER_LOOKUP = {_norm(h): h for h in EXCEL_HEADER}


def coerce_row(raw: Dict, lead_defaults: Dict[str, str] | None = None) -> Dict[str, str]:
    """Map an arbitrary input dict onto the full HYDAC header.

    Column names are matched loosely (case / spaces / punctuation ignored), so
    'Lead Source 1', 'leadsource1' and 'LEADSOURCE1' all land in LeadSource1.
    Unknown columns are ignored. Missing columns stay blank.
    lead_defaults fills LeadSource1/2/3 only when the row left them empty.
    """
    row = new_row()
    for key, val in (raw or {}).items():
        canon = _HEADER_LOOKUP.get(_norm(key))
        if canon and val is not None and str(val).strip().lower() != "nan":
            row[canon] = str(val).strip()
    if lead_defaults:
        for col in LEAD_SOURCE_COLS:
            if not row[col] and lead_defaults.get(col):
                row[col] = str(lead_defaults[col]).strip()
    return row


def read_table(file_bytes: bytes, filename: str) -> List[Dict[str, str]]:
    """Read an uploaded CSV / XLSX into a list of raw dicts (all values as text)."""
    ext = Path(filename).suffix.lower()
    bio = BytesIO(file_bytes)
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(bio, dtype=str)
    else:
        # tolerate odd encodings in CSV exports
        try:
            df = pd.read_csv(bio, dtype=str)
        except UnicodeDecodeError:
            bio.seek(0)
            df = pd.read_csv(bio, dtype=str, encoding="latin-1")
    df = df.fillna("")
    return df.to_dict(orient="records")


def csv_template_bytes() -> bytes:
    """A ready-to-fill CSV template using the primary columns, with one example row."""
    example = {
        "FirstName": "John", "LastName": "Smith", "ContactTitle": "Purchasing Manager",
        "Email": "john.smith@acme.com", "Company": "Acme Corp",
        "Address": "123 Main St", "City": "Hickory", "State": "NC",
        "ZipCode": "28602", "Country": "USA",
        "PhoneSupplied": "1-828-328-1551", "WebAddress": "www.acme.com",
        "Product": "0160 DN 006 BH4HC", "Brand": "HYDAC", "PQ": "15",
        "LeadSource1": "Email", "LeadSource2": "", "LeadSource3": "",
        "LeadComments": "Please quote best price and delivery.",
        "Summary": "Customer requests a quote for 15 filter elements.",
        "ReceivedDateTime": "", "PDF": "", "CSRName": "",
    }
    df = pd.DataFrame([{c: example.get(c, "") for c in PRIMARY_COLS}])
    out = BytesIO()
    df.to_csv(out, index=False)
    return out.getvalue()


# ── Excel export (many records at once) ────────────────────────────────────────

def make_excel(rows: List[Dict]) -> bytes:
    """Export a list of rows to one Excel file in the HYDAC header format."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(EXCEL_HEADER)
    for r in rows:
        ws.append([r.get(h, "") for h in EXCEL_HEADER])
    for col in ws.columns:
        letter = col[0].column_letter
        width = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[letter].width = min(width + 2, 45)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ── Merge PDFs + images into a single PDF ──────────────────────────────────────

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTS = {".pdf"}
MERGEABLE_EXTS = IMAGE_EXTS | PDF_EXTS


def _image_to_pdf_bytes(data: bytes) -> bytes | None:
    """Convert a single image to a one-page PDF using Pillow."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PDF", resolution=150)
        return buf.getvalue()
    except Exception:
        return None


def merge_to_pdf(items: List[Tuple[str, bytes]]) -> bytes | None:
    """Merge a selected, ordered list of (filename, bytes) into one PDF.

    PDFs contribute all their pages; images become one page each. Order is
    preserved exactly as given. Returns PDF bytes, or None if nothing merged.
    """
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    added = 0
    for filename, data in items:
        if not data:
            continue
        ext = Path(filename).suffix.lower()
        try:
            if ext in PDF_EXTS:
                reader = PdfReader(io.BytesIO(data))
                for page in reader.pages:
                    writer.add_page(page)
                    added += 1
            elif ext in IMAGE_EXTS:
                pdf_bytes = _image_to_pdf_bytes(data)
                if pdf_bytes:
                    reader = PdfReader(io.BytesIO(pdf_bytes))
                    for page in reader.pages:
                        writer.add_page(page)
                        added += 1
        except Exception:
            # skip unreadable / corrupt files rather than failing the whole merge
            continue

    if added == 0:
        return None
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _slug(text: str, maxlen: int = 24) -> str:
    """Lowercase, alphanumeric+underscore slug of a company/name for readability."""
    s = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return s[:maxlen] or "lead"


_ISSUED_NAMES: set = set()


def unique_pdf_name(company: str = "", date_str: str = "") -> str:
    """Collision-proof short PDF name: lead_<rand12>.pdf

    Uses a 12-character random hex string — guaranteed unique within the
    session and short enough to be practical. company/date_str are accepted
    for API compatibility but no longer used in the filename.
    """
    import uuid
    while True:
        rand = uuid.uuid4().hex[:12]
        name = f"lead_{rand}.pdf"
        if name not in _ISSUED_NAMES:
            _ISSUED_NAMES.add(name)
            return name


def single_to_pdf(filename: str, data: bytes) -> bytes | None:
    """Turn ONE selected attachment into PDF bytes.

    - an existing PDF is returned unchanged (lossless rename only)
    - an image is wrapped into a one-page PDF
    Returns None if it cannot be converted (e.g. a .dwg/.step that isn't a PDF/image).
    """
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return data
    if ext in IMAGE_EXTS:
        return _image_to_pdf_bytes(data)
    return None


def build_zip(rows: List[Dict], pdfs: Dict[str, bytes], excel_name: str = "leads.xlsx") -> bytes:
    """Bundle the Excel plus every produced PDF into one ZIP.

    rows  : list of full 54-key rows (already carrying their PDF column names)
    pdfs  : mapping of {pdf_filename: pdf_bytes} to include alongside the Excel
    """
    import zipfile
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(excel_name, make_excel(rows))
        for name, data in pdfs.items():
            if name and data:
                z.writestr(name, data)
    return out.getvalue()


# ── Comment → memo-style PDF (parts table) ──────────────────────────────────────

_UM_SET = r"EA|PCS|PCS\.|PC|NOS|NO|SET|SETS|PR|PAIR|PAIRS|UNIT|UNITS|PKT|BOX|ROLL|M|MM|KG|L"
_ROW_RE = re.compile(r"(\d{1,3})\s+(.+?)\s+(\d{1,4})\s+(" + _UM_SET + r")\b", re.I)
_HEADER_RE = re.compile(r"sr\.?\s*no\.?\s+part\s*no\.?\s+description\s+qty\s+um", re.I)


def _split_part_desc(blob: str):
    """Split 'part no + description' into (part_no, description).
    Part no = leading run of tokens made only of digits/hyphens; rest = description.
    """
    toks = blob.split()
    part = []
    i = 0
    while i < len(toks) and re.fullmatch(r"[0-9][0-9\-]*", toks[i]):
        part.append(toks[i])
        i += 1
    if not part and toks:                       # fallback: first token is the part no
        part = [toks[0]]
        i = 1
    return " ".join(part), " ".join(toks[i:])


def parse_parts_table(comment: str):
    """Find a parts/BOM table inside a comment.
    Returns (intro_text, rows) where rows = [(sr, part_no, description, qty, um), ...].
    If fewer than 3 rows are detected, returns (comment, []).
    """
    matches = list(_ROW_RE.finditer(comment or ""))
    if len(matches) < 3:
        return comment, []
    rows = []
    for m in matches:
        sr, blob, qty, um = m.group(1), m.group(2).strip(), m.group(3), m.group(4).upper()
        part_no, desc = _split_part_desc(blob)
        rows.append((sr, part_no, desc, qty, um))
    intro = comment[:matches[0].start()].strip()
    intro = _HEADER_RE.sub("", intro).strip()   # drop a trailing column header
    return intro, rows


def comment_to_pdf(comment: str, title: str = "Request for Quotation",
                   reference: str = "") -> tuple | None:
    """Render a comment (request text + parts table) as a clean memo-style PDF.
    Returns (pdf_bytes, n_items, short_comment) or None on failure.
    short_comment is the request text plus a '(N items — see attached PDF)' pointer.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)

    intro, rows = parse_parts_table(comment or "")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm, title=title)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], fontSize=15, spaceAfter=6, alignment=0)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#666666"), spaceAfter=10)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8.5, leading=11)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")

    story = [Paragraph(title, h)]
    if reference:
        story.append(Paragraph(reference, sub))
    if intro:
        bullets = [b.strip(" *\t") for b in re.split(r"\s*\*\s*|\u2022", intro) if b.strip(" *\t")]
        lead_in = bullets.pop(0) if bullets else ""
        if lead_in:
            story.append(Paragraph(lead_in, body))
        for b in bullets:
            story.append(Paragraph("&bull;&nbsp;&nbsp;" + b, body))
        story.append(Spacer(1, 8))

    n_items = len(rows)
    if rows:
        header = [Paragraph(x, cellb) for x in ("Sr", "Part No", "Description", "Qty", "UM")]
        data = [header] + [[Paragraph(sr, cell), Paragraph(pn, cell),
                            Paragraph(desc, cell), Paragraph(qty, cell), Paragraph(um, cell)]
                           for (sr, pn, desc, qty, um) in rows]
        col_w = [12 * mm, 34 * mm, 90 * mm, 14 * mm, 14 * mm]
        tbl = Table(data, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (3, 0), (4, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F6F6")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)

    try:
        doc.build(story)
    except Exception:
        return None

    short = intro or (comment or "").strip()
    if n_items:
        short = (short + f"  ({n_items} items — see attached PDF)").strip()
    return buf.getvalue(), n_items, short


def inline_images_to_pdf(inline_image_labels: list, request_text: str = "",
                         title: str = "Customer Request") -> bytes | None:
    """Build a memo-style PDF from inline email images with their labels.

    Each image gets its own page with its label text printed above it.
    A final text-only page carries the customer's request text (if any).
    Returns PDF bytes or None on failure.

    inline_image_labels: list of (image_bytes, label_text) in document order.
    request_text: the customer's verbatim request (LeadComments).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Image as RLImage, PageBreak)
    import io as _io
    from PIL import Image as PILImage

    if not inline_image_labels and not request_text:
        return None

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=16*mm, rightMargin=16*mm,
                            title=title)
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle("h", parent=styles["Title"], fontSize=14,
                              spaceAfter=4, alignment=0)
    label_style = ParagraphStyle("lbl", parent=styles["Normal"], fontSize=10,
                                 textColor=colors.HexColor("#1a4f8a"),
                                 spaceAfter=6, leading=14)
    body_style = ParagraphStyle("body", parent=styles["Normal"], fontSize=10,
                                leading=14, spaceAfter=4)

    # Page width available for images
    page_w = A4[0] - 32*mm
    page_h = A4[1] - 40*mm   # leave room for label + margins

    story = []
    story.append(Paragraph(title, h_style))
    story.append(Spacer(1, 4*mm))

    for idx, (img_bytes, label) in enumerate(inline_image_labels):
        if not img_bytes:
            continue
        # Label text above image
        if label:
            # Clean up label — remove excessive whitespace, keep meaningful tokens
            clean_label = " ".join(label.split())
            story.append(Paragraph(clean_label, label_style))

        # Convert image, fit within page
        try:
            pil_img = PILImage.open(_io.BytesIO(img_bytes))
            if pil_img.mode in ("RGBA", "P", "LA"):
                pil_img = pil_img.convert("RGB")
            elif pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            orig_w, orig_h = pil_img.size
            # Scale to fit page width; cap height too
            scale = min(page_w / orig_w, page_h / orig_h, 1.0)
            draw_w = orig_w * scale
            draw_h = orig_h * scale
            img_buf = _io.BytesIO()
            pil_img.save(img_buf, format="JPEG", quality=85)
            img_buf.seek(0)
            story.append(RLImage(img_buf, width=draw_w, height=draw_h))
        except Exception:
            story.append(Paragraph(f"[image {idx+1} could not be rendered]", body_style))

        story.append(PageBreak())

    # Final page: customer request text
    if request_text and request_text.strip():
        story.append(Paragraph("Customer Request", h_style))
        story.append(Spacer(1, 4*mm))
        for line in request_text.strip().splitlines():
            line = line.strip()
            if line:
                story.append(Paragraph(line, body_style))

    # Remove trailing PageBreak if last item is one
    while story and isinstance(story[-1], PageBreak):
        story.pop()

    try:
        doc.build(story)
    except Exception:
        return None

    return buf.getvalue()


def combine_pdfs(parts: List[Tuple[str, bytes]]) -> bytes | None:
    """Combine an ordered list of (filename, bytes) — PDFs and images — into one PDF.
    The comment PDF is just the first item; images are wrapped, PDFs appended."""
    return merge_to_pdf(parts)
