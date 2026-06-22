"""
HYDAC Lead Formatter
A focused tool to turn lead records into the HYDAC 54-column Excel format.

Tabs:
  ➕ Add records       — manual single entry + bulk CSV/Excel + optional .msg (AI)
  📊 Dashboard         — preview / verify / edit every record, set Lead Sources,
                         then export ONE Excel for all 10-20 records at once
  🗂️ Merge PDF/Images  — upload PDFs and images, pick & order them, merge into one PDF

Only the optional .msg extraction needs an API key. Everything else runs offline.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import core
import email_extract as ee

st.set_page_config(page_title="HYDAC Lead Formatter", layout="wide", page_icon="🗂️")

# ── session state ──────────────────────────────────────────────────────────────
if "batch" not in st.session_state:
    st.session_state.batch = []          # list of full 54-key row dicts

st.title("🗂️ HYDAC Lead Formatter")
st.caption("Build records by hand or in bulk, check them in the dashboard, then export one Excel in HYDAC format.")

# ── sidebar: only needed for the optional .msg AI extraction ────────────────────
with st.sidebar:
    st.header("Settings")
    st.caption("A key is only needed for **.msg email extraction**. Manual entry, "
               "CSV bulk, the dashboard and the merge tool all work without one.")
    PROVIDER_LABELS = {
        "groq":   "🆓 Groq (free — console.groq.com)",
        "gemini": "🆓 Gemini Flash (free — aistudio.google.com)",
        "ollama": "🖥️ Ollama (local, no key)",
        "claude": "Claude Sonnet 4.6 (paid)",
        "openai": "OpenAI GPT-4o (paid)",
    }
    provider = st.radio("AI provider (for .msg only)",
                        list(PROVIDER_LABELS.keys()),
                        format_func=lambda x: PROVIDER_LABELS[x])

    secret_name = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
                   "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider, "")
    api_key = ""
    if provider == "ollama":
        st.info("No key needed. Run Ollama locally with `llama3.1:8b`.")
    else:
        api_key = st.secrets.get(secret_name, "") if secret_name else ""
        api_key = api_key or st.text_input(f"{provider.title()} API Key", type="password")
        st.success("Key ready") if api_key else st.warning("Enter a key to enable .msg extraction")

tab_add, tab_dash, tab_merge = st.tabs(
    ["➕ Add records", "📊 Dashboard", "🗂️ Merge PDF / Images"])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — ADD RECORDS
# ════════════════════════════════════════════════════════════════════════════════
with tab_add:
    st.subheader("Add one record manually")
    with st.form("manual_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            first   = st.text_input("First Name")
            last    = st.text_input("Last Name")
            title   = st.text_input("Contact Title")
            email   = st.text_input("Email")
            company = st.text_input("Company")
            product = st.text_input("Product")
        with c2:
            address = st.text_input("Address")
            city    = st.text_input("City")
            state   = st.text_input("State")
            zipcode = st.text_input("Zip Code")
            country = st.text_input("Country")
            phone   = st.text_input("Phone (PhoneSupplied)")
        with c3:
            st.markdown("**Lead Sources** (manual)")
            ls1 = st.text_input("Lead Source 1", value="Email")
            ls2 = st.text_input("Lead Source 2")
            ls3 = st.text_input("Lead Source 3")
            website = st.text_input("Web Address")
            brand   = st.text_input("Brand", value="HYDAC")
            pq      = st.text_input("Quantity (PQ)")
        comments = st.text_area("Lead Comments / Request", height=100)
        summary  = st.text_area("Summary", height=70)

        if st.form_submit_button("➕ Add to batch", type="primary"):
            row = core.new_row(
                FirstName=first, LastName=last, ContactTitle=title, Email=email,
                Company=company, Product=product, Address=address, City=city,
                State=state, ZipCode=zipcode, Country=country, PhoneSupplied=phone,
                LeadSource1=ls1, LeadSource2=ls2, LeadSource3=ls3, WebAddress=website,
                Brand=brand, PQ=pq, LeadComments=comments, Summary=summary,
            )
            st.session_state.batch.append(row)
            st.success(f"Added. Batch now has {len(st.session_state.batch)} record(s).")

    st.divider()

    # ── Bulk via CSV / Excel ────────────────────────────────────────────────────
    st.subheader("Bulk upload — format 10–20 records at once")
    st.markdown("Upload a **CSV or Excel** file with one row per lead. Column names are "
                "matched loosely, so `Lead Source 1`, `leadsource1` and `LEADSOURCE1` all work.")

    st.download_button("⬇️ Download CSV template", data=core.csv_template_bytes(),
                       file_name="hydac_leads_template.csv", mime="text/csv")

    lc1, lc2, lc3 = st.columns(3)
    d_ls1 = lc1.text_input("Default Lead Source 1 (for this batch)", value="Email", key="d_ls1")
    d_ls2 = lc2.text_input("Default Lead Source 2", key="d_ls2")
    d_ls3 = lc3.text_input("Default Lead Source 3", key="d_ls3")
    st.caption("Defaults only fill rows where the file left that Lead Source blank.")

    table_file = st.file_uploader("Upload CSV / Excel", type=["csv", "xlsx", "xls"], key="table_up")
    if table_file is not None:
        if st.button("📥 Add rows from file", key="add_table"):
            try:
                raws = core.read_table(table_file.getvalue(), table_file.name)
                defaults = {"LeadSource1": d_ls1, "LeadSource2": d_ls2, "LeadSource3": d_ls3}
                added = 0
                for raw in raws:
                    if not any(str(v).strip() for v in raw.values()):
                        continue  # skip blank rows
                    st.session_state.batch.append(core.coerce_row(raw, defaults))
                    added += 1
                st.success(f"Added {added} record(s). Batch now has {len(st.session_state.batch)}.")
            except Exception as e:
                st.error(f"Could not read that file: {e}")

    st.divider()

    # ── Bulk via .msg (optional AI) ─────────────────────────────────────────────
    st.subheader("Optional — extract from .msg email files")
    if not ee.extract_msg_available():
        st.info("`.msg` extraction needs the `extract-msg` package (it is in requirements.txt). "
                "It is not active in this preview, but manual and CSV entry work fully.")
    else:
        ready = (provider == "ollama") or bool(api_key)
        msg_files = st.file_uploader("Upload one or more .msg files", type=["msg"],
                                     accept_multiple_files=True, key="msg_up")
        m_ls1, m_ls2, m_ls3 = st.columns(3)
        e_ls1 = m_ls1.text_input("Lead Source 1", value="Email", key="e_ls1")
        e_ls2 = m_ls2.text_input("Lead Source 2", key="e_ls2")
        e_ls3 = m_ls3.text_input("Lead Source 3", key="e_ls3")

        if msg_files and not ready:
            st.warning("Add an API key in the sidebar (or pick Ollama) to run extraction.")
        if msg_files and ready and st.button("🤖 Extract & add to batch", key="run_msg"):
            prog = st.progress(0.0)
            ok = 0
            for i, mf in enumerate(msg_files, 1):
                try:
                    parsed = ee.parse_msg(mf.getvalue(), Path(mf.name).stem)
                    fields = ee.run_agent(parsed["full_text"], provider, api_key)
                    fields["ReceivedDateTime"] = parsed["date"]
                    fields["LeadSource1"] = e_ls1
                    fields["LeadSource2"] = e_ls2
                    fields["LeadSource3"] = e_ls3
                    fields["PDF"] = core.make_pdf_name(parsed["date"])
                    # map "Quantity" from the agent onto the PQ column
                    if fields.get("Quantity"):
                        fields["PQ"] = fields["Quantity"]
                    st.session_state.batch.append(core.coerce_row(fields))
                    ok += 1
                except Exception as e:
                    st.error(f"{mf.name}: {e}")
                prog.progress(i / len(msg_files))
            st.success(f"Extracted {ok}/{len(msg_files)} email(s). Batch now has {len(st.session_state.batch)}.")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — DASHBOARD
# ════════════════════════════════════════════════════════════════════════════════
with tab_dash:
    batch = st.session_state.batch
    if not batch:
        st.info("No records yet. Add some in the **Add records** tab.")
    else:
        # completeness overview — "see how the data extracts"
        df_full = pd.DataFrame(batch)
        total = len(batch)
        def filled(col):
            return int((df_full[col].astype(str).str.strip() != "").sum()) if col in df_full else 0
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Records", total)
        m2.metric("With Email", f"{filled('Email')}/{total}")
        m3.metric("With Company", f"{filled('Company')}/{total}")
        m4.metric("With Phone", f"{filled('PhoneSupplied')}/{total}")
        m5.metric("With Product", f"{filled('Product')}/{total}")

        st.divider()

        # ── set Lead Sources for ALL rows at once ───────────────────────────────
        with st.expander("🏷️ Set Lead Source for all records", expanded=False):
            s1, s2, s3, s4 = st.columns([2, 2, 2, 1])
            all_ls1 = s1.text_input("Lead Source 1", key="all_ls1")
            all_ls2 = s2.text_input("Lead Source 2", key="all_ls2")
            all_ls3 = s3.text_input("Lead Source 3", key="all_ls3")
            s4.markdown("&nbsp;")
            if s4.button("Apply to all"):
                for row in batch:
                    if all_ls1:
                        row["LeadSource1"] = all_ls1
                    if all_ls2:
                        row["LeadSource2"] = all_ls2
                    if all_ls3:
                        row["LeadSource3"] = all_ls3
                st.success("Lead Sources applied to every record.")
                st.rerun()

        # ── editable preview grid (primary columns) ─────────────────────────────
        st.markdown("#### Preview & edit")
        st.caption("Edit any cell, then your changes are kept automatically. Use the export button below.")
        grid_df = pd.DataFrame([{c: row.get(c, "") for c in core.PRIMARY_COLS} for row in batch])
        edited = st.data_editor(grid_df, num_rows="fixed", use_container_width=True,
                                hide_index=False, key="dash_editor")
        # sync edits back into the full rows
        for i, row in enumerate(batch):
            for c in core.PRIMARY_COLS:
                row[c] = "" if pd.isna(edited.iloc[i][c]) else str(edited.iloc[i][c])

        with st.expander("Show all 54 export columns"):
            st.dataframe(pd.DataFrame(batch)[core.EXCEL_HEADER], use_container_width=True)

        st.divider()
        e1, e2, e3 = st.columns([2, 1, 1])
        with e1:
            st.download_button("📥 Download Excel (all records)", type="primary",
                               data=core.make_excel(batch),
                               file_name="hydac_leads.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with e2:
            idx = st.selectbox("Remove record #", options=list(range(len(batch))),
                               format_func=lambda i: f"{i} — {batch[i].get('Company') or batch[i].get('LastName') or 'record'}")
            if st.button("🗑️ Remove"):
                batch.pop(idx)
                st.rerun()
        with e3:
            st.markdown("&nbsp;")
            if st.button("Clear all"):
                st.session_state.batch = []
                st.rerun()

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — MERGE PDF / IMAGES
# ════════════════════════════════════════════════════════════════════════════════
with tab_merge:
    st.subheader("Merge PDFs and images into one PDF")
    st.caption("Upload files, tick the ones to include and set their order, then merge.")
    merge_files = st.file_uploader("Upload PDFs / images",
                                   type=["pdf", "png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp", "webp"],
                                   accept_multiple_files=True, key="merge_up")
    if merge_files:
        sel_df = pd.DataFrame([{"include": True, "order": i + 1, "file": f.name}
                               for i, f in enumerate(merge_files)])
        sel = st.data_editor(
            sel_df, hide_index=True, use_container_width=True, key="merge_editor",
            column_config={
                "include": st.column_config.CheckboxColumn("Include"),
                "order": st.column_config.NumberColumn("Order", min_value=1, step=1),
                "file": st.column_config.TextColumn("File", disabled=True),
            })

        out_name = st.text_input("Output file name", value="merged.pdf")
        if st.button("🔗 Merge selected", type="primary"):
            by_name = {f.name: f.getvalue() for f in merge_files}
            chosen = sel[sel["include"] == True].sort_values("order")  # noqa: E712
            items = [(r["file"], by_name[r["file"]]) for _, r in chosen.iterrows()]
            if not items:
                st.warning("Tick at least one file to include.")
            else:
                merged = core.merge_to_pdf(items)
                if merged:
                    name = out_name if out_name.lower().endswith(".pdf") else out_name + ".pdf"
                    st.success(f"Merged {len(items)} file(s) into {name}.")
                    st.download_button("📄 Download merged PDF", data=merged,
                                       file_name=name, mime="application/pdf")
                else:
                    st.error("Nothing could be merged — the files may be unreadable.")
    else:
        st.info("Upload at least two files to merge.")
