import re
import base64
import json
from io import BytesIO
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st
import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Image as RLImage, HRFlowable, Table, TableStyle)
from reportlab.lib.enums import TA_LEFT


CLIENTS = [
    "Bravotek",
    "DEI",
    "Heatron",
    "Nisshinbo",
    "Shinelink",
    "Soracom",
    "SunLed",
    "Wall",
    "Winchester",
]


OUTPUT_COLUMNS = [
    "Distname",
    "Supplier_name",
    "direct_indirect",
    "in_out_territory",
    "CustAccNbr",
    "CustDunsID",
    "CustName",
    "Address1",
    "City",
    "State",
    "County",
    "Zip",
    "Phone",
    "Country",
    "NoOfEmployees",
    "WebAddress",
    "SIC",
    "NAICS",
    "LineOfBusiness",
    "ParentName",
    "AccountType",
    "UOM",
    "InvoiceNumber",
    "Qty",
    "UnitCost",
    "UnitResale",
    "InvoiceDate",
    "DateRecieved",
    "PartNumberSubmitted",
    "PartNumberDescription",
    "Branch",
    "SalesRep",
    "Latitude",
    "Longitude",
    "Brand",
    "PartNumberActual",
    "UPCCode",
    "rawcustname",
    "rawdistaddress",
    "rawdistcity",
    "rawdiststate",
    "rawdistpostalcode",
    "rawdistcountry",
    "currency",
    "contractID",
    "client_CustName",
    "Zip_4_digit",
    "dnb_trade_style",
    "dnb_sales_value",
    "google_CustName",
    "google_Address1",
    "google_State",
    "google_Zip",
    "google_Country",
    "google_Phone",
    "google_WebAddress",
    "Pay_Month",
    "Pay_Year",
    "Ship_Month",
    "Ship_Year",
    "Industry",
    "Commissions",
    "Commission_Rate",
    "Cust_AM",
    "CEM",
    "Sales",
    "In_Out",
    "Commission_split_percentage",
    "Distributor_part_number",
    "Category",
    "google_City",
    "Billings",
    "Cheque_Number",
    "Pay_Date",
    "meta_data_json",
    "SO_Number",
    "PO_Number",
    "ship_date",
    "searched_on_google",
]


