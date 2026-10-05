"""Google side of SmartTreasury (local OR hosted):
   1) the sheet columns + sample rows
   2) writing headers / formats into a sheet, reading it back
   3) per-user Google sign-in; the demo sheet is created in the USER'S OWN Drive."""
import json, os, pathlib
import pandas as pd

BASE = pathlib.Path(__file__).resolve().parent            # the folder this file lives in
REDIRECT = os.getenv("OAUTH_REDIRECT", "http://localhost:8501/")
STORE = BASE / ".user_data"                                 # saved sign-ins (this computer only)
TAB, LAST_ROW = "Data", 2000
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/drive.file"]
if REDIRECT.startswith("http://localhost"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")   # plain http is fine on localhost
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# ======================================================================= 1) columns + sample rows
# Receivable = POSITIVE amount, Payable = NEGATIVE amount
COLUMNS = [
    ("Ref",         "Unique id, e.g. INV-001 / PAY-001"),
    ("Party",       "Customer (receivable) or vendor (payable)"),
    ("Amount",      "Rupees. RECEIVABLE = positive, PAYABLE = negative"),
    ("Date",        "Receivable: expected date. Payable: due date"),
    ("Actual Date", "Receivables only: date money was received (blank until received)"),
    ("Probability", "Receivables only: 0 to 1 (0.85 = 85%)"),
    ("Priority",    "Payables only: 1 = High, 2 = Medium, 3 = Low"),
    ("Type",        "Auto-filled: Receivable / Payable (do not edit)"),
]
INPUT_COLS = [c for c, _ in COLUMNS[:7]]
CR = 10_000_000
SAMPLE_ROWS = [  # Ref, Party, Amount, Date, Actual Date, Probability, Priority
    ["INV-001", "Alpha Traders",     2 * CR,    "2026-01-20", "2026-01-20", 0.90, ""],
    ["INV-002", "Sigma Retail",      4 * CR,    "2026-02-02", "2026-02-02", 0.85, ""],
    ["INV-003", "Delta Infra",       8 * CR,    "2026-02-10", "2026-02-10", 0.95, ""],
    ["INV-004", "Omega Industries",  3.5 * CR,  "2026-03-01", "2026-03-01", 0.90, ""],
    ["INV-005", "Beta Systems",      5 * CR,    "2026-03-14", "",           0.80, ""],
    ["INV-006", "Gamma Exports",     9 * CR,    "2026-04-04", "",           0.70, ""],
    ["PAY-001", "Salaries",         -1.5 * CR,  "2026-01-31", "", "", 1],
    ["PAY-002", "Office & Rent",    -2.5 * CR,  "2026-02-27", "", "", 2],
    ["PAY-003", "GST / Tax",        -3 * CR,    "2026-02-13", "", "", 1],
    ["PAY-004", "Raw Materials",    -6 * CR,    "2026-03-10", "", "", 2],
    ["PAY-005", "Capex Vendor",     -4 * CR,    "2026-04-15", "", "", 3],
]


# ======================================================================= 2) sheet setup / read
def setup_sheet(ws, with_sample=False):
    """Write headers (+ sample rows). Then nice-to-have formatting; a formatting problem never blocks the sheet."""
    ws.update(values=[[c for c, _ in COLUMNS]], range_name="A1", value_input_option="USER_ENTERED")
    ws.update(values=[['=ARRAYFORMULA(IF(C2:C="","",IF(C2:C>0,"Receivable","Payable")))']],
              range_name="H2", value_input_option="USER_ENTERED")
    if with_sample:
        ws.update(values=SAMPLE_ROWS, range_name="A2", value_input_option="USER_ENTERED")
    try:
        _format_sheet(ws)
    except Exception as e:                       # cosmetic only
        return f"Sheet works, but formatting was skipped ({type(e).__name__})"
    return ""


def _format_sheet(ws):
    sid = ws.id

    def rng(c0, c1=None, r0=1, r1=LAST_ROW):
        return dict(sheetId=sid, startRowIndex=r0, endRowIndex=r1, startColumnIndex=c0, endColumnIndex=c1 or c0 + 1)

    def fmt(c0, kind, pattern):
        return {"repeatCell": {"range": rng(c0), "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                               "fields": "userEnteredFormat.numberFormat"}}

    def colour(cond, rgb):
        return {"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [rng(2)], "booleanRule": {
            "condition": cond, "format": {"textFormat": {"foregroundColor": rgb}}}}}}

    def valid(c0, cond, msg):
        return {"setDataValidation": {"range": rng(c0), "rule": {"condition": cond, "strict": True, "inputMessage": msg, "showCustomUi": True}}}

    ws.spreadsheet.batch_update({"requests": [
        {"repeatCell": {"range": rng(0, len(COLUMNS), 0, 1), "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": .1, "green": .2, "blue": .35}, "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        fmt(2, "NUMBER", "#,##0;-#,##0"), fmt(3, "DATE", "dd-mmm-yyyy"), fmt(4, "DATE", "dd-mmm-yyyy"), fmt(5, "PERCENT", "0%"),
        colour({"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]}, {"red": .05, "green": .5, "blue": .2}),
        colour({"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]}, {"red": .8, "green": .1, "blue": .1}),
        valid(3, {"type": "DATE_IS_VALID"}, "Expected date (receivable) or due date (payable)"),
        valid(4, {"type": "DATE_IS_VALID"}, "Only when money is actually received"),
        valid(5, {"type": "NUMBER_BETWEEN", "values": [{"userEnteredValue": "0"}, {"userEnteredValue": "1"}]}, "0 to 1, e.g. 0.85"),
        valid(6, {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in "123"]}, "1 High, 2 Medium, 3 Low"),
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 8},
                                       "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
    ]})


def load_sheet(ws) -> pd.DataFrame:
    return pd.DataFrame(ws.get_all_records(value_render_option="UNFORMATTED_VALUE", expected_headers=[]))


def _to_date(v):
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)): return None
    if isinstance(v, (int, float)): return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).date()   # Sheets serial
    t = pd.to_datetime(v, errors="coerce", dayfirst=not str(v)[:4].isdigit())
    return None if pd.isna(t) else t.date()


