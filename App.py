"""SmartTreasury dashboard (LOCAL).
Run:  python -m streamlit run app.py --server.port 8501"""
import io, traceback
import streamlit as st

st.set_page_config(page_title="SmartTreasury", page_icon="💰", layout="wide")
try:
    import pandas as pd
    from engine import DEFAULT_CONFIG, run_matcher, inr
    import google_io as gio
except Exception:                                   # show the real problem instead of a blank page
    st.error("The app could not start. Copy this text and send it to your helper:")
    st.code(traceback.format_exc()); st.stop()

CFG = dict(DEFAULT_CONFIG)


def _load_hosted_config():
    """On a public host the Google client id/secret live in Secrets (or environment variables), not in a file."""
    import os, pathlib
    cid, sec, red = (os.getenv("GOOGLE_CLIENT_ID"), os.getenv("GOOGLE_CLIENT_SECRET"), os.getenv("OAUTH_REDIRECT"))
    if cid and sec and red and red.startswith("https://"): return cid, sec, red
    here = [pathlib.Path.home() / ".streamlit" / "secrets.toml", pathlib.Path.cwd() / ".streamlit" / "secrets.toml"]
    if not (any(p.exists() for p in here) or str(pathlib.Path.cwd()).startswith("/mount")):
        return None                                  # local run without secrets: do not touch st.secrets (avoids the red banner)
    try:
        s = st.secrets["google_oauth"]
        return s["client_id"], s["client_secret"], s["redirect_uri"]
    except Exception:
        return None


_hc = _load_hosted_config()
if _hc: gio.configure_hosted(*_hc)
st.sidebar.title("💰 SmartTreasury")
status = gio.oauth_status()
source = st.sidebar.radio("Data source", ["My Google account", "Demo data", "Upload CSV / Excel"],
                          index=0 if status["ok"] else 1)
raw, ws = None, None


def setup_panel():
    with st.expander("🔧 Setup check", expanded=not status["ok"]):
        for line in status["lines"]: st.write(line)
        if status["files"]:
            st.write("JSON files in this folder:", {n: k for n, k in status["files"]})


# ------------------------------------------------------------------ data source
if source == "My Google account":
    st.session_state.setdefault("uemail", None)
    q = st.query_params
    if "error" in q:                                # user pressed Cancel at Google
        st.warning(f"Google sign-in was cancelled ({q['error']}).")
        st.query_params.clear()
    elif "code" in q and not st.session_state["uemail"]:
        try:
            st.session_state["uemail"], st.session_state["utok"] = gio.finish_login(q["code"])
        except Exception as e: st.error(f"Google sign-in failed ({type(e).__name__}): {e}")
        st.query_params.clear()
        if st.session_state["uemail"]: st.rerun()

    UE = st.session_state["uemail"]
    if not UE:
        st.title("💰 SmartTreasury")
        st.write("Sign in with your Google account. A demo sheet with the right columns is created in "
                 "**your own Google Drive** and connected to your dashboard. Only you can see it.")
        setup_panel()
        if status["ok"]:
            try: st.link_button("Sign in with Google", gio.login_url(), type="primary")
            except Exception as e: st.error(f"Could not build the Google sign-in link ({type(e).__name__}): {e}")
        known = gio.known_users()
        if known:
            st.caption("Or continue as an account that already signed in on this computer:")
            for em in known:
                if st.button(f"Continue as {em}", key="k_" + em):
                    st.session_state["uemail"], st.session_state["utok"] = em, None; st.rerun()
        st.stop()

    st.sidebar.write(f"👤 {UE}")
    if st.sidebar.button("Log out"):
        for k in ("uemail", "utok", "uws", "uws_email"): st.session_state.pop(k, None)
        st.rerun()
    try:
        if st.session_state.get("uws_email") != UE:
            _ws, _new, _url, _note = gio.user_sheet(UE, st.session_state.get("utok"))
            st.session_state.update(uws=_ws, uws_email=UE, uws_url=_url, ucreated=_new, unote=_note)
        ws = st.session_state["uws"]
        if st.session_state.pop("ucreated", False):
            st.success("Your demo sheet 'SmartTreasury - Data' was created in your own Google Drive. Replace the sample rows with your data.")
        if st.session_state.get("unote"): st.info(st.session_state["unote"])
        st.sidebar.link_button("📄 Open my Google Sheet", st.session_state["uws_url"])
        if st.sidebar.button("🔄 Refresh"): st.rerun()
        if st.sidebar.button("⚙️ Repair columns"): st.sidebar.info(gio.setup_sheet(ws) or "Columns defined ✔")
        if st.sidebar.button("🧹 Clear sample rows"): ws.batch_clear([f"A2:G{gio.LAST_ROW}"]); st.rerun()
        raw = gio.load_sheet(ws)
    except Exception as e:
        if type(e).__name__ == "RefreshError":       # access revoked -> sign in again
            gio.forget(UE)
            for k in ("uemail", "utok", "uws", "uws_email"): st.session_state.pop(k, None)
            st.error("Google access expired or was revoked. Please sign in again."); st.stop()
        st.sidebar.error(f"Could not open your sheet ({type(e).__name__}): {e}")
