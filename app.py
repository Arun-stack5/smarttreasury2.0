"""SmartTreasury dashboard.  Run:  streamlit run app.py"""
import io
import pandas as pd
import streamlit as st
from engine import DEFAULT_CONFIG, run_matcher, inr
from sample_data import SAMPLE_ROWS
import treasury_sheet as sh

st.set_page_config(page_title="SmartTreasury", page_icon="💰", layout="wide")
CFG = dict(DEFAULT_CONFIG)

# ------------------------------------------------------------------ sidebar
st.sidebar.title("💰 SmartTreasury")
def auth_enabled():
    try: return "auth" in st.secrets
    except Exception: return False

if auth_enabled():                      # hosted mode: Google login, one sheet per user
    if not st.user.is_logged_in:
        st.title("💰 SmartTreasury")
        st.write("Sign in with Google. You get your own private sheet and dashboard.")
        st.button("Sign in with Google", on_click=st.login, type="primary"); st.stop()
    if not st.user.get("email_verified", True): st.error("Your Google email is not verified."); st.stop()
    EMAIL, source = st.user.email, "My sheet"
else:                                   # local/dev mode
    source = st.sidebar.radio("Data source", ["Google Sheet", "Demo data", "Upload CSV / Excel"])
raw, ws = None, None

def creds():
    try: return dict(st.secrets["gcp_service_account"])
    except Exception: return None

def sa_email():
    import json, os
    try:
        info = creds() or json.load(open(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")))
        return info["client_email"]
    except Exception:
        return None

if source == "My sheet":
    st.sidebar.write(f"👤 {EMAIL}"); st.sidebar.button("Log out", on_click=st.logout)
    try:
        if st.session_state.get("ws_email") != EMAIL:
            _ws, _new, _url = sh.user_sheet(sh.get_client(creds()), EMAIL)
            st.session_state.update(ws=_ws, ws_email=EMAIL, ws_url=_url, created=_new)
        ws = st.session_state["ws"]
        if st.session_state.pop("created", False):
            st.success("Your sheet was created (with sample rows) and shared to your email. Replace the sample rows with your data.")
        st.sidebar.link_button("📄 Open my Google Sheet", st.session_state["ws_url"])
        if st.sidebar.button("🔄 Refresh"): st.cache_data.clear()
        if st.sidebar.button("🧹 Clear sample rows"): ws.batch_clear([f"A2:G{sh.LAST_ROW}"]); st.rerun()
        raw = sh.load_sheet(ws)
    except Exception as e:
        st.sidebar.error(f"Could not open your sheet ({type(e).__name__}): {e}")
elif source == "Google Sheet":
    _mail = sa_email()
    if _mail: st.sidebar.info(f"Share your sheet (Editor) with:\n\n`{_mail}`")
    else: st.sidebar.warning("service_account.json not found in the folder you ran streamlit from.")
    try: default_url = st.secrets["SHEET_URL"]
    except Exception: default_url = ""
    url = st.sidebar.text_input("Sheet URL or ID", default_url)
    tab = st.sidebar.text_input("Tab name", "Data")
    if url:
        try:
            ws = sh.open_tab(sh.get_client(creds()), url, tab)
            if st.sidebar.button("⚙️ Set up / repair columns", help="Writes headers, formats & validation. Existing rows are kept."):
                sh.setup_sheet(ws); st.sidebar.success("Columns defined ✔")
            if st.sidebar.button("🧪 Set up + load sample rows"):
                sh.setup_sheet(ws, with_sample=True); st.sidebar.success("Sample rows written ✔")
            if st.sidebar.button("🔄 Refresh"): st.cache_data.clear()
            raw = sh.load_sheet(ws)
        except Exception as e:
            hint = {"FileNotFoundError": "service_account.json is missing from this folder.",
                    "SpreadsheetNotFound": "Wrong URL, or the sheet is not shared with the email above.",
                    "PermissionError": "Share the sheet with the email above as Editor."}.get(type(e).__name__,
                    "Check: Sheets + Drive APIs enabled, sheet shared with the email above (Editor), URL is correct.")
            st.sidebar.error(f"Could not open sheet ({type(e).__name__}): {e or 'no details'}\n\n{hint}")
    else:
        st.info("Paste your Google Sheet URL in the sidebar. Share the sheet with your service-account email (Editor). See README.")
elif source == "Demo data":
    raw = pd.DataFrame(SAMPLE_ROWS, columns=sh.INPUT_COLS)
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

# ------------------------------------------------------------------ run
st.title("SmartTreasury — Matcher Dashboard")
if raw is None or raw.empty:
    if source in ("Google Sheet", "My sheet") and ws is not None:
        st.warning("Connected, but the sheet has no data rows. Click '⚙️ Set up / repair columns' or '🧪 Set up + load sample rows' in the sidebar, then refresh.")
    st.stop()
recs, pays, warns = sh.split_book(raw)
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

def show(df, money=(), pct=(), rename=None):
    d = df.copy()
    for c in money: d[c] = d[c].map(inr)
    for c in pct: d[c] = d[c].map(lambda x: f"{x:g}%")
    st.dataframe(d.rename(columns=rename or {}), width="stretch", hide_index=True)

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
            "cal_to_year_end", "surplus_route", "surplus_rate", "surplus_income"]], money=["amount", "total_funded", "surplus", "surplus_income"], pct=["surplus_rate"])
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
        o = res["od_repayments"]; ev = pd.concat([ev, pd.DataFrame({"date": o["due_date"], "ref": o["ref"], "flow": -o["amount"]})])
    ev = ev.sort_values("date"); ev["cumulative"] = ev["flow"].cumsum()
    st.line_chart(ev.set_index("date")["cumulative"])
    st.caption("Cumulative net cash: receivables (+) and payables (−) in date order, before OD draws.")
with t6:
    st.dataframe(raw.astype(str), width="stretch", hide_index=True)
    st.caption("+ve Amount = receivable, −ve Amount = payable. Edit in Google Sheets, then hit Refresh.")

buf = io.BytesIO()
with pd.ExcelWriter(buf) as xw:
    A.to_excel(xw, sheet_name="Payable coverage", index=False); B.to_excel(xw, sheet_name="Receivable surplus", index=False); C.to_excel(xw, sheet_name="OD schedule", index=False)
st.sidebar.download_button("⬇️ Download results (xlsx)", buf.getvalue(), "smarttreasury_results.xlsx")