def _num(v):
    if isinstance(v, (int, float)): return v
    try: return float(str(v).replace(",", "").replace("₹", "").strip())
    except ValueError: return None


def split_book(raw: pd.DataFrame):
    """Sheet rows -> (receivables, payables, warnings).  +ve Amount = receivable, -ve Amount = payable."""
    warns, recs, pays = [], [], []
    raw = raw.rename(columns={c: str(c).strip() for c in raw.columns})
    missing = [c for c in INPUT_COLS if c not in raw.columns]
    if missing:
        return pd.DataFrame(), pd.DataFrame(), [f"Missing columns: {', '.join(missing)}. Use 'Repair columns' in the sidebar."]
    for i, r in raw.iterrows():
        row = i + 2
        amt = _num(r["Amount"])
        if amt is None or amt == 0:
            if str(r["Ref"]).strip(): warns.append(f"Row {row} ({r['Ref']}): empty/zero/invalid Amount, skipped")
            continue
        dt = _to_date(r["Date"])
        if dt is None:
            warns.append(f"Row {row} ({r['Ref']}): missing Date, skipped"); continue
        base = dict(ref=str(r["Ref"]).strip() or f"ROW-{row}", party=str(r["Party"]).strip())
        if amt > 0:
            p = _num(r["Probability"])
            if p is None: warns.append(f"Row {row} ({base['ref']}): no Probability, treated as 0"); p = 0.0
            if p > 1: p = p / 100
            recs.append({**base, "amount": amt, "expected_date": dt, "actual_date": _to_date(r["Actual Date"]), "probability": p})
        else:
            pr = _num(r["Priority"])
            pays.append({**base, "amount": -amt, "due_date": dt, "priority": int(pr) if pr in (1, 2, 3) else 2})
    return (pd.DataFrame(recs, columns=["ref", "party", "amount", "expected_date", "actual_date", "probability"]),
            pd.DataFrame(pays, columns=["ref", "party", "amount", "due_date", "priority"]), warns)


# ======================================================================= 3) Google sign-in (per user)
# LOCAL : OAuth client JSON file next to app.py, sign-ins remembered in .user_data (this computer only).
# HOSTED: OAuth client id/secret come from the host's Secrets; tokens live ONLY in the visitor's session.
_HOSTED = {"client": None, "redirect": None}


def configure_hosted(client_id: str, client_secret: str, redirect_uri: str):
    _HOSTED["client"] = {"web": {"client_id": client_id.strip(), "client_secret": client_secret.strip(),
                                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                 "token_uri": "https://oauth2.googleapis.com/token",
                                 "redirect_uris": [redirect_uri.strip()]}}
    _HOSTED["redirect"] = redirect_uri.strip()


def is_hosted() -> bool: return _HOSTED["client"] is not None
def redirect_uri() -> str: return _HOSTED["redirect"] or REDIRECT


def scan_json_files():
    """Every .json file next to this code, with what kind it is (local mode)."""
    out = []
    for p in sorted(BASE.glob("*.json")):
        try: d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception: out.append((p.name, "not valid JSON")); continue
        kind = ("oauth-web" if "web" in d else "oauth-desktop" if "installed" in d
                else "service-account" if d.get("type") == "service_account" else "unknown")
        out.append((p.name, kind))
    return out


def find_client_file():
    good = [n for n, k in scan_json_files() if k in ("oauth-web", "oauth-desktop")]
    if "oauth_client.json" in good: return BASE / "oauth_client.json"
    return BASE / good[0] if good else None


def _client_config() -> dict:
    if is_hosted(): return _HOSTED["client"]
    f = find_client_file()
    if f is None: raise FileNotFoundError("oauth_client.json not found next to app.py")
    return json.loads(f.read_text(encoding="utf-8-sig"))


