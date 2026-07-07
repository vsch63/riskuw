#!/usr/bin/env python3
"""
debug_smtp.py
-------------
RiskUW SMTP Debugger — auto-login using /auth/login
Diagnoses why the SMTP banner stays yellow after saving.

Usage:
    python3 debug_smtp.py --user admin --password yourpassword
    python3 debug_smtp.py --user admin --password yourpassword --url http://localhost:8000
"""

import sys, json, argparse, urllib.request, urllib.error, getpass

def req(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as res:
            raw = res.read().decode()
            return res.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:    return e.code, json.loads(raw)
        except: return e.code, {"raw": raw[:300]}
    except Exception as ex:
        return 0, {"error": str(ex)}

def sep(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",      default="http://localhost:8000")
    parser.add_argument("--user",     required=True)
    parser.add_argument("--password", default=None)
    args     = parser.parse_args()
    base     = args.url.rstrip("/")
    password = args.password or getpass.getpass(f"Password for {args.user}: ")

    print(f"\n  RiskUW SMTP Debugger")
    print(f"  Target : {base}")
    print(f"  User   : {args.user}")

    # ── STEP 1: Login ─────────────────────────────────────────────
    sep("1. LOGIN  →  POST /auth/login")
    status, data = req("POST", f"{base}/auth/login",
                       body={"username": args.user, "password": password})
    print(f"  HTTP   : {status}")
    print(f"  Body   : {json.dumps(data, indent=4)}")

    token = data.get("access_token")
    if not token:
        print(f"\n  ❌ Login failed — HTTP {status}")
        if status == 401:
            print("     Wrong username or password.")
        elif status == 429:
            print("     Account locked (too many failed attempts).")
        elif status == 0:
            print("     Backend not reachable. Is it running on", base, "?")
        else:
            print("     Check backend logs.")
        sys.exit(1)

    print(f"\n  ✅ Token obtained: {token[:50]}...")

    # ── STEP 2: GET /system/smtp ───────────────────────────────────
    sep("2. GET /system/smtp  —  raw backend response")
    s, d = req("GET", f"{base}/system/smtp", token)
    print(f"  HTTP   : {s}")
    print(f"  Body   : {json.dumps(d, indent=4)}")

    get_keys      = list(d.keys()) if isinstance(d, dict) else []
    has_smtp_host = bool(d.get("smtp_host"))
    has_host      = bool(d.get("host"))
    print(f"\n  Keys   : {get_keys}")

    if   has_smtp_host: print(f"  ✅ 'smtp_host' = '{d['smtp_host']}'")
    elif has_host:      print(f"  ⚠️  'host'      = '{d['host']}'  (backend uses short key)")
    elif s == 200:      print(f"  ⚠️  All values empty — SMTP never saved to DB")
    else:               print(f"  ❌ Non-200 — route missing or crashing")

    # ── STEP 3: POST /system/smtp ──────────────────────────────────
    sep("3. POST /system/smtp  —  which key format does backend accept?")
    payload_long  = {"smtp_host":"smtp.gmail.com","smtp_port":587,
                     "smtp_user":"t@t.com","smtp_password":"test",
                     "smtp_from":"t@t.com","smtp_from_name":"Test","smtp_use_tls":True}
    payload_short = {"host":"smtp.gmail.com","port":587,
                     "username":"t@t.com","password":"test",
                     "from_email":"t@t.com","from_name":"Test","use_tls":True}

    print("  → Trying smtp_host / smtp_port / smtp_from  (frontend form field names)...")
    s1, d1 = req("POST", f"{base}/system/smtp", token, payload_long)
    print(f"    HTTP {s1}  →  {json.dumps(d1)}")
    accepts_long = s1 in (200, 201)

    accepts_short = False
    if not accepts_long:
        print("  → Trying host / port / from_email  (short keys)...")
        s2, d2 = req("POST", f"{base}/system/smtp", token, payload_short)
        print(f"    HTTP {s2}  →  {json.dumps(d2)}")
        accepts_short = s2 in (200, 201)

    # ── STEP 4: GET again ──────────────────────────────────────────
    sep("4. GET /system/smtp  —  after POST, did it persist?")
    s3, d3 = req("GET", f"{base}/system/smtp", token)
    print(f"  HTTP   : {s3}")
    print(f"  Body   : {json.dumps(d3, indent=4)}")
    persisted      = isinstance(d3, dict) and any(d3.values())
    get_keys_after = list(d3.keys()) if isinstance(d3, dict) else []

    # ── DIAGNOSIS ──────────────────────────────────────────────────
    sep("DIAGNOSIS  &  FIX")

    if has_smtp_host and accepts_long:
        print("""
  ✅ Backend and frontend both use smtp_host keys.
     Everything is aligned. If the banner still shows:
       → Hard-refresh browser:  Ctrl + Shift + R
       → Or open DevTools → Application → Clear site data
""")

    elif has_host or accepts_short:
        print("""
  ROOT CAUSE FOUND:
  ─────────────────
  Backend uses SHORT keys:  host / port / username / from_email
  Frontend form uses LONG:  smtp_host / smtp_port / smtp_user / smtp_from

  The original frontend used r?.host  →  matched backend  ✅
  The recent SMTP fix changed to r?.smtp_host  →  broke the match ❌

  FIX — run this one-liner on your server:
  ─────────────────────────────────────────""")
        print("""
  python3 fix_smtp_keys.py frontend/src/pages/SystemConfigPage.tsx
""")
        # Write the fix script right here
        fix_script = '''\
#!/usr/bin/env python3
"""
fix_smtp_keys.py
Reverts the SMTP key check in SystemConfigPage.tsx to match the
backend which returns short keys: host / port / from_email
"""
import sys, os

if len(sys.argv) < 2:
    print("Usage: python3 fix_smtp_keys.py <path/to/SystemConfigPage.tsx>")
    sys.exit(1)

path = sys.argv[1]
if not os.path.isfile(path):
    print(f"File not found: {path}"); sys.exit(1)

with open(path) as f:
    c = f.read()

# Backup
with open(path + ".bak2", "w") as f:
    f.write(c)
print(f"Backup: {path}.bak2")

fixes = [
    # Revert useEffect + save() key check
    ("if (r?.smtp_host) setStatus(r)",
     "if (r?.host) setStatus(r)"),

    # Revert banner visibility check
    ("{smtpStatus?.smtp_host ? (",
     "{smtpStatus?.host ? ("),

    # Revert banner display values
    ("<strong>{smtpStatus.smtp_host}</strong> port {smtpStatus.smtp_port} from <strong>{smtpStatus.smtp_from}</strong>",
     "<strong>{smtpStatus.host}</strong> port {smtpStatus.port} from <strong>{smtpStatus.from_email}</strong>"),
]

changed = 0
for old, new in fixes:
    n = c.count(old)
    if n:
        c = c.replace(old, new)
        print(f"  FIXED ({n}x): {old[:60]}")
        changed += n
    else:
        # check if already reverted
        if new in c:
            print(f"  SKIP  (already correct): {new[:60]}")
        else:
            print(f"  MISS  (not found): {old[:60]}")

with open(path, "w") as f:
    f.write(c)

print(f"\\n{'✅ Done' if changed else '⚠️  Nothing changed'} — {changed} replacement(s) made.")
print("Rebuild: docker build --no-cache -f Dockerfile.frontend .")
'''
        fix_path = "fix_smtp_keys.py"
        with open(fix_path, "w") as f:
            f.write(fix_script)
        print(f"  ✅ fix_smtp_keys.py written to current directory.")
        print(f"  Run:  python3 fix_smtp_keys.py frontend/src/pages/SystemConfigPage.tsx")

    elif not persisted:
        print("""
  ROOT CAUSE: SMTP settings are NOT being saved to the database.
  POST /system/smtp returns 200 but data is gone on next GET.

  Check your Flask/FastAPI route for /system/smtp POST:
    → Is db.session.commit() / conn.commit() being called?
    → Is it writing to the right table?
    → Check backend logs for silent exceptions.
""")
    else:
        print(f"""
  Unclear — share this full output for further diagnosis.
  GET keys before POST : {get_keys}
  GET keys after  POST : {get_keys_after}
""")

if __name__ == "__main__":
    main()

