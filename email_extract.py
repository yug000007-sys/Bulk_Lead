"""
email_extract.py — universal lead extraction from .msg files.

Company-agnostic: there is no fixed "internal" company. The agent reads the
thread itself to tell the requesting customer (the lead) apart from the vendor
being asked for a quote and any internal forwarders.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List

from bs4 import BeautifulSoup

# ── attachment filtering ───────────────────────────────────────────────────────
# Universal rule: KEEP everything unless it is clearly a signature / logo / icon.
# This is the opposite of the old HYDAC default (which rejected images unless they
# proved useful) so that real drawings / datasheets / nameplate photos with messy
# filenames (IMG_4821.jpg, Scan.pdf, photo.jpeg) are not dropped.

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp"}

# documents are always real evidence — never auto-rejected
DOC_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".step", ".stp", ".igs", ".iges", ".dwg", ".dxf",
    ".zip", ".rar", ".7z", ".txt",
}

# obvious signature / logo / tracking-pixel image names → reject
_SIGNATURE_NAME_RE = re.compile(
    r"""^(
        image\.(png|jpe?g|gif|tiff?|bmp)            # bare image.png
      | image0*\d{1,3}\.(png|jpe?g|gif|tiff?|bmp)   # image001.png .. image0019.png
      | outlook-[\w-]*\.(png|jpe?g|gif)             # Outlook-2sjln02o.png
      | (logo|banner|header|footer|icon|spacer|divider|pixel)\b.*\.(png|jpe?g|gif|bmp)
      | (facebook|linkedin|twitter|instagram|youtube|x|tiktok)\.(png|jpe?g|gif)
    )$""",
    re.I | re.X,
)


def decide_attachment(filename: str, attachment_obj=None) -> Dict:
    """Keep unless the file is clearly a signature/logo/icon image."""
    if not filename:
        return {"filename": "", "decision": "Reject", "reason": "Blank filename"}
    name = Path(filename).name
    ext = Path(name).suffix.lower()

    if ext in DOC_EXTENSIONS:
        return {"filename": name, "decision": "Keep", "reason": "Document / drawing / datasheet", "obj": attachment_obj}

    if ext in IMAGE_EXTENSIONS:
        if _SIGNATURE_NAME_RE.match(name):
            return {"filename": name, "decision": "Reject", "reason": "Signature/logo image", "obj": attachment_obj}
        return {"filename": name, "decision": "Keep", "reason": "Image — likely customer evidence", "obj": attachment_obj}

    # unknown extension: keep but mark, so the user can decide on the dashboard
    return {"filename": name, "decision": "Keep", "reason": f"Other file ({ext or 'no ext'})", "obj": attachment_obj}


# ── text cleanup ────────────────────────────────────────────────────────────────
_ICON_PREFIX_RE = re.compile(
    r"^\s*<https?://[^\s>]+?(?:/images?/|/img/|/cms/|/static/|/icons?/|/logo|/media/|imageserver)[^\s>]*>\s*[\t ]*",
    re.I,
)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).replace("\r", "\n")
    text = re.sub(r"\xa0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    return clean_text(BeautifulSoup(html, "html.parser").get_text("\n"))


def strip_icon_prefixes(text: str) -> str:
    return "\n".join(_ICON_PREFIX_RE.sub("", line) for line in text.splitlines())


def format_received_datetime(value) -> str:
    """Format an email date as 'M/D/YYYY h:MM AM/PM' (e.g. 6/19/2026 11:32 AM).

    Accepts a datetime object or a string (RFC-2822 like
    'Fri, 19 Jun 2026 16:13:03 +0000', or ISO). The wall-clock time is kept
    as-is (no timezone conversion). Returns "" if it can't be parsed.
    """
    import datetime as _dt
    from email.utils import parsedate_to_datetime

    if not value:
        return ""
    dt = None
    if isinstance(value, _dt.datetime):
        dt = value
    else:
        s = str(value).strip()
        try:
            dt = parsedate_to_datetime(s)            # RFC-2822
        except Exception:
            for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = _dt.datetime.strptime(s, fmt)
                    break
                except Exception:
                    continue
    if dt is None:
        return str(value)
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.month}/{dt.day}/{dt.year} {hour12}:{dt.minute:02d} {ampm}"


def parse_msg(file_bytes: bytes, fallback_name: str = "lead") -> Dict:
    """Parse a .msg file's bytes. Requires extract-msg (raises ImportError if missing)."""
    import extract_msg
    with tempfile.NamedTemporaryFile(delete=False, suffix=".msg") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    msg = extract_msg.Message(tmp_path)
    sender = msg.sender or ""
    subject = msg.subject or fallback_name
    date = format_received_datetime(msg.date) if msg.date else ""
    body = clean_text(msg.body or "")
    if not body and getattr(msg, "htmlBody", None):
        body = html_to_text(msg.htmlBody)
    body = strip_icon_prefixes(body)
    full_text = clean_text("\n".join([f"From: {sender}", f"Subject: {subject}", body]))

    decisions, kept = [], []
    for att in msg.attachments:
        fname = getattr(att, "longFilename", None) or getattr(att, "shortFilename", None) or ""
        if fname:
            d = decide_attachment(fname, att)
            decisions.append(d)
            if d["decision"] == "Keep":
                try:
                    kept.append((d["filename"], att.data))
                except Exception:
                    pass
    return {
        "sender": sender, "subject": subject, "date": date,
        "body": body, "full_text": full_text,
        "attachment_decisions": decisions, "kept_attachments": kept,
    }