def set_background_image(image_path):
    try:
        with open(image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode()

        st.markdown(
            f"""
            <style>
            html, body, .stApp {{
                min-height: 100%;
            }}

            .stApp {{
                background-image:
                    linear-gradient(rgba(0, 55, 95, 0.35), rgba(0, 55, 95, 0.35)),
                    url("data:image/png;base64,{encoded_image}");
                background-size: cover;
                background-position: center center;
                background-repeat: no-repeat;
                background-attachment: fixed;
            }}

            [data-testid="stAppViewContainer"],
            [data-testid="stHeader"] {{
                background: transparent;
            }}

            .block-container {{
                background: transparent !important;
                padding-top: 4rem;
                padding-left: 4rem;
                padding-right: 4rem;
                max-width: 95%;
            }}

            h1 {{
                color: white !important;
                font-size: 3.5rem !important;
                font-weight: 800 !important;
                text-shadow: 0 3px 10px rgba(0, 0, 0, 0.45);
            }}

            h2, h3, label, p {{
                color: white !important;
                text-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
            }}

            div[data-baseweb="select"] > div,
            [data-testid="stFileUploader"] section,
            [data-testid="stTextInput"] input {{
                background-color: rgba(255, 255, 255, 0.88) !important;
                border-radius: 10px !important;
            }}

            .stButton > button,
            .stDownloadButton > button {{
                background-color: #159bd3 !important;
                color: white !important;
                border: none !important;
                border-radius: 10px !important;
                font-weight: 700 !important;
                padding: 0.65rem 1.3rem !important;
            }}

            [data-testid="stMetric"],
            [data-testid="stDataFrame"],
            [data-testid="stDataEditor"] {{
                background-color: rgba(255, 255, 255, 0.92);
                border-radius: 12px;
                padding: 0.5rem;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    except FileNotFoundError:
        pass


def blank_row():
    return {column: "" for column in OUTPUT_COLUMNS}


def clean_money(value):
    if value is None:
        return ""

    value = str(value).strip()

    if value in {"", "-"}:
        return ""

    return value.replace("$", "").replace(",", "").replace(" ", "").strip()


def format_date(value):
    value = str(value).strip()

    for date_format in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%m/%d/%Y")
        except ValueError:
            continue

    return value


def normalize_ocr_text(text):
    replacements = {
        "OIGI-KEY": "DIGI-KEY",
        "D1GI-KEY": "DIGI-KEY",
        "INOIVIOUAL": "INDIVIDUAL",
        "IN0IVI0UAL": "INDIVIDUAL",
        "LEONARDO ORS": "LEONARDO DRS",
        "NEVICO": "NEWCO",
        "NEVVCO": "NEWCO",
        "Git": "GI21",
        "GIT": "GI21",
        "GI2I": "GI21",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    return text


def extract_pdf_text(file):
    text = ""

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"

    return text


def extract_pdf_text_with_ocr(file):
    text = extract_pdf_text(file)

    if text.strip():
        return normalize_ocr_text(text)

    try:
        import fitz
        import pytesseract
        from PIL import Image
    except Exception:
        return text

    try:
        file.seek(0)
        pdf_bytes = file.read()
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        ocr_text = []

        for page in document:
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_text.append(
                pytesseract.image_to_string(
                    image,
                    config="--psm 6",
                )
            )

        return normalize_ocr_text("\n".join(ocr_text))
    except Exception:
        return normalize_ocr_text(text)


def process_bravotek(pdf_text):
    rows = []

    row_pattern = re.compile(
        r"^\s*\d+\s+(?P<customer>.*?)\s+(?P<po_no>PO[A-Z0-9]+)\s+(?P<rest>.*)$",
        re.IGNORECASE,
    )

    money_pattern = re.compile(
        r"\$\s*(?P<amount>[0-9,\s]+(?:\.\d{2})?|-)"
    )

    for raw_line in pdf_text.splitlines():
        line = raw_line.strip()

        if not line or "PO" not in line or "$" not in line:
            continue

        match = row_pattern.search(line)

        if not match:
            continue

        amounts = [
            amount_match.group("amount")
            for amount_match in money_pattern.finditer(match.group("rest"))
        ]

        if len(amounts) < 2:
            continue

        row = blank_row()
        row["Supplier_name"] = "Bravotek"
        row["CustName"] = match.group("customer").strip()
        row["PO_Number"] = match.group("po_no").strip()
        row["UnitCost"] = clean_money(amounts[0])
        row["Commissions"] = clean_money(amounts[1])

        rows.append(row)

    return rows, []


def _extract_embedded_date(text):
    digits_and_slashes = "".join(ch for ch in text if ch.isdigit() or ch == "/")
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})$", digits_and_slashes)

    if match:
        return match.group(1)

    return ""


def _remove_embedded_date_characters(text, date_value):
    if not date_value:
        return text.strip()

    chars_to_remove = list(date_value)
    output = []

    for ch in text:
        if chars_to_remove and ch == chars_to_remove[0]:
            chars_to_remove.pop(0)
            continue

        output.append(ch)

    return "".join(output).strip()


def process_heatron(pdf_text):
    rows = []

    for raw_line in pdf_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        upper_line = line.upper()

        if upper_line.startswith("CUSTOMER_ID") or upper_line.startswith("LORENZ SALES"):
            continue

        id_match = re.match(r"^(?P<customer_id>\d+)\s+(?P<remaining>.+)$", line)

        if not id_match:
            continue

        customer_id = id_match.group("customer_id").strip()
        remaining = id_match.group("remaining").strip()

        invoice_match = re.search(r"\s(?P<invoice_id>IN\d+)\s+", remaining, flags=re.IGNORECASE)

        if not invoice_match:
            continue

        before_invoice = remaining[:invoice_match.start()].strip()
        after_invoice = remaining[invoice_match.end():].strip()
        invoice_id = invoice_match.group("invoice_id").strip()

        normal_date_match = re.search(r"(?P<invoice_date>\d{1,2}/\d{1,2}/\d{2,4})$", before_invoice)

        if normal_date_match:
            invoice_date = normal_date_match.group("invoice_date")
            customer_name = before_invoice[:normal_date_match.start()].strip()
        else:
            invoice_date = _extract_embedded_date(before_invoice)
            customer_name = _remove_embedded_date_characters(before_invoice, invoice_date)

        detail_match = re.match(
            r"(?P<amount>[0-9,]+\.\d{2})\s+"
            r"(?P<salesrep_id>\S+)\s+"
            r"(?P<vendor_id>\S+)\s+"
            r"(?P<commission_pct>[0-9]+(?:\.\d+)?)\s+"
            r"(?P<ap_voucher>[0-9,]+\.\d{2})\s*$",
            after_invoice,
            flags=re.IGNORECASE,
        )

        if not detail_match or not invoice_date:
            continue

        row = blank_row()
        row["Supplier_name"] = "Heatron"
        row["CustAccNbr"] = customer_id
        row["CustName"] = customer_name
        row["InvoiceNumber"] = invoice_id
        row["InvoiceDate"] = format_date(invoice_date)
        row["UnitCost"] = clean_money(detail_match.group("amount"))
        row["Commissions"] = clean_money(detail_match.group("ap_voucher"))

        rows.append(row)

    return rows, []


def process_soracom(pdf_text):
    rows = []

    month_pattern = re.compile(
        r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}$",
        re.IGNORECASE,
    )

    customer_pattern = re.compile(
        r"(?P<customer>Carlisle Fluid Technologies|mach\.io)\s+"
        r"(?P<commission_pct>\d+(?:\.\d+)?%)\s+"
        r"\$(?P<unit_cost>[0-9,]+\.\d{2})\s+"
        r"\$(?P<commission>[0-9,]+\.\d{2})",
        re.IGNORECASE,
    )

    current_month = ""

    for raw_line in pdf_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        month_match = month_pattern.match(line)

        if month_match:
            current_month = line
            continue

        if "MONTHLY TOTAL" in line.upper():
            line = line.split("MONTHLY TOTAL")[0].strip()

        if "Customer Name" in line:
            line = line.split("Balance left to be Paid")[-1].strip()

        for match in customer_pattern.finditer(line):
            row = blank_row()
            row["Supplier_name"] = "Soracom"
            row["CustName"] = match.group("customer").strip()
            row["UnitCost"] = clean_money(match.group("unit_cost"))
            row["Commissions"] = clean_money(match.group("commission"))
            row["meta_data_json"] = current_month

            rows.append(row)

    return rows, []


def row_signature(row):
    return "|".join(
        [
            row.get("Supplier_name", ""),
            row.get("Distname", ""),
            row.get("CustAccNbr", ""),
            row.get("InvoiceNumber", ""),
            row.get("CustName", ""),
            row.get("UnitCost", ""),
            row.get("Commissions", ""),
        ]
    ).upper()


def sunled_exact_parse_line(line, current_distributor):
    distributor_row_pattern = re.compile(
        r"^\s*(?P<zipcode>\d{5})\s+"
        r"(?P<customer>.+?)\s+"
        r"\$?(?P<unit_cost>[0-9,]+\.\d{2})\s+"
        r"\$?(?P<commission>[0-9,]+\.\d{2})\s*$",
        re.IGNORECASE,
    )

    oem_row_pattern = re.compile(
        r"^\s*(?P<invoice_number>\d{5,})\s+"
        r"(?P<invoice_date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
        r"(?P<terr>\S+)\s+"
        r"(?P<customer_id>\S+)\s+"
        r"(?P<customer>.+?)\s+"
        r"(?P<unit_cost>[0-9,]+\.\d{2})\s+"
        r"(?P<rate>[0-9]+(?:\.\d+)?)\s+"
        r"\$?(?P<commission>[0-9,]+\.\d{2})\s*$",
        re.IGNORECASE,
    )

    oem_match = oem_row_pattern.match(line)

    if oem_match:
        row = blank_row()
        row["Supplier_name"] = "SunLED"
        row["CustAccNbr"] = oem_match.group("customer_id").strip().replace("Git", "GI21")
        row["InvoiceDate"] = format_date(oem_match.group("invoice_date"))
        row["InvoiceNumber"] = oem_match.group("invoice_number").strip()
        row["CustName"] = oem_match.group("customer").strip().rstrip(",")
        row["UnitCost"] = clean_money(oem_match.group("unit_cost"))
        row["Commissions"] = clean_money(oem_match.group("commission"))
        row["Category"] = "OEM"
        return row

    distributor_match = distributor_row_pattern.match(line)

    if distributor_match and current_distributor:
        row = blank_row()
        row["Supplier_name"] = "SunLED"
        row["Distname"] = current_distributor
        row["CustName"] = distributor_match.group("customer").strip()
        row["UnitCost"] = clean_money(distributor_match.group("unit_cost"))
        row["Commissions"] = clean_money(distributor_match.group("commission"))
        row["Category"] = "Distributor"
        return row

    return None


def sunled_fuzzy_recover_line(line, current_distributor):
    """
    Recovery layer for OCR-damaged SunLED rows.

    Looks for:
    - two money values near the end
    - either a 5-digit ZIP at the front for distributor rows
    - or an invoice/date/customer id pattern for OEM rows
    """
    amounts = re.findall(r"[0-9,]+\.\d{2}", line)

    if len(amounts) < 2:
        return None

    unit_cost = amounts[-2]
    commission = amounts[-1]
    before_amounts = line[: line.rfind(unit_cost)].strip()

    # OEM recovery
    oem_match = re.search(
        r"(?P<invoice_number>\d{5,})\s+"
        r"(?P<invoice_date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
        r"(?P<terr>\S+)\s+"
        r"(?P<customer_id>\S+)\s+"
        r"(?P<customer>.+)$",
        before_amounts,
        flags=re.IGNORECASE,
    )

    if oem_match:
        row = blank_row()
        row["Supplier_name"] = "SunLED"
        row["CustAccNbr"] = oem_match.group("customer_id").strip().replace("Git", "GI21")
        row["InvoiceDate"] = format_date(oem_match.group("invoice_date"))
        row["InvoiceNumber"] = oem_match.group("invoice_number").strip()
        row["CustName"] = oem_match.group("customer").strip().rstrip(",")
        row["UnitCost"] = clean_money(unit_cost)
        row["Commissions"] = clean_money(commission)
        row["Category"] = "OEM-Recovered"
        return row

    # Distributor recovery
    dist_match = re.match(r"^\s*(?P<zipcode>\d{5})\s+(?P<customer>.+)$", before_amounts)

    if dist_match and current_distributor:
        customer = dist_match.group("customer").strip()
        customer = re.sub(r"\s+\d+(?:\.\d+)?\s*$", "", customer).strip()

        row = blank_row()
        row["Supplier_name"] = "SunLED"
        row["Distname"] = current_distributor
        row["CustName"] = customer
        row["UnitCost"] = clean_money(unit_cost)
        row["Commissions"] = clean_money(commission)
        row["Category"] = "Distributor-Recovered"
        return row

    return None


def process_sunled(pdf_text):
    rows = []
    review_rows = []
    current_distributor = ""

    distributor_names = [
        "BEYOND COMPONENTS INC. (MA)",
        "DIGI-KEY CORPORATION",
        "HEARTLAND ELECTRONICS, INC.",
    ]

    ignore_tokens = [
        "ZIPCODE",
        "SUBTOTAL",
        "TOTAL COMMISSION",
        "SALES REP",
        "SUNLED",
        "PREPARED BY",
        "PERIOD:",
        "CUSTOMER INVOICE COMMISSION",
        "POS COMMISSION",
        "INVOICE #",
        "PAGE ",
    ]

    seen = set()

    for raw_line in pdf_text.splitlines():
        line = normalize_ocr_text(" ".join(raw_line.strip().split()))

        if not line:
            continue

        upper_line = line.upper()

        for distributor_name in distributor_names:
            if distributor_name in upper_line:
                current_distributor = distributor_name
                break

        if any(token in upper_line for token in ignore_tokens):
            continue

        exact_row = sunled_exact_parse_line(line, current_distributor)

        if exact_row:
            signature = row_signature(exact_row)

            if signature not in seen:
                rows.append(exact_row)
                seen.add(signature)

            continue

        recovered_row = sunled_fuzzy_recover_line(line, current_distributor)

        if recovered_row:
            signature = row_signature(recovered_row)

            if signature not in seen:
                rows.append(recovered_row)
                seen.add(signature)

            continue

        amounts = re.findall(r"[0-9,]+\.\d{2}", line)
        has_record_clue = bool(amounts) and (
            bool(re.search(r"\b\d{5}\b", line))
            or bool(re.search(r"\b\d{5,}\b", line))
            or current_distributor
        )

        if has_record_clue:
            suggested_unit_cost = clean_money(amounts[-2]) if len(amounts) >= 2 else ""
            suggested_commission = clean_money(amounts[-1]) if len(amounts) >= 1 else ""

            review_rows.append(
                {
                    "Include": False,
                    "Raw Line": line,
                    "Suggested Distname": current_distributor,
                    "Suggested CustAccNbr": "",
                    "Suggested InvoiceDate": "",
                    "Suggested InvoiceNumber": "",
                    "Suggested CustName": "",
                    "Suggested UnitCost": suggested_unit_cost,
                    "Suggested Commissions": suggested_commission,
                    "Reason": "Possible record with money values but parser could not confidently map it",
                }
            )

    return rows, review_rows



def _wall_money_pattern():
    return r"-?\$?\(?[0-9,]+\.\d{2}\)?"


def _clean_wall_money(value):
    value = str(value or "").strip()
    is_negative = value.startswith("-") or (value.startswith("(") and value.endswith(")"))
    cleaned = clean_money(value.replace("(", "").replace(")", ""))

    if is_negative and cleaned and not cleaned.startswith("-"):
        return f"-{cleaned}"

    return cleaned


def _build_wall_review_row(line, reason):
    money_values = re.findall(_wall_money_pattern(), line)
    dates = re.findall(r"\d{1,2}/\d{1,2}/\d{2,4}", line)
    numbers = re.findall(r"\b\d{4,}\b", line)

    return {
        "Include": False,
        "Raw Line": line,
        "Suggested Distname": "",
        "Suggested CustAccNbr": "",
        "Suggested InvoiceDate": dates[0] if dates else "",
        "Suggested InvoiceNumber": numbers[-1] if numbers else "",
        "Suggested CustName": "",
        "Suggested UnitCost": _clean_wall_money(money_values[-2]) if len(money_values) >= 2 else "",
        "Suggested Commissions": _clean_wall_money(money_values[-1]) if money_values else "",
        "Suggested Supplier_name": "Wall",
        "Reason": reason,
    }


def process_wall(pdf_text):
    rows = []
    review_rows = []

    money = _wall_money_pattern()
    line_pattern = re.compile(
        r"^\s*"
        r"(?P<customer>\S+)\s+"
        r"(?P<customer_name>.+?)\s+"
        r"(?P<order_no>\S+)\s+"
        r"(?P<invoice_number>\d+)\s+"
        r"(?P<invoice_date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
        r"(?P<due_date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
        rf"(?P<commission_base>{money})\s+"
        rf"(?P<commission_amount>{money})"
        r".*$",
        re.IGNORECASE,
    )

    header_words = [
        "SHIP TO",
        "SUM",
        "TOTAL",
        "PAGE",
        "SALES REP",
    ]

    parsed_or_reviewed_lines = set()

    for raw_line in pdf_text.splitlines():
        line = " ".join(raw_line.strip().split())

        if not line:
            continue

        upper_line = line.upper()

        if any(word in upper_line for word in header_words):
            continue

        match = line_pattern.match(line)

        if match:
            row = blank_row()
            row["Supplier_name"] = "Wall"
            row["CustAccNbr"] = match.group("customer").strip()
            row["CustName"] = match.group("customer_name").strip()
            row["InvoiceNumber"] = match.group("invoice_number").strip()
            row["InvoiceDate"] = format_date(match.group("invoice_date"))
            row["UnitCost"] = _clean_wall_money(match.group("commission_base"))
            row["Commissions"] = _clean_wall_money(match.group("commission_amount"))
            rows.append(row)
            parsed_or_reviewed_lines.add(line)
            continue

        money_values = re.findall(money, line)
        has_wall_record_clue = len(money_values) >= 2 and (
            bool(re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", line))
            or bool(re.search(r"\b\d{4,}\b", line))
        )

        if has_wall_record_clue:
            review_rows.append(
                _build_wall_review_row(
                    line,
                    "Possible Wall record with money/date/invoice values but parser could not confidently map it",
                )
            )
            parsed_or_reviewed_lines.add(line)

    if not rows and not review_rows:
        compact_text = " ".join(pdf_text.split())

        if compact_text:
            review_rows.append(
                {
                    "Include": False,
                    "Raw Line": compact_text[:1000],
                    "Suggested Distname": "",
                    "Suggested CustAccNbr": "",
                    "Suggested InvoiceDate": "",
                    "Suggested InvoiceNumber": "",
                    "Suggested CustName": "",
                    "Suggested UnitCost": "",
                    "Suggested Commissions": "",
                    "Suggested Supplier_name": "Wall",
                    "Reason": "Wall PDF text was extracted, but no parseable Wall records were found. Review OCR/text manually.",
                }
            )
        else:
            review_rows.append(
                {
                    "Include": False,
                    "Raw Line": "",
                    "Suggested Distname": "",
                    "Suggested CustAccNbr": "",
                    "Suggested InvoiceDate": "",
                    "Suggested InvoiceNumber": "",
                    "Suggested CustName": "",
                    "Suggested UnitCost": "",
                    "Suggested Commissions": "",
                    "Suggested Supplier_name": "Wall",
                    "Reason": "No text could be extracted from this Wall PDF, even after OCR fallback.",
                }
            )

    return rows, review_rows



NISSHINBO_PART_PATTERN = re.compile(
    r"^(NJM|NJG|NJU|BMJ)[A-Z0-9]+-[A-Z0-9\-]+-#[A-Z0-9]+(?:-[A-Z])?$"
)


def _nisshinbo_clean_part(value):
    """
    Correct OCR errors in Nisshinbo part numbers.

    Expected format: (NJM|NJG|NJU|BMJ)<digits>...-TE(1|2|3)-#<SUFFIX>[-P]

    Fixes applied (all verified against real PDF scans):
    1. Prefix: N + junk chars (U/O/I/d/J mix) before M -> NJM; before G -> NJG
    2. TE segment: TH1/TH2/TH3 -> TE1/TE2/TE3;  TRL -> TE1
    3. Hash separator: missing # re-inserted; } -> #; stray ~ removed
    4. Leading spurious char after #: #2Z -> #Z (noise); #2X -> #ZX (real Z misread)
    5. Suffix Z/2 confusion: all 2s in suffix normalised to Z;
       runs of 3+ Z between non-Z chars collapsed to ZZ (e.g. HZZZH -> HZZH)
    6. Specific char fixes:
       F0S5->F05, BP04->BF04, ZG6ZB->ZGZB, digit+B+2digits->digit+8+2digits,
       11S6->1156, 2741P3->2741F3
    """
    p = str(value or "").upper().strip()
    p = p.replace(" ", "")

    # Normalise dash variants
    p = p.replace("_", "-")
    p = p.replace("--", "-")
    p = p.replace("—", "-")
    p = p.replace("–", "-")
    p = p.replace("＃", "#")

    # 1. Fix prefix: NJM variants (NUM, NOM, NIM, NdM, NdJM, NUJM, NUIM -> NJM)
    p = re.sub(r"^N[JUOID]*J?M", "NJM", p)
    # NJG variants (NdG, NdJG -> NJG)
    p = re.sub(r"^N[JD]*J?G", "NJG", p)

    # 2. Fix TE segment
    p = re.sub(r"-TH([123])-", r"-TE\1-", p)
    p = re.sub(r"-TRL-", r"-TE1-", p)
    p = re.sub(r"-TH([123])$", r"-TE\1", p)
    # Remove stray ~ that OCR inserts near the dash-hash boundary
    p = re.sub(r"~-?#", "-#", p)
    p = re.sub(r"-~-", "-", p)

    # 3. Fix hash separator
    p = p.replace("}", "#")
    # Re-insert missing # when none exists (e.g. -ZAZMZF -> -#ZAZMZF)
    if "#" not in p:
        p = re.sub(r"-([A-Z][A-Z0-9]+(?:-P)?)$", r"-#\1", p)

    # 4. Fix leading char after #
    # #2Z -> #Z  (spurious 2 before a real Z)
    p = re.sub(r"#2Z", "#Z", p)
    # #2X -> #ZX  (2 is a misread Z before a non-Z letter)
    p = re.sub(r"#2([^Z])", r"#Z\1", p)

    # 5. Suffix Z/2 normalisation
    def _fix_suffix(m):
        suffix = m.group(1)
        suffix = suffix.replace("2", "Z")
        # Collapse 3+ consecutive Z between two non-Z chars to ZZ
        # (handles HZZZH -> HZZH; does not affect trailing ZZZM)
        suffix = re.sub(r"(?<=[A-WYZ])Z{3,}(?=[A-WYZ])", "ZZ", suffix)
        return "#" + suffix

    p = re.sub(r"#([A-Z0-9\-]+)", _fix_suffix, p)

    # 6. Specific character-level fixes
    p = p.replace("F0S5", "F05")    # S misread between 0 and 5
    p = p.replace("BP04", "BF04")   # F misread as P
    p = p.replace("ZG6ZB", "ZGZB")  # spurious 6 inserted
    # digit + B + two digits: B is a misread 8  (e.g. 2B72 -> 2872)
    p = re.sub(r"(\d)B(\d{2})", lambda m: m.group(1) + "8" + m.group(2), p)
    p = p.replace("11S6", "1156")   # S misread as 5
    p = p.replace("2741P3", "2741F3")  # P misread as F

    # Final: extract the canonical part-number token if present
    match = re.search(
        r"(?:NJM|NJG|NJU|BMJ)[A-Z0-9]+-[A-Z0-9\-]+-#[A-Z0-9]+(?:-[A-Z])?",
        p,
    )
    return match.group(0) if match else p


def _nisshinbo_review_row(file_name, page_no, row_text, raw_part, suggested_part, unit_cost, commissions, cust_name, reason):
    return {
        "Include": False,
        "File Name": file_name,
        "PageNo": page_no,
        "Raw Line": row_text,
        "Suggested Supplier_name": "Nisshinbo",
        "Suggested CustName": cust_name,
        "Suggested UnitCost": clean_money(unit_cost),
        "Suggested Commissions": clean_money(commissions),
        "Suggested PartNumberSubmitted": suggested_part,
        "RawPartNumberOCR": raw_part,
        "NeedsReview": True,
        "CorrectionApplied": False,
        "Reason": reason,
    }


def _nisshinbo_make_row(file_name, page_no, cust_name, part, unit_cost, commissions, source, raw_line="", needs_review=False, review_reason="", slip_no=""):
    row = blank_row()
    row["Supplier_name"] = "Nisshinbo"
    row["CustName"] = str(cust_name or "").strip()
    row["PartNumberSubmitted"] = _nisshinbo_clean_part(part)
    row["InvoiceNumber"] = str(slip_no or "").strip()
    row["UnitCost"] = clean_money(unit_cost)
    row["Commissions"] = clean_money(commissions)
    row["meta_data_json"] = json.dumps(
        {
            "FileName": file_name,
            "PageNo": page_no,
            "RawPartNumberOCR": part,
            "PartExtractionSource": source,
            "NeedsReview": needs_review,
            "ReviewReason": review_reason,
            "RawLine": raw_line,
        }
    )
    return row


GROQ_PROMPTS = {
    "Nisshinbo": {
        "system": (
            "You are a data extraction agent for Nisshinbo distributor commission statements. "
            "Extract every transaction row from the OCR text. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Nisshinbo commission statement OCR text.\n\n"
            "Column order: I/V No | SLIP No | PARTS No | Q'TY | AMOUNT | % | COMM | Currency | Pay amount | CUSTOMER\n\n"
            "Rules:\n"
            "- Skip header lines, subtotal lines (lines with *), and summary/total lines.\n"
            "- AMOUNT is the 1st money value. % is always 2.00 — skip it. COMM is the 3rd money value.\n"
            "- OCR noise in part numbers: NUM/NOM/NIM/NdM/NUJM → NJM; NdG/NdJG → NJG; Z and 2 are often confused in suffixes.\n"
            "- Each SLIP No is unique (format: 7digits-2digits). Deduplicate if you see the same slip twice.\n\n"
            "Return JSON: {\"rows\": [{\"slip\": \"\", \"part\": \"\", \"amount\": \"\", \"commission\": \"\", \"customer\": \"\"}]}\n\n"
            "OCR TEXT:\n"
        ),
        "fields": ["slip", "part", "amount", "commission", "customer"],
    },

    "Bravotek": {
        "system": (
            "You are a data extraction agent for Bravotek sales commission reports. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Bravotek commission report OCR/PDF text.\n\n"
            "Each data row contains: a line number, Customer Name, PO Number (starts with PO), Sales Amount ($), Payout Amount ($).\n\n"
            "Rules:\n"
            "- Skip header lines, total lines, and blank lines.\n"
            "- PO Number always starts with 'PO' followed by alphanumeric characters.\n"
            "- Sales Amount is the first $ value, Payout Amount is the second $ value.\n"
            "- Deduplicate rows with the same PO Number + Customer + Amount.\n\n"
            "Return JSON: {\"rows\": [{\"customer\": \"\", \"po_number\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer", "po_number", "amount", "commission"],
    },

    "Heatron": {
        "system": (
            "You are a data extraction agent for Heatron commission statements. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Heatron commission statement OCR/PDF text.\n\n"
            "Each data row contains: Customer ID (numeric), Customer Name, Invoice Date (MM/DD/YYYY), "
            "Invoice Number (starts with IN), Sales Amount, Sales Rep ID, Vendor ID, Commission %, AP Voucher Amount.\n\n"
            "Rules:\n"
            "- Skip header lines (CUSTOMER_ID, LORENZ SALES) and blank lines.\n"
            "- Invoice Number starts with IN followed by digits.\n"
            "- The commission value is the AP Voucher amount (last money value on the line).\n"
            "- Deduplicate rows with same Invoice Number + Customer ID.\n\n"
            "Return JSON: {\"rows\": [{\"customer_id\": \"\", \"customer\": \"\", \"invoice_number\": \"\", \"invoice_date\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer_id", "customer", "invoice_number", "invoice_date", "amount", "commission"],
    },

    "Soracom": {
        "system": (
            "You are a data extraction agent for Soracom commission reports. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Soracom commission report OCR/PDF text.\n\n"
            "The report is organised by month. Each section has a month/year header (e.g. 'January 2024').\n"
            "Each data row contains: Customer Name, Commission %, Sales Amount ($), Commission Amount ($).\n"
            "Known customers: Carlisle Fluid Technologies, mach.io\n\n"
            "Rules:\n"
            "- Capture the month header that applies to each row.\n"
            "- Skip MONTHLY TOTAL lines and header lines.\n"
            "- Deduplicate rows with same Customer + Amount + Month.\n\n"
            "Return JSON: {\"rows\": [{\"customer\": \"\", \"amount\": \"\", \"commission\": \"\", \"month\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer", "amount", "commission", "month"],
    },

    "SunLed": {
        "system": (
            "You are a data extraction agent for SunLED commission statements. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this SunLED commission statement OCR/PDF text.\n\n"
            "The report has two types of rows:\n"
            "1. OEM rows: Invoice Number (5+ digits) | Invoice Date | Territory | Customer ID | Customer Name | Sales Amount | Rate | Commission\n"
            "2. Distributor rows: ZIP Code (5 digits) | Customer Name | Sales Amount | Commission (under a named distributor section)\n\n"
            "Distributor section headers include: BEYOND COMPONENTS INC., DIGI-KEY CORPORATION, HEARTLAND ELECTRONICS.\n\n"
            "Rules:\n"
            "- Track the current distributor name for distributor rows.\n"
            "- Skip SUBTOTAL, TOTAL, ZIPCODE header lines.\n"
            "- Category field: 'OEM' for type-1 rows, 'Distributor' for type-2 rows.\n"
            "- Deduplicate rows with same Invoice Number + Customer + Amount (for OEM) or ZIP + Customer + Amount (for Distributor).\n\n"
            "Return JSON: {\"rows\": [{\"category\": \"\", \"invoice_number\": \"\", \"invoice_date\": \"\", \"customer_id\": \"\", \"customer\": \"\", \"distname\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["category", "invoice_number", "invoice_date", "customer_id", "customer", "distname", "amount", "commission"],
    },

    "Wall": {
        "system": (
            "You are a data extraction agent for Wall Industries commission statements. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Wall Industries commission statement OCR/PDF text.\n\n"
            "Each data row contains: Customer ID | Customer Name | Order No | Invoice Number (digits) | "
            "Invoice Date (MM/DD/YYYY) | Due Date (MM/DD/YYYY) | Commission Base Amount | Commission Amount.\n\n"
            "Rules:\n"
            "- Skip header lines (CUSTOMER, SHIP TO, ORDER, INVOICE, COMMISSION, SUM, TOTAL, PAGE, SALES).\n"
            "- Commission Base is the first money value, Commission Amount is the second.\n"
            "- Negative amounts may appear as (123.45) — preserve the negative sign.\n"
            "- Deduplicate rows with same Invoice Number + Customer ID + Commission Amount.\n\n"
            "Return JSON: {\"rows\": [{\"customer_id\": \"\", \"customer\": \"\", \"invoice_number\": \"\", \"invoice_date\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer_id", "customer", "invoice_number", "invoice_date", "amount", "commission"],
    },

    "DEI": {
        "system": (
            "You are a data extraction agent for DEI commission statements. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this DEI commission statement OCR/PDF text.\n\n"
            "Extract whatever transaction data is present. Common fields include: "
            "Customer Name, Invoice Number, Invoice Date, Sales Amount, Commission Amount.\n\n"
            "Rules:\n"
            "- Skip header lines, total lines, and blank lines.\n"
            "- Return all data rows you can identify.\n\n"
            "Return JSON: {\"rows\": [{\"customer\": \"\", \"invoice_number\": \"\", \"invoice_date\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer", "invoice_number", "invoice_date", "amount", "commission"],
    },

    "Shinelink": {
        "system": (
            "You are a data extraction agent for Shinelink commission statements. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Shinelink commission statement OCR/PDF text.\n\n"
            "Extract whatever transaction data is present. Common fields include: "
            "Customer Name, Invoice Number, Invoice Date, Sales Amount, Commission Amount.\n\n"
            "Rules:\n"
            "- Skip header lines, total lines, and blank lines.\n"
            "- Return all data rows you can identify.\n\n"
            "Return JSON: {\"rows\": [{\"customer\": \"\", \"invoice_number\": \"\", \"invoice_date\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer", "invoice_number", "invoice_date", "amount", "commission"],
    },

    "Winchester": {
        "system": (
            "You are a data extraction agent for Winchester commission statements. "
            "Return ONLY valid JSON — no explanation, no markdown fences."
        ),
        "user_prefix": (
            "Extract all transaction rows from this Winchester commission statement OCR/PDF text.\n\n"
            "Extract whatever transaction data is present. Common fields include: "
            "Customer Name, Invoice Number, Invoice Date, Sales Amount, Commission Amount.\n\n"
            "Rules:\n"
            "- Skip header lines, total lines, and blank lines.\n"
            "- Return all data rows you can identify.\n\n"
            "Return JSON: {\"rows\": [{\"customer\": \"\", \"invoice_number\": \"\", \"invoice_date\": \"\", \"amount\": \"\", \"commission\": \"\"}]}\n\n"
            "PDF TEXT:\n"
        ),
        "fields": ["customer", "invoice_number", "invoice_date", "amount", "commission"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CLIENT PERSISTENCE
# Saved as  custom_clients.json  next to app.py
# Schema: { "ClientName": { "prompt": "...", "fields": [...], "column_map": {...} } }
# ─────────────────────────────────────────────────────────────────────────────

CUSTOM_CLIENTS_FILE = "custom_clients.json"


def _load_custom_clients():
    try:
        with open(CUSTOM_CLIENTS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_custom_client(name, prompt, fields, column_map):
    clients = _load_custom_clients()
    clients[name] = {
        "prompt":     prompt,
        "fields":     fields,
        "column_map": column_map,
    }
    with open(CUSTOM_CLIENTS_FILE, "w") as f:
        json.dump(clients, f, indent=2)


def get_all_clients():
    """Return built-in clients + saved custom clients + New Client sentinel."""
    custom = list(_load_custom_clients().keys())
    return CLIENTS + [c for c in custom if c not in CLIENTS] + ["➕ New Client"]


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSAL GROQ DISCOVERY  (runs once on a sample PDF to learn its structure)
# ─────────────────────────────────────────────────────────────────────────────

def _groq_call(system_prompt, user_prompt, api_key):
    """Make a single Groq API call and return parsed JSON dict."""
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 4096,
    }
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


DISCOVER_SYSTEM = (
    "You are a data extraction expert. Given raw PDF/OCR text from a commission statement, "
    "identify the table structure and extract all transaction rows. "
    "Return ONLY valid JSON — no explanation, no markdown fences."
)

DISCOVER_USER = """Analyze this commission statement PDF text and extract all transaction rows.

First, identify what columns exist in the data (e.g. customer name, invoice number, date, amount, commission, part number, PO number, etc.).

Then extract every data row. Skip headers, totals, and blank lines.

Return JSON in this exact format:
{
  "detected_columns": ["col1", "col2", ...],
  "rows": [
    {"col1": "value", "col2": "value", ...},
    ...
  ]
}

PDF TEXT:
"""


def groq_discover_client(pdf_text, api_key):
    """
    Auto-detect the column structure of an unknown PDF and extract all rows.
    Returns (detected_columns, rows_list).
    """
    # Use first ~3000 words to stay under token limit
    sample = " ".join(pdf_text.split()[:3000])
    data = _groq_call(DISCOVER_SYSTEM, DISCOVER_USER + sample, api_key)
    detected_columns = data.get("detected_columns", [])
    rows = data.get("rows", [])
    return detected_columns, rows


def groq_extract_custom(pdf_text, api_key, client_cfg):
    """
    Extract rows from a saved custom client using its stored prompt + field list.
    """
    prompt_cfg = {
        "system":      client_cfg.get("prompt", DISCOVER_SYSTEM),
        "user_prefix": DISCOVER_USER,
        "fields":      client_cfg.get("fields", []),
    }
    words = pdf_text.split()
    chunk_size = 3000
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, max(len(words), 1), chunk_size)]

    all_rows = []
    seen_keys = set()
    for chunk in chunks:
        if not chunk.strip():
            continue
        data = _groq_call(prompt_cfg["system"], prompt_cfg["user_prefix"] + chunk, api_key)
        for gr in data.get("rows", []):
            key = "|".join(str(gr.get(f, "")).strip().upper() for f in prompt_cfg["fields"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_rows.append(gr)
    return all_rows


def apply_column_map(groq_rows, column_map, supplier_name):
    """
    Map Groq-detected column names → OUTPUT_COLUMNS using the saved column_map.
    column_map = { "detected_col": "OUTPUT_COLUMN" }
    Also stores the raw source in meta_data_json.
    """
    out = []
    for gr in groq_rows:
        row = blank_row()
        row["Supplier_name"] = supplier_name
        for detected_col, output_col in column_map.items():
            if output_col and output_col in OUTPUT_COLUMNS:
                val = str(gr.get(detected_col, "")).strip()
                if output_col in ("UnitCost", "Commissions"):
                    val = clean_money(val)
                elif output_col in ("InvoiceDate", "Pay_Date", "ship_date"):
                    val = format_date(val)
                row[output_col] = val
        row["meta_data_json"] = json.dumps(gr)  # store raw for traceability
        out.append(row)
    return out



    """Make a single Groq API call and return parsed JSON dict."""
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 4096,
    }
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def _groq_rows_to_output(client_name, groq_rows, supplier_name):
    """
    Convert Groq JSON rows (list of dicts) → list of blank_row() dicts
    mapped to OUTPUT_COLUMNS for each client.
    """
    out = []
    for gr in groq_rows:
        row = blank_row()
        row["Supplier_name"] = supplier_name

        if client_name == "Nisshinbo":
            row["CustName"]             = str(gr.get("customer", "")).strip().upper()
            row["PartNumberSubmitted"]  = _nisshinbo_clean_part(str(gr.get("part", "")))
            row["InvoiceNumber"]        = str(gr.get("slip", "")).strip()
            row["UnitCost"]             = clean_money(gr.get("amount", ""))
            row["Commissions"]          = clean_money(gr.get("commission", ""))

        elif client_name == "Bravotek":
            row["CustName"]    = str(gr.get("customer", "")).strip()
            row["PO_Number"]   = str(gr.get("po_number", "")).strip()
            row["UnitCost"]    = clean_money(gr.get("amount", ""))
            row["Commissions"] = clean_money(gr.get("commission", ""))

        elif client_name == "Heatron":
            row["CustAccNbr"]    = str(gr.get("customer_id", "")).strip()
            row["CustName"]      = str(gr.get("customer", "")).strip()
            row["InvoiceNumber"] = str(gr.get("invoice_number", "")).strip()
            row["InvoiceDate"]   = format_date(str(gr.get("invoice_date", "")))
            row["UnitCost"]      = clean_money(gr.get("amount", ""))
            row["Commissions"]   = clean_money(gr.get("commission", ""))

        elif client_name == "Soracom":
            row["CustName"]      = str(gr.get("customer", "")).strip()
            row["UnitCost"]      = clean_money(gr.get("amount", ""))
            row["Commissions"]   = clean_money(gr.get("commission", ""))
            row["meta_data_json"] = str(gr.get("month", "")).strip()

        elif client_name == "SunLed":
            row["Category"]      = str(gr.get("category", "")).strip()
            row["Distname"]      = str(gr.get("distname", "")).strip()
            row["CustAccNbr"]    = str(gr.get("customer_id", "")).strip()
            row["InvoiceNumber"] = str(gr.get("invoice_number", "")).strip()
            row["InvoiceDate"]   = format_date(str(gr.get("invoice_date", "")))
            row["CustName"]      = str(gr.get("customer", "")).strip()
            row["UnitCost"]      = clean_money(gr.get("amount", ""))
            row["Commissions"]   = clean_money(gr.get("commission", ""))

        elif client_name in ("Wall", "DEI", "Shinelink", "Winchester"):
            row["CustAccNbr"]    = str(gr.get("customer_id", "")).strip()
            row["CustName"]      = str(gr.get("customer", "")).strip()
            row["InvoiceNumber"] = str(gr.get("invoice_number", "")).strip()
            row["InvoiceDate"]   = format_date(str(gr.get("invoice_date", "")))
            row["UnitCost"]      = clean_money(gr.get("amount", ""))
            row["Commissions"]   = clean_money(gr.get("commission", ""))

        out.append(row)
    return out


def groq_extract(client_name, pdf_text, api_key):
    """
    Universal Groq extraction for any client.
    Splits text into chunks to stay within token limits,
    calls Groq per chunk, deduplicates, and returns output rows.
    Raises on any failure so caller can fall back to regex.
    """
    prompt_cfg = GROQ_PROMPTS.get(client_name)
    if not prompt_cfg:
        raise ValueError(f"No Groq prompt configured for client: {client_name}")

    # Split text into ~3000-word chunks to stay under token limits
    words = pdf_text.split()
    chunk_size = 3000
    chunks = [
        " ".join(words[i: i + chunk_size])
        for i in range(0, max(len(words), 1), chunk_size)
    ]

    all_groq_rows = []
    seen_keys = set()

    for chunk in chunks:
        if not chunk.strip():
            continue
        data = _groq_call(
            prompt_cfg["system"],
            prompt_cfg["user_prefix"] + chunk,
            api_key,
        )
        for gr in data.get("rows", []):
            # Build a dedup key from the most identifying fields
            key = "|".join(str(gr.get(f, "")).strip().upper() for f in prompt_cfg["fields"])
            if key in seen_keys or key == "|" * (len(prompt_cfg["fields"]) - 1):
                continue
            seen_keys.add(key)
            all_groq_rows.append(gr)

    supplier_name = client_name
    return _groq_rows_to_output(client_name, all_groq_rows, supplier_name)


def _nisshinbo_parse_ocr_text(ocr_text, file_name):
    """
    Single-pass parser: extracts all fields (part number, amounts, customer)
    from the same OCR line. No column-cropping or index alignment needed.

    Column order in the PDF:
      I/V No | SLIP No | PARTS No | Q'TY | AMOUNT | % | COMM | Currency | Pay amount | CUSTOMER

    Money amounts on each line: amounts[0]=AMOUNT, amounts[1]=% (always 2.00),
    amounts[2]=COMM, amounts[3]=Pay amount (same as COMM).
    We use amounts[0] for UnitCost and amounts[2] for Commissions.
    Lines with fewer than 3 money values are skipped (unrecoverable by OCR).
    """
    rows = []
    review_rows = []
    current_page = 1
    seen = set()  # deduplicate by slip number (each slip number is unique in the PDF)

    page_marker  = re.compile(r"^---\s*NISSHINBO_PAGE_(\d+)\s*---$")
    slip_pattern = re.compile(r"\b(\d{7}-\d{2})\b")
    # Capture the full raw part token (non-whitespace) starting with known Nisshinbo prefixes.
    # Uses (?<!\S) so it only matches at a word start (after whitespace or line start).
    part_pattern = re.compile(
        r"(?<!\S)((?:NJ[MG]|NJU|BMJ|N[UOIDJ]+[JMG])\S+)",
        re.IGNORECASE,
    )
    money_pattern = re.compile(r"\b(\d{1,3}(?:,\d{3})*\.\d{2})\b")
    cust_pattern  = re.compile(
        r"(GARMIN(?:\s+CORP(?:ORATION)?(?:\s+AUTO\s+OEM)?|\s+INTERNATIONAL)?(?:\s*[=—\-]\s*T1)?)",
        re.IGNORECASE,
    )

    skip_words = [
        "REQUEST FOR PAYMENT", "TOTAL", "CURRENCY", "PARTS NO", "PAY AMOUNT",
        "RECIPIENT", "ADDRESS", "ACCOUNT NO", "DIVISION", "DISTRIBUTOR",
        "SECTION", "DEALINGS", "Q'TY", "DATE OF PAYMENT",
    ]

    for raw_line in str(ocr_text or "").splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue

        pm = page_marker.match(line)
        if pm:
            current_page = int(pm.group(1))
            continue

        upper = line.upper()
        if any(s in upper for s in skip_words):
            continue

        slip_m  = slip_pattern.search(line)
        part_m  = part_pattern.search(line)
        amounts = money_pattern.findall(line)
        cust_m  = cust_pattern.search(line)

        # Require slip, part, and at least 3 money values (AMOUNT, %, COMM)
        if not slip_m or not part_m or len(amounts) < 3:
            continue

        raw_part   = part_m.group(1)
        fixed_part = _nisshinbo_clean_part(raw_part)
        unit_cost  = clean_money(amounts[0])   # AMOUNT column
        commission = clean_money(amounts[2])   # COMM column (skip % at index 1)
        cust_name  = re.sub(r"\s+", " ", cust_m.group(1).upper()).strip() if cust_m else "GARMIN"

        slip_no = slip_m.group(1)
        if slip_no in seen:
            continue
        seen.add(slip_no)

        rows.append(
            _nisshinbo_make_row(
                file_name,
                current_page,
                cust_name,
                fixed_part,
                unit_cost,
                commission,
                "full_page_ocr",
                raw_line=line,
                needs_review=False,
                review_reason="",
                slip_no=slip_no,
            )
        )

    return rows, review_rows


def process_nisshinbo_pdf(uploaded_file, groq_api_key=""):
    """
    Nisshinbo extraction using pdf2image + tesseract for OCR,
    then Groq LLM for structured extraction (with regex fallback).

    Flow:
      1. Render each page at 300 DPI with pdf2image.
      2. OCR each page with tesseract.
      3. If Groq API key provided: send OCR text to Groq → parse JSON rows.
         On any Groq failure: fall back to regex parser automatically.
      4. If no API key: use regex parser directly.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except Exception as exc:
        st.error(f"Nisshinbo OCR dependencies are missing: {exc}. Ensure tesseract-ocr, poppler-utils are in packages.txt and pdf2image is in requirements.txt.")
        return [], [
            _nisshinbo_review_row(
                getattr(uploaded_file, "name", ""),
                "", "", "", "", "", "", "",
                f"Nisshinbo OCR dependencies are missing: {exc}",
            )
        ]

    file_name = getattr(uploaded_file, "name", "")
    uploaded_file.seek(0)
    pdf_bytes = uploaded_file.read()

    try:
        pages = convert_from_bytes(pdf_bytes, dpi=300)
    except Exception as exc:
        st.error(f"Nisshinbo PDF rendering failed for '{file_name}': {exc}")
        return [], [
            _nisshinbo_review_row(
                file_name, "", "", "", "", "", "", "",
                f"Could not render PDF pages: {exc}",
            )
        ]

    # OCR all pages
    ocr_chunks = []
    for page_index, page in enumerate(pages, start=1):
        ocr_chunks.append(f"--- NISSHINBO_PAGE_{page_index} ---")
        ocr_chunks.append(
            pytesseract.image_to_string(
                page,
                config="--oem 3 --psm 6 -c preserve_interword_spaces=1",
            )
        )
    ocr_text = "\n".join(ocr_chunks)

    rows = []
    review_rows = []
    extraction_method = "regex"

    # Try Groq if API key provided
    if groq_api_key.strip():
        try:
            with st.spinner("Groq AI extracting rows..."):
                rows = groq_extract("Nisshinbo", ocr_text, groq_api_key.strip())
            extraction_method = "groq_ai"
            st.success(f"Groq extracted {len(rows)} rows from '{file_name}'.")

        except Exception as exc:
            st.warning(f"Groq extraction failed ({exc}) — falling back to regex parser.")
            rows = []

    # Regex parser (primary if no key, fallback if Groq failed)
    if not rows:
        rows, review_rows = _nisshinbo_parse_ocr_text(ocr_text, file_name)
        if extraction_method == "groq_ai":
            st.info(f"Regex fallback extracted {len(rows)} rows.")

    if not rows and not review_rows:
        review_rows.append(
            _nisshinbo_review_row(
                file_name, "", "", "", "", "", "", "",
                "No Nisshinbo rows were extracted. Review source PDF manually.",
            )
        )

    return rows, review_rows




def process_selected_client(client_name, pdf_text):
    if client_name == "Bravotek":
        return process_bravotek(pdf_text)

    if client_name == "Heatron":
        return process_heatron(pdf_text)

    if client_name == "Soracom":
        return process_soracom(pdf_text)

    if client_name == "SunLed":
        return process_sunled(pdf_text)

    if client_name == "Wall":
        return process_wall(pdf_text)

    st.warning(f"{client_name} parser is not configured yet. Please select Bravotek, Heatron, Soracom, SunLed, Wall, or Nisshinbo for now.")
    return [], []


def get_required_fields(client_name):
    if client_name == "Bravotek":
        return ["Supplier_name", "CustName", "PO_Number", "UnitCost", "Commissions"]

    if client_name == "Heatron":
        return ["Supplier_name", "CustAccNbr", "CustName", "InvoiceNumber", "InvoiceDate", "UnitCost", "Commissions"]

    if client_name == "Soracom":
        return ["Supplier_name", "CustName", "UnitCost", "Commissions"]

    if client_name == "SunLed":
        return ["Supplier_name", "CustName", "UnitCost", "Commissions"]

    if client_name == "Wall":
        return ["Supplier_name", "CustAccNbr", "CustName", "InvoiceNumber", "InvoiceDate", "UnitCost", "Commissions"]

    if client_name == "Nisshinbo":
        return ["Supplier_name", "CustName", "InvoiceNumber", "PartNumberSubmitted", "UnitCost", "Commissions"]

    return []


def get_duplicate_key_fields(client_name):
    if client_name == "Bravotek":
        return ["Supplier_name", "CustName", "PO_Number", "UnitCost", "Commissions"]

    if client_name == "Heatron":
        return ["Supplier_name", "CustAccNbr", "InvoiceNumber", "UnitCost", "Commissions"]

    if client_name == "Soracom":
        return ["Supplier_name", "CustName", "UnitCost", "Commissions", "meta_data_json"]

    if client_name == "SunLed":
        return ["Supplier_name", "Distname", "CustAccNbr", "InvoiceNumber", "CustName", "UnitCost", "Commissions"]

    if client_name == "Wall":
        return ["Supplier_name", "CustAccNbr", "InvoiceNumber", "UnitCost", "Commissions"]

    if client_name == "Nisshinbo":
        return ["Supplier_name", "InvoiceNumber", "PartNumberSubmitted", "UnitCost", "Commissions"]

    return []


def build_validation_report(df, file_summary, client_name, review_df):
    required_fields = get_required_fields(client_name)
    duplicate_key_fields = get_duplicate_key_fields(client_name)

    missing_rows = []

    for index, row in df.iterrows():
        missing_fields = [
            field
            for field in required_fields
            if field in df.columns and str(row.get(field, "")).strip() == ""
        ]

        if missing_fields:
            missing_rows.append(
                {
                    "Excel Row": index + 2,
                    "Missing Fields": ", ".join(missing_fields),
                    "CustName": row.get("CustName", ""),
                    "InvoiceNumber": row.get("InvoiceNumber", ""),
                    "PO_Number": row.get("PO_Number", ""),
                }
            )

    duplicate_rows = pd.DataFrame()

    if duplicate_key_fields and all(field in df.columns for field in duplicate_key_fields):
        duplicate_mask = df.duplicated(subset=duplicate_key_fields, keep=False)
        duplicate_rows = df.loc[duplicate_mask, duplicate_key_fields].copy()

    failed_files = [item for item in file_summary if item["Records Found"] == 0]
    review_count = 0 if review_df is None or review_df.empty else len(review_df)

    status = "PASS"

    if failed_files:
        status = "FAIL"
    elif missing_rows or len(duplicate_rows) > 0 or review_count > 0:
        status = "REVIEW REQUIRED"

    summary = {
        "PDFs Uploaded": len(file_summary),
        "PDFs Processed": sum(1 for item in file_summary if item["Records Found"] > 0),
        "Total Records Extracted": len(df),
        "Files With Zero Records": len(failed_files),
        "Rows With Missing Required Data": len(missing_rows),
        "Duplicate Rows Found": len(duplicate_rows),
        "Review Queue Rows": review_count,
        "Validation Status": status,
    }

    return summary, pd.DataFrame(missing_rows), duplicate_rows, pd.DataFrame(failed_files)


def show_validation_dashboard(df, file_summary, client_name, review_df):
    summary, missing_df, duplicate_df, failed_files_df = build_validation_report(
        df,
        file_summary,
        client_name,
        review_df,
    )

    st.subheader("Validation Dashboard")

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("PDFs Uploaded", summary["PDFs Uploaded"])
    metric_2.metric("PDFs Processed", summary["PDFs Processed"])
    metric_3.metric("Records Extracted", summary["Total Records Extracted"])
    metric_4.metric("Status", summary["Validation Status"])

    metric_5, metric_6, metric_7, metric_8 = st.columns(4)
    metric_5.metric("Zero Record Files", summary["Files With Zero Records"])
    metric_6.metric("Missing Data Rows", summary["Rows With Missing Required Data"])
    metric_7.metric("Duplicate Rows", summary["Duplicate Rows Found"])
    metric_8.metric("Review Queue Rows", summary["Review Queue Rows"])

    if summary["Validation Status"] == "PASS":
        st.success("Validation passed.")
    elif summary["Validation Status"] == "REVIEW REQUIRED":
        st.warning("Review required. Check the review queue and exception tables before downloading.")
    else:
        st.error("Validation failed. At least one file produced zero extracted records.")

    if not failed_files_df.empty:
        st.subheader("Files With Zero Records")
        st.dataframe(failed_files_df, use_container_width=True)

    if not missing_df.empty:
        st.subheader("Rows With Missing Required Data")
        st.dataframe(missing_df, use_container_width=True)

    if not duplicate_df.empty:
        st.subheader("Duplicate Rows")
        st.dataframe(duplicate_df, use_container_width=True)


def add_review_rows_to_dataframe(df, review_df, client_name):
    if review_df.empty or "Include" not in review_df.columns:
        return df

    selected_review_rows = review_df[review_df["Include"] == True]

    if selected_review_rows.empty:
        return df

    new_rows = []

    for _, review_row in selected_review_rows.iterrows():
        row = blank_row()
        row["Supplier_name"] = str(review_row.get("Suggested Supplier_name", client_name)).strip() or client_name
        row["Distname"] = str(review_row.get("Suggested Distname", "")).strip()
        row["CustAccNbr"] = str(review_row.get("Suggested CustAccNbr", "")).strip()
        row["InvoiceDate"] = str(review_row.get("Suggested InvoiceDate", "")).strip()
        row["InvoiceNumber"] = str(review_row.get("Suggested InvoiceNumber", "")).strip()
        row["CustName"] = str(review_row.get("Suggested CustName", "")).strip()
        row["PartNumberSubmitted"] = str(review_row.get("Suggested PartNumberSubmitted", "")).strip()
        row["UnitCost"] = clean_money(review_row.get("Suggested UnitCost", ""))
        row["Commissions"] = clean_money(review_row.get("Suggested Commissions", ""))
        row["Category"] = "Manual Review Added"
        row["meta_data_json"] = str(review_row.get("Raw Line", "")).strip()
        new_rows.append(row)

    if not new_rows:
        return df

    review_add_df = pd.DataFrame(new_rows)

    for column in OUTPUT_COLUMNS:
        if column not in review_add_df.columns:
            review_add_df[column] = ""

    review_add_df = review_add_df[OUTPUT_COLUMNS]

    return pd.concat([df, review_add_df], ignore_index=True)


def make_excel_download(dataframe, review_dataframe=None):
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Output")

        if review_dataframe is not None and not review_dataframe.empty:
            review_dataframe.to_excel(writer, index=False, sheet_name="Review Queue")

    return output.getvalue()



# ═══════════════════════════════════════════════════════════════════════════════
# LEADS — .MSG EMAIL PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def parse_msg_file(data):
    """
    Parse raw .msg (OLE) binary.
    Returns (body_text, images, subject, sender_from)
    images = list of (filename, bytes, width, height)
    """
    # ── Subject / sender from UTF-16 strings ──────────────────────────────────
    subject = ""
    sender_from = ""
    for chunk in re.findall(b'(?:[\x20-\x7e]\x00){8,}', data):
        try:
            s = chunk.decode('utf-16-le', errors='ignore').strip()
            if (s.startswith('Fw:') or s.startswith('FW:') or s.startswith('Re:')) and not subject:
                subject = s
            if s.startswith('From: ') and '@' in s and not sender_from:
                sender_from = s
        except Exception:
            pass

    # ── Body text ─────────────────────────────────────────────────────────────
    # Find the large UTF-16 block that contains readable email content
    BODY_MARKERS_UTF16 = [
        b'E\x00X\x00T\x00E\x00R\x00N\x00A\x00L',
        b'B\x00e\x00s\x00t\x00 \x00R\x00e\x00g\x00a\x00r\x00d\x00s',
        b'T\x00h\x00a\x00n\x00k\x00 \x00Y\x00o\x00u',
        b'P\x00l\x00e\x00a\x00s\x00e',
    ]
    body = ""
    for marker in BODY_MARKERS_UTF16:
        idx = data.find(marker)
        if idx == -1:
            continue
        chunk = data[max(0, idx - 5000): idx + 80000]
        try:
            text = chunk.decode('utf-16-le', errors='ignore')
        except Exception:
            continue
        # Find the start of meaningful content
        for start_kw in ["EXTERNAL EMAIL", "Best Regards", "Thank You,", "Please would"]:
            si = text.find(start_kw)
            if si != -1:
                raw = text[max(0, si - 500): si + 10000]
                raw = re.sub(r'\r\n', '\n', raw)
                raw = re.sub(r'\n{3,}', '\n\n', raw)
                raw = re.sub(r'[ \t]+', ' ', raw)
                raw = re.sub(r'\x00+', '', raw)
                raw = re.sub(r'__substg\S*', '', raw)
                body = raw.strip()
                break
        if body:
            break

    # ── Embedded images (JPEG + PNG) ──────────────────────────────────────────
    from PIL import Image as PILImage
    images = []
    img_count = 0

    # JPEG
    pos = 0
    while True:
        idx = data.find(b'\xff\xd8\xff', pos)
        if idx == -1:
            break
        end = data.find(b'\xff\xd9', idx)
        if end == -1 or end - idx < 500:
            pos = idx + 1
            continue
        img_bytes = data[idx: end + 2]
        try:
            img = PILImage.open(BytesIO(img_bytes))
            w, h = img.size
            if w > 50 and h > 50:
                images.append((f'image{img_count + 1:03d}.jpg', img_bytes, w, h))
                img_count += 1
        except Exception:
            pass
        pos = end + 2

    # PNG
    pos = 0
    while True:
        idx = data.find(b'\x89PNG\r\n\x1a\n', pos)
        if idx == -1:
            break
        end = data.find(b'IEND\xaeB`\x82', idx)
        if end == -1:
            pos = idx + 1
            continue
        img_bytes = data[idx: end + 8]
        try:
            img = PILImage.open(BytesIO(img_bytes))
            w, h = img.size
            if w > 50 and h > 50:
                images.append((f'image{img_count + 1:03d}.png', img_bytes, w, h))
                img_count += 1
        except Exception:
            pass
        pos = end + 8

    return body, images, subject, sender_from


LEAD_GROQ_SYSTEM = (
    "You are a sales lead extraction agent. Given the body text of a forwarded email, "
    "extract the key lead information. Return ONLY valid JSON — no explanation, no markdown."
)

LEAD_GROQ_USER = """Extract the following fields from this email lead. If a field is not present, use an empty string.

Fields to extract:
- contact_name: Full name of the person who sent the original inquiry
- company: Company or organization name
- phone: Phone number(s)
- email: Email address of the inquirer
- part_numbers: Any part numbers, model numbers, or product references mentioned
- request: A 1-2 sentence summary of what they are asking for
- location: Address or city/state if mentioned
- forwarded_by: Name and email of the person who forwarded the email (if it's a forwarded email)

Return JSON: {"contact_name":"","company":"","phone":"","email":"","part_numbers":"","request":"","location":"","forwarded_by":""}

EMAIL BODY:
"""


def groq_extract_lead(body_text, api_key):
    """Use Groq to extract structured lead info from email body text."""
    sample = body_text[:4000]
    data = _groq_call(LEAD_GROQ_SYSTEM, LEAD_GROQ_USER + sample, api_key)
    return data


def _short_pdf_name(sequence, suffix="lead_card"):
    """Generate a short unique PDF name: Lead_YYYYMMDD_001_suffix.pdf"""
    date_str = datetime.now().strftime("%Y%m%d")
    return f"Lead_{date_str}_{sequence:03d}_{suffix}.pdf"


def build_lead_pdf(body, images, subject, sender_from, lead_info, file_name=""):
    """
    Build a structured PDF lead card: AI-extracted fields table + email body + images.
    Returns bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style   = ParagraphStyle('ltitle', parent=styles['Heading1'],
                                    fontSize=16, textColor=colors.HexColor('#1a3a5c'), spaceAfter=4)
    section_style = ParagraphStyle('lsec',   parent=styles['Heading2'],
                                    fontSize=11, textColor=colors.HexColor('#2c5f8a'),
                                    spaceBefore=10, spaceAfter=4)
    body_style    = ParagraphStyle('lbody',  parent=styles['Normal'],
                                    fontSize=8.5, leading=12, spaceAfter=2)

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("LEAD CARD", title_style))
    story.append(Paragraph(f"<b>Subject:</b> {subject or file_name}", body_style))
    story.append(Paragraph(f"<b>{sender_from}</b>" if sender_from else "", body_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2c5f8a')))
    story.append(Spacer(1, 6))

    # ── AI extracted fields ───────────────────────────────────────────────────
    story.append(Paragraph("AI-Extracted Lead Details", section_style))
    field_labels = [
        ("Contact Name",   "contact_name"),
        ("Company",        "company"),
        ("Phone",          "phone"),
        ("Email",          "email"),
        ("Part Numbers",   "part_numbers"),
        ("Request",        "request"),
        ("Location",       "location"),
        ("Forwarded By",   "forwarded_by"),
    ]
    table_data = [["Field", "Value"]]
    for label, key in field_labels:
        val = str(lead_info.get(key, "") or "").strip()
        if val:
            table_data.append([label, val])

    if len(table_data) > 1:
        t = Table(table_data, colWidths=[1.4 * inch, 5.6 * inch])
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor('#2c5f8a')),
            ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
            ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 8.5),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#edf3f9')]),
            ('GRID',          (0, 0), (-1, -1), 0.4, colors.HexColor('#c0d0e0')),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(t)

    # ── Email body ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(Paragraph("Email Body", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#c0d0e0')))
    story.append(Spacer(1, 4))

    SKIP_STARTS = ('__sub', 'http', '<http', 'DwMF', 'BocC', 'TwK9', 'SxwcD', '***')
    for line in body.split('\n')[:80]:
        line = line.strip()
        if not line:
            story.append(Spacer(1, 2))
            continue
        if any(line.startswith(s) for s in SKIP_STARTS):
            continue
        safe = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(safe, body_style))

    # ── Images (2 per row) ────────────────────────────────────────────────────
    if images:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"Attachments — {len(images)} image(s)", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#c0d0e0')))
        story.append(Spacer(1, 6))

        MAX_W = 3.1 * inch
        MAX_H = 3.0 * inch
        img_flowables = []
        for _name, img_bytes, w, h in images:
            scale = min(MAX_W / w, MAX_H / h, 1.0)
            try:
                img_flowables.append(
                    RLImage(BytesIO(img_bytes), width=w * scale, height=h * scale)
                )
            except Exception:
                pass

        for i in range(0, len(img_flowables), 2):
            row = img_flowables[i: i + 2]
            cols = [3.5 * inch] * len(row)
            row_table = Table([row], colWidths=cols)
            row_table.setStyle(TableStyle([
                ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING',  (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
            ]))
            story.append(row_table)

    doc.build(story)
    buf.seek(0)
    return buf.read()


def build_raw_msg_pdf(body, images):
    """
    Memo-style raw export: clean body text then each image full-width on its own,
    exactly like the Memo_Style.pdf reference. No tables, no headers, no styling.
    Returns bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    memo_style = ParagraphStyle(
        'memo', parent=styles['Normal'],
        fontSize=10, leading=15, spaceAfter=4,
        textColor=colors.HexColor('#1a3a5c'),
    )

    story = []

    SKIP_STARTS = ('__sub', 'http', '<http', 'DwMF', 'BocC', 'TwK9', 'SxwcD',
                   '***', 'Return-Path', 'X-Original', 'Delivered', 'X-Spam',
                   'DKIM', 'ARC', 'Received', 'Authentication', 'Content-Type',
                   'MIME', 'x-ms', 'b=', 'h=', 'bh=')

    # ── Body text ─────────────────────────────────────────────────────────────
    for line in body.split('\n'):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        if any(line.lower().startswith(s.lower()) for s in SKIP_STARTS):
            continue
        safe = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(safe, memo_style))

    # ── Images — each one full width, one per section ─────────────────────────
    MAX_W = 5.5 * inch
    MAX_H = 7.0 * inch

    for _name, img_bytes, w, h in images:
        story.append(Spacer(1, 12))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor('#c0c0c0')))
        story.append(Spacer(1, 8))
        scale = min(MAX_W / w, MAX_H / h, 1.0)
        try:
            story.append(RLImage(BytesIO(img_bytes),
                                  width=w * scale, height=h * scale))
        except Exception:
            pass

    doc.build(story)
    buf.seek(0)
    return buf.read()




