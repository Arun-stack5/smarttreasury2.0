"""Google Sheet layer: defines the columns of the single sheet, formats it, and loads it.
CLI:  python treasury_sheet.py <sheet-url-or-id> [--sample] [--tab Data]"""
import os, sys
import pandas as pd
from sample_data import SAMPLE_ROWS

# The single sheet: receivable = POSITIVE amount, payable = NEGATIVE amount.
COLUMNS = [
    ("Ref",         "Unique id, e.g. INV-001 / PAY-001"),
    ("Party",       "Customer (receivable) or vendor (payable)"),
    ("Amount",      "Rupees. RECEIVABLE = positive, PAYABLE = negative"),
    ("Date",        "Receivable: expected date. Payable: due date"),
    ("Actual Date", "Receivables only: date money was actually received (blank until received)"),
    ("Probability", "Receivables only: 0 to 1 (0.85 = 85%)"),
    ("Priority",    "Payables only: 1 = High, 2 = Medium, 3 = Low"),
    ("Type",        "Auto-filled: Receivable / Payable (do not edit)"),
]
INPUT_COLS = [c for c, _ in COLUMNS[:7]]
LAST_ROW = 2000


def get_client(info: dict | None = None):
    import gspread
    if info: return gspread.service_account_from_dict(info)
    return gspread.service_account(filename=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"))


def open_tab(gc, url_or_id: str, tab: str = "Data"):
    sh = gc.open_by_url(url_or_id) if url_or_id.startswith("http") else gc.open_by_key(url_or_id)
    try: return sh.worksheet(tab)
    except Exception: return sh.add_worksheet(tab, rows=LAST_ROW, cols=len(COLUMNS))


def user_sheet(gc, email: str, tab: str = "Data"):
    """Find (or create + share) the personal sheet for this email. Returns (worksheet, created, url)."""
    import gspread
    title = f"SmartTreasury - {email.lower()}"
    try:
        book, created = gc.open(title), False
    except gspread.SpreadsheetNotFound:
        book, created = gc.create(title), True
        book.share(email, perm_type="user", role="writer", notify=True,
                   email_message="Your SmartTreasury sheet. Enter receivables (+) and payables (-) here.")
    if created:
        ws = book.sheet1; ws.update_title(tab)
        setup_sheet(ws, with_sample=True)
    else:
        ws = open_tab(gc, book.id, tab)
    return ws, created, book.url


def setup_sheet(ws, with_sample=False):
    """Write headers, formats, validation and colour rules. Sample rows only if requested."""
    sid = ws.id
    ws.update(values=[[c for c, _ in COLUMNS]], range_name="A1", value_input_option="USER_ENTERED")
    ws.update(values=[[f'=ARRAYFORMULA(IF(C2:C="","",IF(C2:C>0,"Receivable","Payable")))']],
              range_name="H2", value_input_option="USER_ENTERED")
    if with_sample:
        ws.update(values=SAMPLE_ROWS, range_name="A2", value_input_option="USER_ENTERED")

    def rng(c0, c1=None, r0=1, r1=LAST_ROW):
        return dict(sheetId=sid, startRowIndex=r0, endRowIndex=r1, startColumnIndex=c0, endColumnIndex=c1 or c0 + 1)

    def fmt(c0, kind, pattern):
        return {"repeatCell": {"range": rng(c0), "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                               "fields": "userEnteredFormat.numberFormat"}}

    def rule(cond, color):
        return {"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [rng(2)], "booleanRule": {
            "condition": cond, "format": {"textFormat": {"foregroundColor": color}}}}}}

    def valid(c0, cond, msg):
        return {"setDataValidation": {"range": rng(c0), "rule": {"condition": cond, "strict": True, "inputMessage": msg, "showCustomUi": True}}}

    reqs = [
        {"repeatCell": {"range": rng(0, len(COLUMNS), 0, 1), "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": .1, "green": .2, "blue": .35}, "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
        fmt(2, "NUMBER", "#,##0;-#,##0"), fmt(3, "DATE", "dd-mmm-yyyy"), fmt(4, "DATE", "dd-mmm-yyyy"), fmt(5, "PERCENT", "0%"),
        rule({"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]}, {"red": .05, "green": .5, "blue": .2}),
        rule({"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]}, {"red": .8, "green": .1, "blue": .1}),
        valid(2, {"type": "NUMBER_NOT_BETWEEN", "values": [{"userEnteredValue": "-0.0001"}, {"userEnteredValue": "0.0001"}]}, "Receivable = +ve, Payable = -ve (not 0)"),
        valid(3, {"type": "DATE_IS_VALID"}, "Expected date (receivable) or due date (payable)"),
        valid(4, {"type": "DATE_IS_VALID"}, "Only when money is actually received"),
        valid(5, {"type": "NUMBER_BETWEEN", "values": [{"userEnteredValue": "0"}, {"userEnteredValue": "1"}]}, "0 to 1, e.g. 0.85"),
        valid(6, {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in "123"]}, "1 High, 2 Medium, 3 Low"),
    ]
    # clear old rules so re-running setup doesn't stack duplicates
    for _ in range(3): reqs.insert(0, {"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    try: ws.spreadsheet.batch_update({"requests": reqs})
    except Exception:  # nothing to delete on a fresh sheet -> retry without the delete requests
        ws.spreadsheet.batch_update({"requests": reqs[3:]})
    ws.spreadsheet.batch_update({"requests": [{"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 8}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}}]})


def _to_date(v):
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)): return None
    if isinstance(v, (int, float)): return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).date()  # Sheets serial
    t = pd.to_datetime(v, errors="coerce", dayfirst=not str(v)[:4].isdigit())
    return None if pd.isna(t) else t.date()


def _num(v):
    if isinstance(v, (int, float)): return v
    try: return float(str(v).replace(",", "").replace("₹", "").strip())
    except ValueError: return None


def load_sheet(ws) -> pd.DataFrame:
    return pd.DataFrame(ws.get_all_records(value_render_option="UNFORMATTED_VALUE", expected_headers=[]))


def split_book(raw: pd.DataFrame):
    """Raw sheet rows -> (receivables, payables, warnings). +ve amount = receivable, -ve = payable."""
    warns, recs, pays = [], [], []
    raw = raw.rename(columns={c: str(c).strip() for c in raw.columns})
    missing = [c for c in INPUT_COLS if c not in raw.columns]
    if missing: return pd.DataFrame(), pd.DataFrame(), [f"Missing columns: {', '.join(missing)}. Run the setup to define them."]
    for i, r in raw.iterrows():
        row = i + 2
        amt = _num(r["Amount"])
        if amt is None or amt == 0:
            if str(r["Ref"]).strip(): warns.append(f"Row {row} ({r['Ref']}): empty/zero/invalid Amount, skipped")
            continue
        dt = _to_date(r["Date"])
        if dt is None: warns.append(f"Row {row} ({r['Ref']}): missing Date, skipped"); continue
        base = dict(ref=str(r["Ref"]).strip() or f"ROW-{row}", party=str(r["Party"]).strip())
        if amt > 0:
            p = _num(r["Probability"])
            if p is None: warns.append(f"Row {row} ({base['ref']}): no Probability, treated as 0"); p = 0.0
            if p > 1: p = p / 100
            recs.append({**base, "amount": amt, "expected_date": dt, "actual_date": _to_date(r["Actual Date"]), "probability": p})
        else:
            pr = _num(r["Priority"])
            pays.append({**base, "amount": -amt, "due_date": dt, "priority": int(pr) if pr in (1, 2, 3) else 2})
    cols_r = ["ref", "party", "amount", "expected_date", "actual_date", "probability"]
    cols_p = ["ref", "party", "amount", "due_date", "priority"]
    return pd.DataFrame(recs, columns=cols_r), pd.DataFrame(pays, columns=cols_p), warns


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args: sys.exit(__doc__)
    tab = sys.argv[sys.argv.index("--tab") + 1] if "--tab" in sys.argv else "Data"
    if "--tab" in sys.argv: args.remove(tab)
    ws = open_tab(get_client(), args[0], tab)
    setup_sheet(ws, with_sample="--sample" in sys.argv)
    print(f"Sheet '{tab}' is set up with columns: {', '.join(c for c, _ in COLUMNS)}")