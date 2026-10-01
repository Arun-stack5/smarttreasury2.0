"""SmartTreasury Matcher Engine (SOP v11). Pure logic, no UI / Google code."""
import numpy as np
import pandas as pd

HOLIDAYS_2026 = ["2026-01-14", "2026-01-26", "2026-02-26", "2026-03-02", "2026-03-20", "2026-03-30",
                 "2026-04-03", "2026-04-14", "2026-04-21", "2026-05-01", "2026-06-04", "2026-07-24",
                 "2026-08-15", "2026-08-24", "2026-10-02", "2026-10-20", "2026-10-21", "2026-11-04",
                 "2026-11-19", "2026-12-25"]

# Rates are in % p.a.; money in INR; dates are datetime.date
DEFAULT_CONFIG = dict(
    MIN_INVEST_WD=7, LF_MAX_WD=10, LB_MAX_WD=90, NEO_MIN_AMT=5_000_000,
    SAV_RATE=3.5, LF_RATE=6.0, LB_RATE=8.0, NEO_RATE=10.0,
    YEAR_END=pd.Timestamp("2026-12-31").date(),
    OD_LIMIT=50_000_000, OD_WINDOW=10, OD_RATE=12.0, OD_BASIS=365, OD_INC_INT=True, OD_REP_BUF=2,
    STRATEGY="Auto",  # Auto | Aggressive | Conservative
)
STRATEGIES = {"Aggressive": (0.50, 2), "Conservative": (0.75, 5)}  # (PROB_THRESHOLD, WD_BUFFER)
NO_MATCH, BIG = "No Match", 999_999


def _hol(h): return np.array(h, dtype="datetime64[D]")
def workday(d, n, hol):
    """Excel WORKDAY: negative n rolls a weekend start forward first, positive rolls back."""
    r = np.busday_offset(np.datetime64(d), n, roll="backward" if n > 0 else "forward", holidays=hol)
    return pd.Timestamp(r).date()
def networkdays(a, b, hol):
    """Excel NETWORKDAYS (inclusive of both ends); 0 if b < a."""
    return int(np.busday_count(np.datetime64(a), np.datetime64(b) + 1, holidays=hol)) if b >= a else 0


def strategy_params(cfg, pays):
    mode = cfg["STRATEGY"]
    if mode == "Auto":
        months = max(1, len({(p["due_date"].year, p["due_date"].month) for p in pays}))
        avg_month = sum(p["amount"] for p in pays) / months
        mode = "Aggressive" if cfg["OD_LIMIT"] >= avg_month else "Conservative"
    return mode, *STRATEGIES[mode]


def route_for(wd_idle, amt, c):
    if wd_idle <= 0: return "—", 0.0
    if wd_idle < c["MIN_INVEST_WD"]: return "Savings Account", c["SAV_RATE"]
    if wd_idle <= c["LF_MAX_WD"]: return "Liquid Fund", c["LF_RATE"]
    if wd_idle <= c["LB_MAX_WD"]: return "Liquid Bonds", c["LB_RATE"]
    if amt >= c["NEO_MIN_AMT"]: return "Neo Yield Enhancer", c["NEO_RATE"]
    return "Liquid Bonds", c["LB_RATE"]


def inr(x):
    """Indian digit grouping: 25032877 -> ₹2,50,32,877"""
    import re
    s = f"{abs(round(x)):d}"
    s = s[:-3] and re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3]) + "," + s[-3:] or s
    return ("-₹" if x < 0 else "₹") + s


