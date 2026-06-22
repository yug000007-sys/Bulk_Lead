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
    """Collision-proof PDF name: lead_<slug>_<YYYYMMDD>_<HHMMSS>_<rand>.pdf

    Uses a timestamp plus a random suffix, and also remembers every name handed
    out this session, regenerating on the rare clash — so no two files ever
    share a name, even within the same second or across repeated batches.
    """
    import time
    import uuid
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[\sT](\d{2}):(\d{2}):?(\d{2})?", date_str or "")
    if m:
        y, mo, d, h, mi, s = m.groups()
        stamp = f"{y}{mo}{d}_{h}{mi}{s or '00'}"
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
    while True:
        rand = uuid.uuid4().hex[:8]
        name = f"lead_{_slug(company)}_{stamp}_{rand}.pdf"
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
