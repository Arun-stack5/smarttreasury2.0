"""Diagnose Google Sheet access. Run:  python check_connection.py "<sheet URL>" """
import json, os, re, sys
import gspread

url = sys.argv[1] if len(sys.argv) > 1 else ""
key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
print("Working folder :", os.getcwd())
print("Key file exists:", os.path.exists(key_file))
info = json.load(open(key_file))
print("Service account:", info["client_email"])
print("Project id     :", info.get("project_id"))
m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
print("Sheet ID in URL:", m.group(1) if m else "(none found - is this a full /d/... URL?)")

gc = gspread.service_account(filename=key_file)
print("\nSheets this service account can see:")
try:
    files = gc.list_spreadsheet_files()
    if not files: print("  (none)  -> nothing is shared with this email yet")
    for f in files: print(f"  - {f['name']}   id={f['id']}")
    ids = [f["id"] for f in files]
    if m: print("\nYour sheet is in the list:", m.group(1) in ids)
except Exception as e:
    print("  Drive listing failed:", e, "\n  -> enable the Google Drive API in the SAME project:", info.get("project_id"))