elif source == "Demo data":
    raw = pd.DataFrame(gio.SAMPLE_ROWS, columns=gio.INPUT_COLS)
else:
    up = st.sidebar.file_uploader("File with the sheet's columns", type=["csv", "xlsx"])
    if up: raw = pd.read_csv(up) if up.name.endswith("csv") else pd.read_excel(up)

with st.sidebar.expander("⚙️ Matcher settings"):
    CFG["STRATEGY"] = st.selectbox("Strategy", ["Auto", "Aggressive", "Conservative"])
    CFG["OD_LIMIT"] = st.number_input("OD limit (₹)", 0, value=CFG["OD_LIMIT"], step=1_000_000)
    CFG["OD_RATE"] = st.number_input("OD rate % p.a.", value=CFG["OD_RATE"])
    CFG["OD_WINDOW"] = st.number_input("OD bridge window (WD)", 1, value=CFG["OD_WINDOW"])
    CFG["OD_REP_BUF"] = st.number_input("OD repayment buffer (WD)", 0, value=CFG["OD_REP_BUF"])
    CFG["OD_INC_INT"] = st.checkbox("OD repayment includes interest", CFG["OD_INC_INT"])
    CFG["YEAR_END"] = st.date_input("Investment horizon", CFG["YEAR_END"])
    st.caption("Investment tiers")
    for k in ("MIN_INVEST_WD", "LF_MAX_WD", "LB_MAX_WD", "NEO_MIN_AMT", "SAV_RATE", "LF_RATE", "LB_RATE", "NEO_RATE"):
        CFG[k] = st.number_input(k, value=CFG[k])

# ------------------------------------------------------------------ run the matcher
st.title("SmartTreasury — Matcher Dashboard")
if raw is None or raw.empty:
    if ws is not None:
        st.warning("Connected, but the sheet has no data rows. Click '⚙️ Repair columns' and add rows in Google Sheets, then Refresh.")
    st.stop()
recs, pays, warns = gio.split_book(raw)
for w in warns: st.warning(w)
if recs.empty and pays.empty: st.stop()
res = run_matcher(recs, pays, CFG)
S, A, B, C = res["summary"], res["payables"], res["receivables"], res["od_schedule"]

tot_r, tot_p = recs["amount"].sum(), pays["amount"].sum()
k = st.columns(6)
k[0].metric("Receivables (+)", inr(tot_r), f"{len(recs)} invoices")
k[1].metric("Payables (−)", inr(-tot_p), f"{len(pays)} payments")
k[2].metric("Net position", inr(tot_r - tot_p))
k[3].metric("Gross treasury income", inr(S["income_a"] + S["income_b"]))
k[4].metric("OD interest", inr(S["od_interest"]))
k[5].metric("Net treasury income", inr(S["net_income"]))
st.caption(f"Strategy: **{S['mode']}** · probability ≥ {S['prob_threshold']:.0%} · buffer {S['wd_buffer']} WD")