def lead_to_excel_row(lead_info, subject, sender_from, file_name, num_images):
    """Convert extracted lead info to a flat dict for Excel output."""
    return {
        "FileName":       file_name,
        "Subject":        subject,
        "ForwardedFrom":  sender_from,
        "ContactName":    lead_info.get("contact_name", ""),
        "Company":        lead_info.get("company", ""),
        "Phone":          lead_info.get("phone", ""),
        "Email":          lead_info.get("email", ""),
        "PartNumbers":    lead_info.get("part_numbers", ""),
        "Request":        lead_info.get("request", ""),
        "Location":       lead_info.get("location", ""),
        "ForwardedBy":    lead_info.get("forwarded_by", ""),
        "ImageCount":     num_images,
    }



set_background_image("assets/background.png")

st.title("Shubham AI Agent")

tab_commissions, tab_leads = st.tabs(["📄 Commission Statements", "📧 Leads"])

# ── Sidebar: Groq key + manage saved clients (shared across both tabs) ────────
with st.sidebar:
    st.header("⚙️ Settings")
    # Auto-load from Streamlit secrets if available
    _secret_key = ""
    try:
        _secret_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        pass

    groq_api_key = st.text_input(
        "Groq API Key",
        value=_secret_key,
        type="password",
        placeholder="gsk_...",
        help="Set once in Streamlit Cloud → Manage app → Settings → Secrets as GROQ_API_KEY",
    )
    if _secret_key and groq_api_key == _secret_key:
        st.caption("✅ Loaded from Streamlit Secrets")
    st.divider()
    st.subheader("Saved Custom Clients")
    custom_clients = _load_custom_clients()
    if custom_clients:
        for cname in list(custom_clients.keys()):
            col1, col2 = st.columns([3, 1])
            col1.write(cname)
            if col2.button("🗑️", key=f"del_{cname}"):
                del custom_clients[cname]
                with open(CUSTOM_CLIENTS_FILE, "w") as f:
                    json.dump(custom_clients, f, indent=2)
                st.rerun()
    else:
        st.caption("No custom clients saved yet.")