# ── universal agent prompt ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the Lead AI Agent. You read raw (often forwarded) sales email threads from
ANY industry or company and extract the real sales LEAD.

WHO IS THE LEAD:
The lead is the EXTERNAL party requesting something — a price, lead time, a part, a datasheet,
compatibility info, a replacement, etc. They are the person who first wrote IN with the inquiry.

WHO TO IGNORE (there is NO fixed company — work it out from THIS thread):
- The VENDOR/supplier being asked for the quote: usually the top sender if they are REPLYING
  ("you don't have an active account", "a distributor will contact you", "please find attached our offer"),
  or whoever the inquiry was addressed TO.
- Internal forwarders: people who merely forwarded the thread inside the vendor's company
  (look for "Forwarded Message", "WG:", "FW:", "Im Auftrag von", multiple same-domain hops).
- Anyone whose email domain matches the vendor's / forwarders' domain.
Signals that mark the real customer's message: an "[EXTERNAL]" / "originated from outside" banner,
a "Forwarded Message" divider, or simply being the original inquiry in a direct (non-forwarded) email.
If the email is direct (not forwarded), the sender IS the lead.

EXTRACTION RULES:
- FirstName / LastName: split cleanly, handle "Last, First", remove titles (Mr/Dr).
- ContactTitle: job title from the customer's signature only.
- Email: the customer's own email. Never the vendor/forwarder address.
- Company: from the customer's body/signature. If only a business email domain is present
  (not gmail/yahoo/hotmail/outlook/icloud), derive the company from the domain (e.g. atcoflex.com -> Atcoflex).
  Never use the vendor's company as the lead's company.
- Address/City/State/ZipCode/Country: only what the customer wrote.
- PhoneSupplied: the customer's phone(s) only, formatted "phone1 : phone2".
- WebAddress: the customer's explicit URL only.
- Product: the part number / model / product the customer is asking about, exactly as written.
  Part numbers vary wildly by brand (e.g. UL-4030-CM+ULMB-40, M/50/EAP/10V, 801077700000,
  CXK02-2/2-FC-3/50/004/200PP, R901239533, UB2522-3ZCM). Copy it verbatim; do not normalise.
