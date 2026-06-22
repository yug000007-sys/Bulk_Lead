# Lead AI Agent

Universal lead extraction from Outlook `.msg` emails. The agent reads each (often
forwarded) thread and pulls out the **real external customer** — for any company
or industry — then lays the leads out on a dashboard for review.

It is company-agnostic: there is **no hard-coded vendor and nothing to configure**.
The agent works out per-email who the vendor/forwarder is (the party being asked for
a quote, or the internal people who forwarded it) and who the actual lead is (the one
requesting a price/part/info), using cues like an `[EXTERNAL]` banner, a forwarded-message
divider, or a direct sender.

## Stage 1 (this version)
- Upload `.msg` files, one or many at once.
- Extraction of name, title, email, company, address, phone, product, quantity, request and summary.
- Dashboard: completeness metrics, editable grid, manual Lead Source 1/2/3, an
  "how the agent read each email" panel (lead vs vendor), and a read-only preview of
  each lead's kept attachments (image thumbnails + named documents).
- Attachment filter keeps real drawings / datasheets / nameplate photos even with messy
  filenames (`IMG_4821.jpg`, `Scan.pdf`), and rejects signature/logo/Outlook icons.

## Stage 2 (next)
- Per-lead: select which attachments are valid, then **confirm** (single) or **order + merge**
  (two or more) into one **uniquely-named PDF**; the name goes into the `PDF` column.
- Export a single **ZIP** containing `leads.xlsx` plus all the PDFs (you upload them to your FTP).

## Files
- `app.py` — Streamlit UI (upload → dashboard)
- `email_extract.py` — `.msg` parsing, universal attachment filter, AI extraction prompt
- `core.py` — Excel header/export and PDF/image helpers
- `requirements.txt`, `runtime.txt`

## Deploy on Streamlit Cloud
1. Push to a new GitHub repo.
2. Main file path `app.py`, branch `main`.
3. Add a key in **Settings → Secrets**, e.g. `GROQ_API_KEY = "..."`
   (or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`).
   For Gemini also add `google-generativeai` to requirements.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