def oauth_status() -> dict:
    """Plain-language checklist shown on the sign-in screen."""
    if is_hosted():
        body = _HOSTED["client"]["web"]
        lines = ["✅ Hosted mode: Google settings read from the host's Secrets",
                 "✅ client_id looks right" if body["client_id"].endswith(".apps.googleusercontent.com")
                 else "❌ client_id in Secrets does not look like a Google client id",
                 f"➡ This exact address must be listed under 'Authorized redirect URIs' in Google Cloud: {redirect_uri()}"]
        return dict(ok=bool(body["client_id"]) and bool(body["client_secret"]), lines=lines, files=[])
    lines, files = [f"📁 Folder: {BASE}"], scan_json_files()
    f = find_client_file()
    if f is None:
        lines.append("❌ No OAuth client file found in this folder.")
        for n, k in files:
            if k == "service-account":
                lines.append(f"❌ '{n}' is a SERVICE ACCOUNT key. That is the wrong file for this app.")
        lines.append("➡ Google Cloud → APIs & Services → Credentials → open your OAuth client (type: Web application) → "
                     "Download JSON → save it in this folder as  oauth_client.json")
        return dict(ok=False, lines=lines, files=files)
    d = json.loads(f.read_text(encoding="utf-8-sig"))
    body = d.get("web") or d.get("installed") or {}
    lines.append(f"✅ Using OAuth client file: {f.name}  ({'web' if 'web' in d else 'desktop'} type)")
    lines.append("✅ client_id looks right" if str(body.get("client_id", "")).endswith(".apps.googleusercontent.com")
                 else "❌ client_id inside the file does not look like a Google client id")
    if "web" in d:
        uris = body.get("redirect_uris", [])
        lines.append(f"✅ Redirect address {redirect_uri()} is registered" if redirect_uri() in uris
                     else f"⚠ The file does not list {redirect_uri()}. Add it under 'Authorized redirect URIs' in Google Cloud, then download the JSON again.")
    ok = bool(body.get("client_id")) and bool(body.get("client_secret"))
    if not ok: lines.append("❌ client_id / client_secret missing in the file")
    return dict(ok=ok, lines=lines, files=files)


def _flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri(),
                                   autogenerate_code_verifier=False)


def login_url() -> str:
    url, _ = _flow().authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    return url


# ---- remembered sign-ins: LOCAL ONLY (a public server must never keep other people's tokens)
def _file(email): return STORE / (email.lower().replace("/", "_") + ".json")
def _read(email):
    try: return json.loads(_file(email).read_text())
    except Exception: return {}
def _write(email, data):
    STORE.mkdir(exist_ok=True); _file(email).write_text(json.dumps(data))
def known_users():
    if is_hosted() or not STORE.exists(): return []
    return sorted(p.stem for p in STORE.glob("*.json"))
def forget(email):
    try: _file(email).unlink()
    except Exception: pass


def finish_login(code: str):
    """Trade the ?code= Google sent back for tokens. Returns (email, token_dict)."""
    import requests
    f = _flow(); f.fetch_token(code=code)
    c = f.credentials
    r = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {c.token}"}, timeout=15)
    r.raise_for_status()
    email, tok = r.json()["email"].lower(), json.loads(c.to_json())
    if not is_hosted():
        data = _read(email); data["creds"] = tok; _write(email, data)
    return email, tok


def _creds(email, tok=None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if tok is None:
        tok = _read(email).get("creds")
        if not tok: raise PermissionError("Not signed in yet.")
    c = Credentials.from_authorized_user_info(tok, SCOPES)
    if not c.valid:
        c.refresh(Request())
        if not is_hosted():
            data = _read(email); data["creds"] = json.loads(c.to_json()); _write(email, data)
    return c


SHEET_NAME = "SmartTreasury - Data"


def _find_sheet(gc, name=SHEET_NAME):
    """Newest non-trashed spreadsheet with this name that THIS user's grant can see (the app's own files)."""
    q = f'mimeType="application/vnd.google-apps.spreadsheet" and name="{name}" and trashed=false'
    r = gc.http_client.request("get", "https://www.googleapis.com/drive/v3/files",
                               params={"q": q, "orderBy": "modifiedTime desc", "pageSize": 1, "fields": "files(id,name)"})
    files = r.json().get("files", [])
    return files[0]["id"] if files else None


def user_sheet(email: str, tok=None):
    """Open this user's sheet from THEIR Drive, or create the demo sheet there. -> (worksheet, created, url, note)"""
    import gspread
    gc = gspread.authorize(_creds(email, tok))
    sid = None if is_hosted() else _read(email).get("sheet_id")
    for candidate in (sid, None):
        try:
            sid2 = candidate or _find_sheet(gc)
            if sid2:
                book = gc.open_by_key(sid2)
                if not is_hosted(): d = _read(email); d["sheet_id"] = book.id; _write(email, d)
                return book.worksheet(TAB), False, book.url, ""
        except Exception:
            continue
    book = gc.create(SHEET_NAME)
    ws = book.sheet1; ws.update_title(TAB)
    note = setup_sheet(ws, with_sample=True)
    if not is_hosted(): d = _read(email); d["sheet_id"] = book.id; _write(email, d)
    return ws, True, book.url, note