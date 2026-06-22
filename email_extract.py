"""
email_extract.py — OPTIONAL .msg extraction for bulk upload.

This is the only part of the formatter that can use an AI provider. It is fully
optional: if extract-msg or an API key is missing, the rest of the app still
works (manual entry, CSV bulk, dashboard, Excel export, PDF/image merge).

Ported and trimmed from the original HYDAC Lead Agent.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List

from bs4 import BeautifulSoup

# ── attachment filtering ───────────────────────────────────────────────────────
SIGNATURE_IMAGE_NAMES = {
    "image.png", "image.jpg", "image.jpeg", "image.gif",
    "logo.png", "logo.jpg", "logo.jpeg", "banner.png", "banner.jpg", "banner.jpeg",
    "facebook.png", "linkedin.png", "twitter.png", "instagram.png", "youtube.png",
} | {f"image{str(i).zfill(3)}.{ext}"
     for i in range(1, 20) for ext in ("png", "jpg", "jpeg", "gif")}

VALID_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".step", ".stp", ".igs", ".iges", ".dwg", ".dxf",
    ".zip", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff"}

_ICON_PREFIX_RE = re.compile(
    r"^\s*<https?://[^\s>]+?(?:/images?/|/img/|/cms/|/static/|/icons?/|/logo|/media/)[^\s>]*>\s*[\t ]*",
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


def decide_attachment(filename: str, attachment_obj=None) -> Dict:
    if not filename:
        return {"filename": "", "decision": "Reject", "reason": "Blank filename"}
    name = Path(filename).name
    low = name.lower()
    ext = Path(low).suffix
    if ext not in VALID_ATTACHMENT_EXTENSIONS:
        return {"filename": name, "decision": "Reject", "reason": f"Unsupported {ext or '(none)'}"}
    if low in SIGNATURE_IMAGE_NAMES:
        return {"filename": name, "decision": "Reject", "reason": "Signature/logo image"}
    if re.fullmatch(r"image[.](png|jpg|jpeg|gif|tif|tiff)", low):
        return {"filename": name, "decision": "Reject", "reason": "Signature/logo image"}
    if re.match(r"image[0-9]", low) and ext in IMAGE_EXTENSIONS:
        return {"filename": name, "decision": "Keep", "reason": "Numbered inline image", "obj": attachment_obj}
    if ext not in IMAGE_EXTENSIONS:
        return {"filename": name, "decision": "Keep", "reason": "Document/CAD attachment", "obj": attachment_obj}
    if re.search(r"[0-9]{4,}", name):
        return {"filename": name, "decision": "Keep", "reason": "Part/model number in name", "obj": attachment_obj}
    if re.search(r"(?i)(pump|filter|drawing|label|plate|model|part|hydraulic|spec|quote|serial|bieri)", name):
        return {"filename": name, "decision": "Keep", "reason": "Product keyword in name", "obj": attachment_obj}
    return {"filename": name, "decision": "Reject", "reason": "Image not customer evidence"}


def parse_msg(file_bytes: bytes, fallback_name: str = "lead") -> Dict:
    """Parse a .msg file's bytes. Requires extract-msg (raises ImportError if missing)."""
    import extract_msg
    with tempfile.NamedTemporaryFile(delete=False, suffix=".msg") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    msg = extract_msg.Message(tmp_path)
    sender = msg.sender or ""
    subject = msg.subject or fallback_name
    date = str(msg.date) if msg.date else ""
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


# ── AI agent ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the HYDAC Lead Agent. HYDAC is a US industrial filtration and hydraulics company.
You receive raw forwarded email threads and extract the external customer lead.
Identify the REAL external customer — the person who sent an inquiry TO HYDAC.
Ignore HYDAC employees / forwarders (@hydacusa.com, @hydac.com, @hydac-interlynx.com).
The customer is usually the OLDEST message or the one below an "EXTERNAL EMAIL" marker.

RULES:
- FirstName / LastName: split cleanly, handle "Last, First", remove titles.
- ContactTitle: job title from signature only.
- Email: external customer email only, never a HYDAC domain.
- Company: from body/signature; never infer from gmail/yahoo/hotmail. If only a business domain
  is present (e.g. fleetpride.com) derive the name (FleetPride).
- Address/City/State/ZipCode/Country: only what is written.
- PhoneSupplied: customer phones only, formatted "phone1 : phone2".
- WebAddress: explicit URLs only.
- LeadComments: copy the customer's request VERBATIM (no paraphrase). For item tables use <br> and <b>labels</b>.
  Remove only greetings, sign-offs, signature blocks, legal disclaimers.
- Product: HYDAC model/part number or category.
- Quantity: numeric only if stated.
- Summary: 2-4 sentence briefing for a sales rep.

Return ONLY valid JSON with these keys (unknown = ""):
{"FirstName":"","LastName":"","ContactTitle":"","Email":"","Company":"","Address":"","City":"",
"State":"","ZipCode":"","Country":"","PhoneSupplied":"","WebAddress":"","LeadComments":"",
"Summary":"","Product":"","Quantity":"","AgentReason":""}
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