def run_matcher(recs: pd.DataFrame, pays: pd.DataFrame, cfg: dict, holidays=HOLIDAYS_2026):
    """recs: ref, party, amount(+), expected_date, actual_date, probability
       pays: ref, party, amount(+ abs value), due_date, priority"""
    c, hol = {**DEFAULT_CONFIG, **cfg}, _hol(holidays)
    P = sorted(pays.to_dict("records"), key=lambda p: p["due_date"])
    mode, thr, buf = strategy_params(c, P)

    # ---- receivables: reliability, adjusted date, use_date, status (SOP 2.2)
    R = []
    for r in recs.to_dict("records"):
        p, exp, act = r["probability"], r["expected_date"], r["actual_date"]
        adj = exp if p >= .75 else workday(exp, buf, hol) if p >= .5 else None
        r.update(category="High" if p >= .75 else "Medium" if p >= .5 else "Low", adjusted_date=adj,
                 use_date=act or adj,
                 early_late_days=(act - exp).days if act else None,
                 status="Awaiting" if not act else "Early" if act < exp else "On Time" if act == exp else "Late")
        R.append(r)

    alloc, out, od_rows, repay_pays = {}, [], [], []
    for p in P:
        due, amt = p["due_date"], p["amount"]
        eff = workday(due, -buf, hol)
        # ---- score eligible receivables (SOP 4.2-4.4)
        best, best_score, best_avail = None, BIG, 0
        for r in R:
            if r["use_date"] is None or r["probability"] < thr or r["use_date"] > eff: continue
            avail = r["amount"] - alloc.get(r["ref"], 0)
            if avail <= 0: continue
            s = networkdays(r["use_date"], eff, hol) - 1
            if s < best_score: best, best_score, best_avail = r, s, avail
        # ---- OD window (SOP 5)
        od_end = workday(due, c["OD_WINDOW"], hol)
        win = [r for r in R if r["use_date"] and r["probability"] >= thr and due <= r["use_date"] <= od_end]
        repay = min(win, key=lambda r: r["use_date"]) if win else None
        best_win = max((r["amount"] for r in win), default=0)
        lim, od, status, covered = c["OD_LIMIT"], 0, "", 0

        if best:
            covered = min(best_avail, amt)
            short = amt - covered
            alloc[best["ref"]] = alloc.get(best["ref"], 0) + covered
            if short <= 0: status = "✅ Fully Funded"
            elif short > lim: status = "⚠️ Partial (gap > OD)"
            elif repay: status, od = "⚡ Partial + OD", short
            else: status = "❌ No rec in window"
        else:
            if not win: status = "🚨 Exceeds OD Limit" if amt > lim else "❌ No rec in window"
            elif best_win >= amt:  # full payment from OD, repaid by window receivable
                status, od = ("🏦 OD Bridge", amt) if amt <= lim else ("🚨 Exceeds OD Limit", 0)
            else:
                need = amt - best_win
                status, od = ("🏦 Split OD", need) if need <= lim else ("🚨 Exceeds OD Limit", 0)
            covered = min(amt, best_win) if od and status == "🏦 Split OD" else 0

        # ---- investment route & income (SOP 6.1-6.2)
        wd_idle = best_score if best else 0
        cal_days = (eff - best["use_date"]).days if best else 0
        rt, rate = route_for(wd_idle, amt, c) if best else ("—", 0.0)
        income = round(amt * rate / 100 / 365 * cal_days) if best else 0

        # ---- OD cost, detail text & auto repayment payable (SOP 5.2-5.6)
        interest = wdr = 0; detail = ""
        if od and repay:
            days = (repay["use_date"] - due).days
            interest = round(od * c["OD_RATE"] / 100 / c["OD_BASIS"] * days)
            wdr = networkdays(due, repay["use_date"], hol)
            total = od + (interest if c["OD_INC_INT"] else 0)
            detail = (f"{'Rec' if best else 'Own funds'} {inr(covered)} + OD {inr(od)} │ OD repaid by "
                      f"{repay['ref']} in {wdr} WD │ Int {inr(interest)} │ Total to bank {inr(od + interest)}")
            rep_ref = "OD-REPAY-" + "".join(ch for ch in p["ref"] if ch.isdigit()).lstrip("0").zfill(2)
            repay_pays.append(dict(ref=rep_ref, party=f"Bank — OD Repayment ({p['ref']})", amount=total,
                                   due_date=workday(repay["use_date"], -c["OD_REP_BUF"], hol), priority=1,
                                   matched_receivable=repay["ref"], fund_status="OD Repayment"))
            od_rows.append({"Triggered by": p["ref"], "OD draw date": due, "OD principal": od,
                            "Repay date": repay["use_date"], "Repaying receivable": repay["ref"],
                            "Days outstanding": days, "OD interest": interest, "Total bank repayment": total,
                            "Net cash impact": -interest})
        out.append(dict(ref=p["ref"], party=p["party"], amount=amt, due_date=due, priority=p.get("priority"),
                        effective_due=eff, matched_receivable=best["ref"] if best else NO_MATCH,
                        rec_party=best["party"] if best else "", rec_use_date=best["use_date"] if best else None,
                        rec_amount=best["amount"] if best else 0, wd_idle=wd_idle, calendar_days=cal_days,
                        route=rt, rate=rate, income=income, fund_status=status, od_drawn=od,
                        od_repay_rec=repay["ref"] if od and repay else "", od_repay_date=repay["use_date"] if od and repay else None,
                        od_wd_to_repay=wdr, od_interest=interest, od_bridge_detail=detail))

    # ---- Section B: receivable surplus (SOP 6.3)
    B = []
    for r in R:
        funded = alloc.get(r["ref"], 0)
        surplus = max(0, r["amount"] - funded) if r["use_date"] else 0
        start = r["actual_date"] or r["use_date"]
        wd_ye = networkdays(start, c["YEAR_END"], hol) if start else 0
        cal_ye = max(0, (c["YEAR_END"] - start).days) if start else 0
        rt, rate = route_for(wd_ye, surplus, c) if surplus else ("—", 0.0)
        B.append({**{k: r[k] for k in ("ref", "party", "amount", "expected_date", "actual_date", "probability",
                  "category", "adjusted_date", "use_date", "early_late_days", "status")},
                  "total_funded": funded, "surplus": surplus, "wd_to_year_end": wd_ye, "cal_to_year_end": cal_ye,
                  "surplus_route": rt, "surplus_rate": rate, "surplus_income": round(surplus * rate / 100 / 365 * cal_ye)})

    A, Bdf, C = pd.DataFrame(out), pd.DataFrame(B), pd.DataFrame(od_rows)
    ia = int(A["income"].sum()) if len(A) else 0
    ib = int(Bdf["surplus_income"].sum()) if len(Bdf) else 0
    oi = int(C["OD interest"].sum()) if len(C) else 0
    return dict(payables=A, receivables=Bdf, od_schedule=C, od_repayments=pd.DataFrame(repay_pays),
                summary=dict(mode=mode, prob_threshold=thr, wd_buffer=buf, income_a=ia, income_b=ib,
                             od_interest=oi, net_income=ia + ib - oi))