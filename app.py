"""
Lead AI Agent — Stage 1
Universal lead extraction from .msg email files (any company/industry).

Upload .msg files (one or many) -> the agent finds the real external customer in
each thread -> review every lead on the dashboard, including any kept attachments.

Stage 2 will add: select/confirm/merge attachments into one uniquely-named PDF,
write the name into the PDF column, and export a ZIP (Excel + PDFs).
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import core
import email_extract as ee

st.set_page_config(page_title="Lead AI Agent", layout="wide", page_icon="🧲")

if "batch" not in st.session_state:
    # batch: list of {"row": {54 cols}, "attachments": [(name, bytes)], "decisions": [..], "source_file": str}
    st.session_state.batch = []

st.title("🧲 Lead AI Agent")
st.caption("Upload .msg emails — the agent finds the real customer lead in each thread, "
           "for any company or industry. Review everything on the dashboard.")

# ── sidebar: AI provider + key ──────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    PROVIDER_LABELS = {
        "groq":   "🆓 Groq (free — console.groq.com)",
        "gemini": "🆓 Gemini Flash (free — aistudio.google.com)",
        "ollama": "🖥️ Ollama (local, no key)",
        "claude": "Claude Sonnet 4.6 (paid)",
        "openai": "OpenAI GPT-4o (paid)",
    }
    provider = st.radio("AI provider",
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
        st.success("Key ready") if api_key else st.warning("Enter a key to enable extraction")

ready = (provider == "ollama") or bool(api_key)

# ════════════════════════════════════════════════════════════════════════════════
# 1) UPLOAD & EXTRACT
# ════════════════════════════════════════════════════════════════════════════════
st.subheader("1. Upload .msg email files")

if not ee.extract_msg_available():
    st.info("`.msg` extraction needs the `extract-msg` package (it is in requirements.txt and "
            "will be active once deployed on Streamlit).")

msg_files = st.file_uploader("Upload one or more .msg files", type=["msg"],
                             accept_multiple_files=True, key="msg_up")

lc1, lc2, lc3 = st.columns(3)
ls1 = lc1.text_input("Lead Source 1", value="Website")
ls2 = lc2.text_input("Lead Source 2")
ls3 = lc3.text_input("Lead Source 3")

if msg_files and not ready:
    st.warning("Add an API key in the sidebar (or pick Ollama) to run extraction.")

if msg_files and ready and st.button("🔎 Extract & add to batch", type="primary"):
    prog = st.progress(0.0)
    ok = 0
    for i, mf in enumerate(msg_files, 1):
        try:
            parsed = ee.parse_msg(mf.getvalue(), Path(mf.name).stem)
            fields = ee.run_agent(parsed["full_text"], provider, api_key)
            fields["ReceivedDateTime"] = parsed["date"]
            fields["LeadSource1"] = ls1
            fields["LeadSource2"] = ls2
            fields["LeadSource3"] = ls3
            if fields.get("Quantity"):
                fields["PQ"] = fields["Quantity"]
            st.session_state.batch.append({
                "row": core.coerce_row(fields),
                "attachments": parsed.get("kept_attachments", []),
                "decisions": parsed.get("attachment_decisions", []),
                "vendor": fields.get("VendorContext", ""),
                "reason": fields.get("AgentReason", ""),
                "source_file": mf.name,
            })
            ok += 1
        except Exception as e:
            st.error(f"{mf.name}: {e}")
        prog.progress(i / len(msg_files))
    st.success(f"Extracted {ok}/{len(msg_files)} email(s). Batch now has {len(st.session_state.batch)}.")

st.divider()

# ════════════════════════════════════════════════════════════════════════════════
# 2) DASHBOARD
# ════════════════════════════════════════════════════════════════════════════════
st.subheader("2. Dashboard")
batch = st.session_state.batch

if not batch:
    st.info("No records yet — upload .msg files above and extract.")
else:
    rows = [rec["row"] for rec in batch]
    df_full = pd.DataFrame(rows)
    total = len(batch)

    def filled(col):
        return int((df_full[col].astype(str).str.strip() != "").sum()) if col in df_full else 0

    n_with_att = sum(1 for rec in batch if rec["attachments"])
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Records", total)
    m2.metric("With Email", f"{filled('Email')}/{total}")
    m3.metric("With Company", f"{filled('Company')}/{total}")
    m4.metric("With Product", f"{filled('Product')}/{total}")
    m5.metric("With Attachments", f"{n_with_att}/{total}")

    with st.expander("🏷️ Set Lead Source for all records"):
        s1, s2, s3, s4 = st.columns([2, 2, 2, 1])
        a1 = s1.text_input("Lead Source 1", key="all_ls1")
        a2 = s2.text_input("Lead Source 2", key="all_ls2")
        a3 = s3.text_input("Lead Source 3", key="all_ls3")
        s4.markdown("&nbsp;")
        if s4.button("Apply to all"):
            for rec in batch:
                if a1:
                    rec["row"]["LeadSource1"] = a1
                if a2:
                    rec["row"]["LeadSource2"] = a2
                if a3:
                    rec["row"]["LeadSource3"] = a3
            st.rerun()

    st.markdown("#### Preview & edit")
    st.caption("Edit any cell — changes are kept automatically.")
    grid_df = pd.DataFrame([{c: rec["row"].get(c, "") for c in core.PRIMARY_COLS} for rec in batch])
    edited = st.data_editor(grid_df, num_rows="fixed", use_container_width=True, key="dash_editor")
    for i, rec in enumerate(batch):
        for c in core.PRIMARY_COLS:
            rec["row"][c] = "" if pd.isna(edited.iloc[i][c]) else str(edited.iloc[i][c])

    # how the agent read each thread (lead vs vendor) — helps verify universal logic
    with st.expander("🤖 How the agent read each email"):
        for i, rec in enumerate(batch):
            who = f"{rec['row'].get('FirstName','')} {rec['row'].get('LastName','')}".strip() or "?"
            comp = rec["row"].get("Company", "")
            st.markdown(f"**[{i}] {rec.get('source_file','')}** → lead: **{who}**"
                        + (f" ({comp})" if comp else ""))
            if rec.get("reason"):
                st.caption("Why: " + rec["reason"])
            if rec.get("vendor"):
                st.caption("Vendor/forwarder: " + rec["vendor"])

    with st.expander("Show all 54 export columns"):
        st.dataframe(pd.DataFrame([rec["row"] for rec in batch])[core.EXCEL_HEADER],
                     use_container_width=True)

    # ── attachments: select → confirm (1) or order+merge (2+) → one PDF ─────────
    if n_with_att:
        st.markdown("#### 📎 Attachments → PDF")
        st.caption("Tick the valid files for each lead. One file → Confirm (renamed to a unique PDF). "
                   "Two or more → set order and Merge into one PDF. The name goes into the PDF column.")
        for i, rec in enumerate(batch):
            atts = rec["attachments"]
            if not atts:
                continue
            label = rec["row"].get("Company") or rec["row"].get("LastName") or rec.get("source_file") or f"record {i}"
            done = rec["row"].get("PDF", "")
            head = f"📎 [{i}] {label} — {len(atts)} attachment(s)" + (f"  ✅ {done}" if done else "")
            with st.expander(head):
                # thumbnails for quick validity check
                images = [(n, d) for n, d in atts if Path(n).suffix.lower() in core.IMAGE_EXTS]
                if images:
                    cols = st.columns(min(4, len(images)))
                    for j, (n, d) in enumerate(images):
                        with cols[j % len(cols)]:
                            try:
                                st.image(d, caption=n, width=140)
                            except Exception:
                                st.caption(n)

                # selection / ordering grid (only PDF + image files can become a PDF)
                pdfable = [(n, d) for n, d in atts if Path(n).suffix.lower() in core.MERGEABLE_EXTS]
                other = [(n, d) for n, d in atts if Path(n).suffix.lower() not in core.MERGEABLE_EXTS]
                if other:
                    st.caption("Can't go into a PDF (kept in the email, not the merged file): "
                               + ", ".join(n for n, _ in other))

                if not pdfable:
                    st.caption("No PDF/image attachments to turn into a PDF for this lead.")
                    continue

                sel_df = pd.DataFrame([{"include": True, "order": k + 1, "file": n}
                                       for k, (n, _) in enumerate(pdfable)])
                sel = st.data_editor(
                    sel_df, hide_index=True, use_container_width=True, key=f"sel_{i}",
                    column_config={
                        "include": st.column_config.CheckboxColumn("Use"),
                        "order": st.column_config.NumberColumn("Order", min_value=1, step=1),
                        "file": st.column_config.TextColumn("File", disabled=True),
                    })
                chosen = sel[sel["include"] == True].sort_values("order")  # noqa: E712
                by_name = {n: d for n, d in pdfable}
                items = [(r["file"], by_name[r["file"]]) for _, r in chosen.iterrows()]

                btn_label = "✅ Confirm (1 file → PDF)" if len(items) == 1 else f"🔗 Merge {len(items)} files → PDF"
                if st.button(btn_label, key=f"make_{i}", disabled=len(items) == 0):
                    company = rec["row"].get("Company", "")
                    date_str = rec["row"].get("ReceivedDateTime", "")
                    if len(items) == 1:
                        pdf = core.single_to_pdf(items[0][0], items[0][1])
                    else:
                        pdf = core.merge_to_pdf(items)
                    if pdf:
                        name = core.unique_pdf_name(company, date_str)
                        rec["row"]["PDF"] = name
                        rec["pdf_bytes"] = pdf
                        st.success(f"Created **{name}** ({len(items)} file(s)). Added to the export package.")
                        st.rerun()
                    else:
                        st.error("Could not build a PDF from the selected file(s).")

                if done:
                    cdl, ccl = st.columns([1, 1])
                    cdl.download_button("📄 Download this PDF", data=rec.get("pdf_bytes", b""),
                                        file_name=done, mime="application/pdf", key=f"dl_{i}")
                    if ccl.button("↩️ Undo / redo selection", key=f"undo_{i}"):
                        rec["row"]["PDF"] = ""
                        rec.pop("pdf_bytes", None)
                        st.rerun()

    # ── export: Excel + all produced PDFs as one ZIP ────────────────────────────
    st.divider()
    st.markdown("#### Export")
    made = {rec["row"]["PDF"]: rec["pdf_bytes"]
            for rec in batch if rec.get("pdf_bytes") and rec["row"].get("PDF")}
    pending = [i for i, rec in enumerate(batch) if rec["attachments"] and not rec["row"].get("PDF")]
    if pending:
        st.warning(f"{len(pending)} lead(s) have attachments not yet turned into a PDF "
                   f"(records: {', '.join(map(str, pending))}). Their PDF column will be blank.")
    st.caption(f"Package will contain leads.xlsx + {len(made)} PDF(s).")

    x1, x2 = st.columns([2, 1])
    with x1:
        st.download_button(
            "📦 Download package (ZIP: Excel + PDFs)", type="primary",
            data=core.build_zip([rec["row"] for rec in batch], made),
            file_name="leads_package.zip", mime="application/zip")
    with x2:
        st.download_button(
            "📥 Excel only",
            data=core.make_excel([rec["row"] for rec in batch]),
            file_name="leads.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    c1, c2 = st.columns([1, 1])
    with c1:
        idx = st.selectbox("Remove record #", options=list(range(len(batch))),
                           format_func=lambda i: f"{i} — {batch[i]['row'].get('Company') or batch[i]['row'].get('LastName') or 'record'}")
        if st.button("🗑️ Remove"):
            batch.pop(idx)
            st.rerun()
    with c2:
        st.markdown("&nbsp;")
        if st.button("Clear all"):
            st.session_state.batch = []
            st.rerun()
