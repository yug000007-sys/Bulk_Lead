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


def _render_pdf_made(rec, i):
    """Download + undo controls shown once a lead's PDF has been built."""
    done = rec["row"].get("PDF", "")
    if not done:
        return
    cdl, ccl = st.columns([1, 1])
    cdl.download_button("📄 Download this PDF", data=rec.get("pdf_bytes", b""),
                        file_name=done, mime="application/pdf", key=f"dl_{i}")
    if ccl.button("↩️ Undo this PDF", key=f"undo_{i}"):
        rec["row"]["PDF"] = ""
        rec.pop("pdf_bytes", None)
        if "_orig_comment" in rec:          # restore the full comment if it was shortened
            rec["row"]["LeadComments"] = rec.pop("_orig_comment")
        st.rerun()

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

    st.divider()
    st.markdown("**Timezone (for email timestamps)**")
    UTC_OFFSETS = {
        "UTC+0  (London winter, GMT)": 0,
        "UTC-4  (US Eastern — EDT, summer)": -4,
        "UTC-5  (US Eastern — EST, winter / Central EDT)": -5,
        "UTC-6  (US Central — CST / Mountain EDT)": -6,
        "UTC-7  (US Mountain — MST / Pacific EDT)": -7,
        "UTC-8  (US Pacific — PST)": -8,
        "UTC+1  (Central Europe — CET)": 1,
        "UTC+2  (Eastern Europe — EET / CEST)": 2,
        "UTC+3  (Moscow / Gulf)": 3,
        "UTC+5:30 (India — IST)": 5.5,
        "UTC+8  (China / Singapore / Perth)": 8,
        "UTC+9  (Japan / Korea)": 9,
        "UTC+10 (Sydney AEST)": 10,
    }
    tz_label = st.selectbox("Your UTC offset", list(UTC_OFFSETS.keys()), index=1,
                            help="Shifts email timestamps from UTC to your local time, "
                                 "matching what Outlook displays.")
    utc_offset = UTC_OFFSETS[tz_label]

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
            parsed = ee.parse_msg(mf.getvalue(), Path(mf.name).stem, utc_offset_hours=utc_offset)
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
                "inline_image_labels": parsed.get("inline_image_labels", []),
                "vendor": fields.get("VendorContext", ""),
                "reason": fields.get("AgentReason", ""),
                "source_file": mf.name,
                "raw_body": parsed.get("display_body", parsed.get("body", "")),
                "raw_sender": parsed.get("sender", ""),
                "raw_subject": parsed.get("subject", ""),
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
dash_col, clear_col = st.columns([6, 1])
dash_col.subheader("2. Dashboard")
if clear_col.button("🗑️ Clear All", type="secondary", use_container_width=True,
                    help="Remove all uploaded leads and start fresh"):
    st.session_state.batch = []
    st.rerun()

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

    # ── One-click Make PDF per lead ─────────────────────────────────────────────
    st.markdown("#### ⚡ Quick Make PDF")
    st.caption("One click per lead — builds PDF from inline images and/or request text. "
               "PDF name is written into the PDF column and included in the export ZIP.")
    qcols = st.columns(min(4, len(batch)))
    for i, rec in enumerate(batch):
        col = qcols[i % len(qcols)]
        label = (rec["row"].get("Company") or rec["row"].get("LastName")
                 or rec.get("source_file") or f"#{i}")
        done = rec["row"].get("PDF", "")
        btn_label = f"✅ #{i} {label[:18]}" if done else f"📄 #{i} {label[:18]}"
        if col.button(btn_label, key=f"qmake_{i}", help=done or "Build PDF for this lead"):
            inline = rec.get("inline_image_labels", [])
            request_text = rec["row"].get("LeadComments", "")
            # Also include file attachments that are images/PDFs
            from pathlib import Path as _Path
            file_items = [(n, d) for n, d in rec.get("attachments", [])
                          if _Path(n).suffix.lower() in core.MERGEABLE_EXTS]
            pdf_bytes = None
            if inline:
                # Inline images path — memo style with labels
                pdf_bytes = core.inline_images_to_pdf(
                    inline, request_text=request_text,
                    title=rec["row"].get("Subject", "Customer Request") or "Customer Request"
                )
            elif file_items:
                # File attachments path — existing merge logic
                pdf_bytes = core.combine_pdfs(file_items)
            elif request_text:
                # Text-only — parts table / comment memo
                built = core.comment_to_pdf(request_text,
                                            title="Request for Quotation",
                                            reference=rec["row"].get("Product", ""))
                if built:
                    pdf_bytes = built[0]
            if pdf_bytes:
                name = core.unique_pdf_name()
                rec["row"]["PDF"] = name
                rec["pdf_bytes"] = pdf_bytes
                st.success(f"PDF created: **{name}**")
                st.rerun()
            else:
                st.warning(f"Nothing to build for lead #{i}.")

    st.divider()

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

    # ── Raw email viewer: editable body + Make PDF from selection ────────────────
    with st.expander("📧 View raw email / Make PDF from selection"):
        st.caption("Select a lead to inspect its raw email. Edit the text area down to "
                   "what you want, then click Make PDF — the result is merged with any "
                   "images and written into the PDF column.")
        raw_idx = st.selectbox("Lead", options=list(range(len(batch))),
                               format_func=lambda i: (
                                   f"#{i} — "
                                   + (batch[i]["row"].get("Company")
                                      or batch[i]["row"].get("LastName")
                                      or batch[i].get("source_file", f"record {i}"))
                               ), key="raw_sel")
        rrec = batch[raw_idx]

        # Header info
        rc1, rc2, rc3 = st.columns(3)
        rc1.markdown(f"**From:** {rrec.get('raw_sender', '—')}")
        rc2.markdown(f"**Subject:** {rrec.get('raw_subject', '—')}")
        rc3.markdown(f"**Date:** {rrec['row'].get('ReceivedDateTime', '—')}")

        # Attachment decisions
        decisions = rrec.get("decisions", [])
        if decisions:
            with st.expander(f"Attachments ({len(decisions)} found)", expanded=False):
                for d in decisions:
                    icon = "✅" if d.get("decision") == "Keep" else "❌"
                    st.caption(f"{icon} **{d.get('filename','?')}** — {d.get('reason','')}")

        # Editable body text
        st.markdown("**Email body** — inline images shown as `[📷 filename]` placeholders. "
                    "Trim to the text you want in the PDF:")
        edited_body = st.text_area(
            "Email body",
            value=rrec.get("raw_body", ""),
            height=300,
            key=f"raw_body_{raw_idx}",
            label_visibility="collapsed",
        )

        # Make PDF from selection button
        col_btn, col_info = st.columns([1, 3])
        if col_btn.button("📄 Make PDF from this text", key=f"sel_pdf_{raw_idx}",
                          type="primary"):
            from pathlib import Path as _Path
            inline = rrec.get("inline_image_labels", [])
            file_items = [(n, d) for n, d in rrec.get("attachments", [])
                          if _Path(n).suffix.lower() in core.MERGEABLE_EXTS]
            parts = []
            # Text memo first
            if edited_body.strip():
                built = core.comment_to_pdf(
                    edited_body.strip(),
                    title=rrec.get("raw_subject", "") or "Customer Request",
                    reference=rrec["row"].get("Product", ""),
                )
                if built:
                    parts.append(("memo.pdf", built[0]))
                else:
                    # comment_to_pdf returns None when no parts table found —
                    # fall back to plain text memo via inline_images_to_pdf
                    plain_pdf = core.inline_images_to_pdf(
                        [], request_text=edited_body.strip(),
                        title=rrec.get("raw_subject", "") or "Customer Request",
                    )
                    if plain_pdf:
                        parts.append(("memo.pdf", plain_pdf))
            # Then inline images
            if inline:
                img_pdf = core.inline_images_to_pdf(
                    inline, request_text="",
                    title=rrec.get("raw_subject", "") or "Customer Request",
                )
                if img_pdf:
                    parts.append(("images.pdf", img_pdf))
            # Then file attachments
            parts.extend(file_items)

            if parts:
                pdf_bytes = core.combine_pdfs(parts) if parts else None
                if pdf_bytes:
                    name = core.unique_pdf_name()
                    rrec["row"]["PDF"] = name
                    rrec["pdf_bytes"] = pdf_bytes
                    col_info.success(f"✅ Created **{name}**")
                    st.rerun()
            else:
                col_info.warning("Nothing to build — add some text or check attachments.")

    with st.expander("Show all 54 export columns"):
        st.dataframe(pd.DataFrame([rec["row"] for rec in batch])[core.EXCEL_HEADER],
                     use_container_width=True)

    # ── attachments: select → confirm (1) or order+merge (2+) → one PDF ─────────
    # ── build one PDF per lead: comment parts-table memo + selected attachments ──
    buildable = []
    for i, rec in enumerate(batch):
        _intro, _rows = core.parse_parts_table(rec["row"].get("LeadComments", ""))
        rec["_table_rows"] = len(_rows)
        pdfable = [(n, d) for n, d in rec["attachments"]
                   if Path(n).suffix.lower() in core.MERGEABLE_EXTS]
        rec["_pdfable"] = pdfable
        if pdfable or len(_rows) >= 3:
            buildable.append(i)

    if buildable:
        st.markdown("#### 🧷 Build PDF (per lead)")
        st.caption("For leads with a long parts list and/or attachments. Make a memo PDF of the "
                   "comment table, optionally append the attachments, and the unique name goes "
                   "into the PDF column. The comment is shortened to the request text.")
        for i in buildable:
            rec = batch[i]
            label = rec["row"].get("Company") or rec["row"].get("LastName") or rec.get("source_file") or f"record {i}"
            done = rec["row"].get("PDF", "")
            n_tbl = rec["_table_rows"]
            pdfable = rec["_pdfable"]
            tag = []
            if n_tbl >= 3:
                tag.append(f"{n_tbl}-item table")
            if pdfable:
                tag.append(f"{len(pdfable)} attachment(s)")
            head = f"🧷 [{i}] {label} — " + ", ".join(tag) + (f"  ✅ {done}" if done else "")
            with st.expander(head):
                make_table = False
                if n_tbl >= 3:
                    make_table = st.checkbox(f"Include parts table as memo page ({n_tbl} items)",
                                             value=True, key=f"tbl_{i}")

                # attachment thumbnails + selection
                items = []
                if pdfable:
                    images = [(n, d) for n, d in rec["attachments"] if Path(n).suffix.lower() in core.IMAGE_EXTS]
                    if images:
                        cols = st.columns(min(4, len(images)))
                        for j, (n, d) in enumerate(images):
                            with cols[j % len(cols)]:
                                try:
                                    st.image(d, caption=n, width=140)
                                except Exception:
                                    st.caption(n)
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

                other = [n for n, _ in rec["attachments"] if Path(n).suffix.lower() not in core.MERGEABLE_EXTS]
                if other:
                    st.caption("Not added to the PDF (kept in the email): " + ", ".join(other))

                disabled = not (make_table or items)
                if st.button("📄 Make / update PDF for this lead", key=f"make_{i}",
                             disabled=disabled, type="primary"):
                    company = rec["row"].get("Company", "")
                    date_str = rec["row"].get("ReceivedDateTime", "")
                    parts = []
                    short_comment = None
                    if make_table:
                        ref = rec["row"].get("Product", "") or rec["row"].get("Subject", "")
                        built = core.comment_to_pdf(rec["row"].get("LeadComments", ""),
                                                    title="Request for Quotation", reference=ref)
                        if built:
                            memo_bytes, _n, short_comment = built
                            parts.append(("comment.pdf", memo_bytes))
                    parts.extend(items)
                    pdf = core.combine_pdfs(parts) if parts else None
                    if pdf:
                        name = core.unique_pdf_name(company, date_str)
                        rec.setdefault("_orig_comment", rec["row"].get("LeadComments", ""))
                        rec["row"]["PDF"] = name
                        rec["pdf_bytes"] = pdf
                        if short_comment is not None:
                            rec["row"]["LeadComments"] = short_comment
                        st.success(f"Created **{name}** "
                                   f"({'memo' if make_table else ''}{' + ' if make_table and items else ''}"
                                   f"{str(len(items)) + ' file(s)' if items else ''}).")
                        st.rerun()
                    else:
                        st.error("Nothing selected to build a PDF from.")

                _render_pdf_made(rec, i)


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
