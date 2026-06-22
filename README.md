# HYDAC Lead Formatter

A focused, standalone tool that turns lead records into the **HYDAC 54-column Excel format**.
Split out from the HYDAC Lead Agent so the formatting + dashboard + merge tools live in their own repo.

## What it does

The app has three tabs:

### ➕ Add records
- **Manual entry** — type one record at a time. Lead Source 1, 2 and 3 are manual fields.
- **Bulk upload** — upload a CSV/Excel with one row per lead to format **10–20 records at once**.
  - Download the built-in CSV template to get the column names.
  - Column names are matched loosely, so `Lead Source 1`, `leadsource1` and `LEADSOURCE1` all land in the right place.
  - Set default Lead Sources for the batch; they only fill rows where the file left them blank.
- **.msg email extraction (optional)** — upload one or more Outlook `.msg` files and let an AI provider extract the lead. Needs an API key (see below). Everything else works without a key.

### 📊 Dashboard
- See **how your data extracts** at a glance: record count and how many rows have Email / Company / Phone / Product filled in.
- Edit any cell inline — changes are kept automatically.
- Set Lead Source 1/2/3 for **every record at once**.
- Remove a single record or clear the batch.
- **Download one Excel** containing all records in the full HYDAC header format.

### 🗂️ Merge PDF / Images
- Upload several PDFs and/or images.
- Tick which ones to include and set their order.
- Merge them into a **single PDF** and download it.

## Files

- `app.py` — the Streamlit UI (three tabs)
- `core.py` — the formatter engine: HYDAC header, row building, Excel export, CSV template, PDF/image merge (no API key needed)
- `email_extract.py` — optional `.msg` parsing + AI extraction
- `requirements.txt`, `runtime.txt`

## Deploy on Streamlit Cloud

1. Push these files to a new GitHub repo.
2. On [share.streamlit.io](https://share.streamlit.io) create an app:
   - Main file path: `app.py`
   - Branch: `main`
3. (Optional) For `.msg` AI extraction, add a key in **Settings → Secrets**, e.g.:

   ```toml
   GROQ_API_KEY = "your_free_groq_key"
   # or ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
   ```

   Without a key the app still runs — only the `.msg` tab is disabled.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```