# ── Client selector ───────────────────────────────────────────────────────────
with tab_commissions:
    client = st.selectbox("Select Account", get_all_clients())

    uploaded_files = st.file_uploader(
        "Upload PDF files",
        type=["pdf"],
        accept_multiple_files=True,
    )

    st.subheader("Required Dates")
    invoice_date = st.text_input("InvoiceDate", placeholder="MM/DD/YYYY")
    pay_date = st.text_input("Pay_Date", placeholder="MM/DD/YYYY")

    process_button = st.button("Process Files", type="primary")

    # ═══════════════════════════════════════════════════════════════════════════════
    # NEW CLIENT FLOW
    # ═══════════════════════════════════════════════════════════════════════════════
    if client == "➕ New Client":
        st.info("Upload a PDF and click **Discover** — Groq will auto-detect the columns and extract all rows. You can then map them to output columns and save as a named client.")

        if not groq_api_key.strip():
            st.warning("A Groq API key is required for New Client discovery.")
            st.stop()

        discover_file = uploaded_files[0] if uploaded_files else None

        if discover_file and st.button("🔍 Discover Columns", type="primary"):
            with st.spinner("Groq is analysing the PDF structure..."):
                discover_file.seek(0)
                raw_text = extract_pdf_text(discover_file)
                if not raw_text.strip():
                    raw_text = extract_pdf_text_with_ocr(discover_file)

                detected_cols, disc_rows = groq_discover_client(raw_text, groq_api_key.strip())

            st.success(f"Detected {len(detected_cols)} columns, {len(disc_rows)} rows.")
            st.session_state["disc_cols"]  = detected_cols
            st.session_state["disc_rows"]  = disc_rows
            st.session_state["disc_text"]  = raw_text

        if "disc_cols" in st.session_state and st.session_state["disc_cols"]:
            detected_cols = st.session_state["disc_cols"]
            disc_rows     = st.session_state["disc_rows"]

            # ── Preview raw extracted rows ────────────────────────────────────────
            st.subheader("📄 Discovered Rows Preview")
            st.dataframe(pd.DataFrame(disc_rows).head(10), use_container_width=True)

            # ── Column mapper ─────────────────────────────────────────────────────
            st.subheader("🗂️ Map Columns to Output")
            st.caption("For each column Groq found, choose which output column it maps to (or leave blank to ignore).")

            col_map = {}
            output_options = ["(ignore)"] + OUTPUT_COLUMNS
            mapper_cols = st.columns(min(len(detected_cols), 4))
            for idx, dc in enumerate(detected_cols):
                best_guess = "(ignore)"
                dc_lower = dc.lower().replace(" ", "")
                for oc in OUTPUT_COLUMNS:
                    if dc_lower in oc.lower() or oc.lower() in dc_lower:
                        best_guess = oc
                        break
                sel = mapper_cols[idx % 4].selectbox(
                    f'"{dc}"',
                    output_options,
                    index=output_options.index(best_guess) if best_guess in output_options else 0,
                    key=f"map_{dc}",
                )
                if sel != "(ignore)":
                    col_map[dc] = sel

            st.session_state["col_map"] = col_map

            # ── Raw ↔ Excel preview ───────────────────────────────────────────────
            st.subheader("🔗 PDF Raw Line ↔ Mapped Output Preview")
            if col_map and disc_rows:
                preview_rows = []
                for gr in disc_rows[:10]:
                    mapped = {col_map[dc]: str(gr.get(dc, "")) for dc in col_map}
                    preview_rows.append({
                        "📄 Raw (from PDF)": " | ".join(f"{dc}: {gr.get(dc,'')}" for dc in detected_cols if gr.get(dc)),
                        **mapped,
                    })
                st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

            # ── Save as named client ──────────────────────────────────────────────
            st.subheader("💾 Save as Named Client")
            new_client_name = st.text_input("Client Name", placeholder="e.g. Acme Corp")
            if st.button("Save Client") and new_client_name.strip():
                fields = list(col_map.keys())
                system_prompt = (
                    f"You are a data extraction agent for {new_client_name} commission statements. "
                    f"Extract all transaction rows. The columns are: {', '.join(detected_cols)}. "
                    "Return ONLY valid JSON — no explanation, no markdown fences."
                )
                _save_custom_client(
                    new_client_name.strip(),
                    system_prompt,
                    fields,
                    col_map,
                )
                st.success(f"✅ '{new_client_name}' saved! It will appear in the dropdown next time.")
                for k in ["disc_cols", "disc_rows", "disc_text", "col_map"]:
                    st.session_state.pop(k, None)
                st.rerun()

        st.stop()

    # ═══════════════════════════════════════════════════════════════════════════════
    # NORMAL PROCESSING (existing + custom clients)
    # ═══════════════════════════════════════════════════════════════════════════════
    if process_button:

        if not uploaded_files:
            st.error("Please upload at least one PDF file.")
            st.stop()

        all_rows = []
        all_review_rows = []
        file_summary = []
        all_raw_lines = []   # for raw ↔ excel mapping table

        custom_clients = _load_custom_clients()
        is_custom = client in custom_clients

        for uploaded_file in uploaded_files:
            rows, review_rows = [], []
            file_name = uploaded_file.name

            # ── Nisshinbo: needs pdf2image render + OCR first ─────────────────────
            if client == "Nisshinbo":
                rows, review_rows = process_nisshinbo_pdf(uploaded_file, groq_api_key=groq_api_key)

            # ── Custom saved client ───────────────────────────────────────────────
            elif is_custom:
                client_cfg = custom_clients[client]
                pdf_text = extract_pdf_text(uploaded_file)
                if not pdf_text.strip():
                    pdf_text = extract_pdf_text_with_ocr(uploaded_file)

                if groq_api_key.strip():
                    try:
                        with st.spinner(f"Groq extracting '{client}' rows from '{file_name}'..."):
                            groq_rows = groq_extract_custom(pdf_text, groq_api_key.strip(), client_cfg)
                        rows = apply_column_map(groq_rows, client_cfg["column_map"], client)
                        st.success(f"Groq extracted {len(rows)} rows from '{file_name}'.")
                    except Exception as exc:
                        st.warning(f"Groq failed ({exc}) — no regex fallback for custom clients.")
                else:
                    st.warning("A Groq API key is required for custom client extraction.")

            # ── Built-in clients ──────────────────────────────────────────────────
            else:
                if client in ["SunLed", "Wall"]:
                    pdf_text = extract_pdf_text_with_ocr(uploaded_file)
                else:
                    pdf_text = extract_pdf_text(uploaded_file)

                if groq_api_key.strip():
                    try:
                        with st.spinner(f"Groq AI extracting {client} rows from '{file_name}'..."):
                            rows = groq_extract(client, pdf_text, groq_api_key.strip())
                        st.success(f"Groq extracted {len(rows)} rows from '{file_name}'.")
                    except Exception as exc:
                        st.warning(f"Groq extraction failed ({exc}) — falling back to regex parser.")
                        rows = []

                if not rows:
                    rows, review_rows = process_selected_client(client, pdf_text)

            # ── Tag each row with its source file ─────────────────────────────────
            for row in rows:
                if not row.get("meta_data_json"):
                    row["meta_data_json"] = file_name

            for review_row in review_rows:
                if not review_row.get("File Name"):
                    review_row["File Name"] = file_name

            all_rows.extend(rows)
            all_review_rows.extend(review_rows)

            file_summary.append({
                "File Name": file_name,
                "Records Found": len(rows),
                "Review Queue Rows": len(review_rows),
            })

        if not all_rows and not all_review_rows:
            st.error("No valid records or review queue rows were found.")
            st.stop()

        df = pd.DataFrame(all_rows)

        if df.empty:
            df = pd.DataFrame(columns=OUTPUT_COLUMNS)

        for column in OUTPUT_COLUMNS:
            if column not in df.columns:
                df[column] = ""

        df = df[OUTPUT_COLUMNS]

        if invoice_date.strip():
            df["InvoiceDate"] = invoice_date.strip()

        if pay_date.strip():
            df["Pay_Date"] = pay_date.strip()

        review_df = pd.DataFrame(all_review_rows)

        st.success("Processing completed.")

        st.subheader("File Summary")
        st.dataframe(pd.DataFrame(file_summary), use_container_width=True)

        show_validation_dashboard(df, file_summary, client, review_df)

        # ── Raw PDF ↔ Excel Row mapping table ─────────────────────────────────────
        if not df.empty and "meta_data_json" in df.columns:
            with st.expander("🔗 PDF Raw ↔ Excel Row Mapping", expanded=False):
                st.caption("Each extracted Excel row shown alongside its raw source data from the PDF.")
                key_cols = ["CustName", "InvoiceNumber", "PO_Number", "PartNumberSubmitted", "UnitCost", "Commissions"]
                visible_cols = [c for c in key_cols if c in df.columns and df[c].astype(str).str.strip().any()]
                mapping_df = df[visible_cols + ["meta_data_json"]].copy()
                mapping_df = mapping_df.rename(columns={"meta_data_json": "📄 Raw Source"})

                # Try to pretty-print the raw source JSON
                def _pretty_raw(val):
                    try:
                        d = json.loads(str(val))
                        return " | ".join(f"{k}: {v}" for k, v in d.items() if v and k not in OUTPUT_COLUMNS)
                    except Exception:
                        return str(val)

                mapping_df["📄 Raw Source"] = mapping_df["📄 Raw Source"].apply(_pretty_raw)
                st.dataframe(mapping_df, use_container_width=True)

        if not review_df.empty:
            st.subheader("Intelligent Review Queue")
            st.write("Rows below may be missed records. Edit suggested fields, mark Include, and they will be added to the final Excel.")
            review_df = st.data_editor(
                review_df,
                use_container_width=True,
                num_rows="dynamic",
                key="review_queue_editor",
            )

        df = add_review_rows_to_dataframe(df, review_df, client)

        st.subheader("Preview / Edit Data Before Download")
        edited_df = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            key="final_output_editor",
        )

        excel_data = make_excel_download(edited_df, review_df)

        st.download_button(
            label="Download Excel",
            data=excel_data,
            file_name=f"{client}_processed_output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )



# ═══════════════════════════════════════════════════════════════════════════════
# LEADS TAB
# ═══════════════════════════════════════════════════════════════════════════════
with tab_leads:
    st.subheader("📧 Email Lead Processor")
    st.caption("Upload .msg email files. Groq extracts the lead details, images are merged into a PDF lead card.")

    if not groq_api_key.strip():
        st.warning("A Groq API key is required. Add it in the sidebar.")

    lead_files = st.file_uploader(
        "Upload .msg files",
        type=["msg"],
        accept_multiple_files=True,
        key="lead_uploader",
    )

    process_leads_btn = st.button("Process Leads", type="primary", key="process_leads")

    if process_leads_btn and lead_files:
        excel_rows = []

        for seq, lead_file in enumerate(lead_files, start=1):
            file_name = lead_file.name
            st.write(f"**Processing:** {file_name}")

            lead_file.seek(0)
            raw_data = lead_file.read()

            # Parse MSG
            with st.spinner("Parsing email..."):
                body, images, subject, sender_from = parse_msg_file(raw_data)

            st.caption(f"Found {len(images)} image attachment(s)")

            # Groq extraction
            lead_info = {}
            if groq_api_key.strip() and body:
                try:
                    with st.spinner("Groq extracting lead details..."):
                        lead_info = groq_extract_lead(body, groq_api_key.strip())
                    st.success(f"Extracted: {lead_info.get('contact_name','?')} @ {lead_info.get('company','?')}")
                except Exception as exc:
                    st.warning(f"Groq extraction failed ({exc}) — PDF will still be generated with raw body.")

            # Review / edit extracted fields
            with st.expander("✏️ Review & Edit Extracted Fields", expanded=True):
                col1, col2 = st.columns(2)
                lead_info["contact_name"] = col1.text_input("Contact Name",  value=lead_info.get("contact_name", ""), key=f"cn_{seq}")
                lead_info["company"]      = col2.text_input("Company",       value=lead_info.get("company", ""),      key=f"co_{seq}")
                lead_info["phone"]        = col1.text_input("Phone",         value=lead_info.get("phone", ""),        key=f"ph_{seq}")
                lead_info["email"]        = col2.text_input("Email",         value=lead_info.get("email", ""),        key=f"em_{seq}")
                lead_info["part_numbers"] = col1.text_input("Part Numbers",  value=lead_info.get("part_numbers", ""), key=f"pn_{seq}")
                lead_info["location"]     = col2.text_input("Location",      value=lead_info.get("location", ""),     key=f"lo_{seq}")
                lead_info["request"]      = st.text_area("Request Summary",  value=lead_info.get("request", ""),      key=f"rq_{seq}", height=80)
                lead_info["forwarded_by"] = st.text_input("Forwarded By",    value=lead_info.get("forwarded_by", ""), key=f"fb_{seq}")

            # ── Two download buttons side by side ─────────────────────────────
            btn_col1, btn_col2 = st.columns(2)

            # Structured lead card PDF
            with st.spinner("Building lead card PDF..."):
                card_pdf   = build_lead_pdf(body, images, subject, sender_from, lead_info)
                card_name  = _short_pdf_name(seq, "lead_card")

            btn_col1.download_button(
                label="⬇️ Download Lead Card PDF",
                data=card_pdf,
                file_name=card_name,
                mime="application/pdf",
                key=f"dl_card_{seq}",
            )

            # Raw memo-style PDF
            with st.spinner("Building raw memo PDF..."):
                raw_pdf  = build_raw_msg_pdf(body, images)
                raw_name = _short_pdf_name(seq, "raw")

            btn_col2.download_button(
                label="📄 Export Raw MSG as PDF",
                data=raw_pdf,
                file_name=raw_name,
                mime="application/pdf",
                key=f"dl_raw_{seq}",
            )

            st.divider()
            excel_rows.append(lead_to_excel_row(lead_info, subject, sender_from, file_name, len(images)))

        # Excel export for all leads
        if excel_rows:
            st.subheader("All Leads — Excel Export")
            leads_df = pd.DataFrame(excel_rows)
            st.dataframe(leads_df, use_container_width=True)

            excel_buf = BytesIO()
            with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                leads_df.to_excel(writer, index=False, sheet_name="Leads")
            excel_buf.seek(0)

            st.download_button(
                label="⬇️ Download All Leads Excel",
                data=excel_buf.read(),
                file_name=f"Leads_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_leads_excel",
            )