def show(df, money=(), pct=()):
    d = df.copy()
    for c in money: d[c] = d[c].map(inr)
    for c in pct: d[c] = d[c].map(lambda x: f"{x:g}%")
    st.dataframe(d, width="stretch", hide_index=True)


t1, t2, t3, t4, t5, t6 = st.tabs(["📊 Overview", "A · Payable coverage", "B · Receivable surplus", "C · OD schedule", "Cash timeline", "Sheet data"])
with t1:
    a, b = st.columns(2)
    a.subheader("Funding status of payables"); a.bar_chart(A["fund_status"].value_counts())
    b.subheader("Income by instrument (₹)")
    inc = pd.concat([A.groupby("route")["income"].sum(), B.groupby("surplus_route")["surplus_income"].sum()], axis=1).fillna(0).sum(axis=1)
    b.bar_chart(inc[inc.index != "—"])
    st.subheader("Needs attention")
    bad = A[~A["fund_status"].isin(["✅ Fully Funded", "⚡ Partial + OD", "🏦 OD Bridge", "🏦 Split OD"])]
    if bad.empty: st.success("All payables are funded (directly or via OD).")
    else: show(bad[["ref", "party", "amount", "due_date", "fund_status"]], money=["amount"])
with t2:
    show(A[["ref", "party", "amount", "due_date", "effective_due", "matched_receivable", "rec_party", "rec_use_date", "rec_amount",
            "wd_idle", "calendar_days", "route", "rate", "income", "fund_status", "od_drawn", "od_bridge_detail"]],
         money=["amount", "rec_amount", "income", "od_drawn"], pct=["rate"])
with t3:
    show(B[["ref", "party", "amount", "use_date", "status", "category", "total_funded", "surplus", "wd_to_year_end",
            "cal_to_year_end", "surplus_route", "surplus_rate", "surplus_income"]],
         money=["amount", "total_funded", "surplus", "surplus_income"], pct=["surplus_rate"])
with t4:
    if C.empty: st.info("No OD drawn.")
    else:
        show(C, money=["OD principal", "OD interest", "Total bank repayment", "Net cash impact"])
        st.subheader("Auto-generated OD repayment payables")
        show(res["od_repayments"], money=["amount"])
with t5:
    ev = pd.concat([recs.assign(date=recs["actual_date"].fillna(recs["expected_date"]), flow=recs["amount"]),
                    pays.assign(date=pays["due_date"], flow=-pays["amount"])])[["date", "ref", "flow"]]
    if not res["od_repayments"].empty:
        o = res["od_repayments"]
        ev = pd.concat([ev, pd.DataFrame({"date": o["due_date"], "ref": o["ref"], "flow": -o["amount"]})])
    ev = ev.sort_values("date"); ev["cumulative"] = ev["flow"].cumsum()
    st.line_chart(ev.set_index("date")["cumulative"])
    st.caption("Cumulative net cash: receivables (+) and payables (−) in date order, before OD draws.")
with t6:
    st.dataframe(raw.astype(str), width="stretch", hide_index=True)
    st.caption("+ve Amount = receivable, −ve Amount = payable. Edit in Google Sheets, then press Refresh.")

buf = io.BytesIO()
with pd.ExcelWriter(buf) as xw:
    A.to_excel(xw, sheet_name="Payable coverage", index=False)
    B.to_excel(xw, sheet_name="Receivable surplus", index=False)
    C.to_excel(xw, sheet_name="OD schedule", index=False)
st.sidebar.download_button("⬇️ Download results (xlsx)", buf.getvalue(), "smarttreasury_results.xlsx")