- Quantity: numeric only if the customer stated it.
- LeadComments: COPY THE CUSTOMER'S REQUEST WORD-FOR-WORD. This is a verbatim quote, NOT a summary.
  Do NOT paraphrase, reword, rephrase, condense, expand, "clean up", or improve the wording in any way.
  Changing the customer's words is an ERROR. Keep their exact sentences, spelling, capitalisation,
  part numbers, vendor numbers, quantities, references and special instructions.
  Remove ONLY: the greeting line (Hello/Hi/Dear/Good morning), the sign-off (Thanks/Regards/Best/Sincerely),
  the signature block (name/title/company/contact lines), legal disclaimers, and forwarding/tracking boilerplate.
  If the customer sent more than one message in the thread, use their substantive ORIGINAL request (the one
  containing the actual ask), not a short follow-up like "any update on this?".
  If details are laid out as a split/broken table (a label on one line and its value on a later line, e.g.
  "Vendor #" / "Qty." then "3842543469" / "4"), reassemble them inline as "Label - value" pairs joined by
  commas, keeping the exact words and numbers. Do not invent labels or values.
  EXAMPLE — customer wrote:
    "Hello,
     May I please get pricing, MOQ and lead time on part below for Fastenal HTIN/IN067? I could not find
     this part on the price file you sent me last week. Thanks.
     Vendor #
     Qty.
     3842543469
     4
     Nick Hantle
     Customer Supply Chain Administrator"
  CORRECT LeadComments (verbatim, greeting+sign-off+signature removed, split table reassembled inline):
    "May I please get pricing, MOQ and lead time on part below for Fastenal HTIN/IN067? I could not find this
     part on the price file you sent me last week. Vendor # - 3842543469, Qty. - 4"
- Summary: this is the ONLY place rewording/briefing belongs — 2-4 sentence briefing for a sales rep
  (who the customer is, what they want, any context). Never put a summary or paraphrase in LeadComments.
- VendorContext: 1 short line naming the vendor/supplier this inquiry was sent to or about, if identifiable
  (e.g. "Forwarded from Norgren/IMI customer service"). Empty if it was a direct email.

Return ONLY valid JSON with these keys (unknown = ""):
{"FirstName":"","LastName":"","ContactTitle":"","Email":"","Company":"","Address":"","City":"",
"State":"","ZipCode":"","Country":"","PhoneSupplied":"","WebAddress":"","LeadComments":"",
"Summary":"","Product":"","Quantity":"","VendorContext":"","AgentReason":""}
No markdown, no preamble."""

PROVIDERS = ["groq", "gemini", "claude", "openai", "ollama"]


def run_agent(email_text: str, provider: str, api_key: str = "") -> Dict:
    """Call the chosen AI provider and return the parsed JSON lead dict."""
    user_prompt = f"Extract the lead from this email thread:\n\n{email_text[:12000]}"
    raw = ""

    if provider == "ollama":
        import urllib.request
        payload = json.dumps({
            "model": "llama3.1:8b",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": user_prompt}],
            "stream": False, "options": {"temperature": 0},
        }).encode()
        req = urllib.request.Request("http://localhost:11434/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())["message"]["content"].strip()

    elif provider == "groq":
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        r = client.chat.completions.create(
            model="llama-3.1-8b-instant", temperature=0,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_prompt}])
        raw = r.choices[0].message.content.strip()

    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_PROMPT)
        raw = model.generate_content(user_prompt).text.strip()

    elif provider == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        r = client.messages.create(model="claude-sonnet-4-6", max_tokens=1200,
                                    system=SYSTEM_PROMPT,
                                    messages=[{"role": "user", "content": user_prompt}])
        raw = r.content[0].text.strip()

    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        r = client.chat.completions.create(
            model="gpt-4o", temperature=0,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_prompt}])
        raw = r.choices[0].message.content.strip()
    else:
        raise ValueError(f"Unknown provider: {provider}")

    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def extract_msg_available() -> bool:
    try:
        import extract_msg  # noqa: F401
        return True
    except Exception:
        return False
