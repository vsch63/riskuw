#!/usr/bin/env python3
"""
debug_smtp_v3.py
----------------
RiskUW SMTP Debugger — hardcoded for your setup:
  Backend : http://localhost:8001  (127.0.0.1:8001->8000/tcp)
  Login   : POST /auth/login  {"username": ..., "password": ...}

Usage:
    python3 debug_smtp_v3.py --user admin --password yourpassword
"""

import sys, json, argparse, urllib.request, urllib.error, getpass

BASE = "http://localhost:8001"   # ← your actual backend port

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

def write_fix_script(mode):
    """Write the appropriate fix script based on diagnosis."""

    if mode == "revert":
        # Backend returns short keys (host/port/from_email) — revert frontend
        script = '''\
#!/usr/bin/env python3
"""
fix_smtp_keys.py — Reverts frontend SMTP key check to match backend.
Backend returns: host / port / from_email  (short keys)
Run: python3 fix_smtp_keys.py /opt/riskuw/frontend/src/pages/SystemConfigPage.tsx
"""
import sys, os

path = sys.argv[1] if len(sys.argv) > 1 else "frontend/src/pages/SystemConfigPage.tsx"
if not os.path.isfile(path):
    print(f"File not found: {path}"); sys.exit(1)

with open(path) as f:
    c = f.read()

with open(path + ".bak_smtpfix", "w") as f:
    f.write(c)
print(f"Backup: {path}.bak_smtpfix")

fixes = [
    ("if (r?.smtp_host) setStatus(r)",
     "if (r?.host) setStatus(r)"),
    ("{smtpStatus?.smtp_host ? (",
     "{smtpStatus?.host ? ("),
    ("<strong>{smtpStatus.smtp_host}</strong> port {smtpStatus.smtp_port} from <strong>{smtpStatus.smtp_from}</strong>",
     "<strong>{smtpStatus.host}</strong> port {smtpStatus.port} from <strong>{smtpStatus.from_email}</strong>"),
]

changed = 0
for old, new in fixes:
    n = c.count(old)
    if n:
        c = c.replace(old, new); changed += n
        print(f"  FIXED ({n}x): {old[:65]}")
    elif new in c:
        print(f"  SKIP  (already correct): {new[:65]}")
    else:
        print(f"  MISS  (not found - may already be fixed): {old[:65]}")

with open(path, "w") as f:
    f.write(c)
print(f"\\n{'Done — ' + str(changed) + ' fix(es) applied.' if changed else 'Nothing changed (already correct).'}")
print("Now rebuild: docker build --no-cache -f Dockerfile.frontend . && docker compose up -d frontend")
'''
        fname = "fix_smtp_keys.py"

    elif mode == "align":
        # Backend returns smtp_host — frontend fix was correct, something else is wrong
        script = '''\
#!/usr/bin/env python3
"""
fix_smtp_verify.py
Confirms frontend has the correct smtp_host keys (backend matches).
If banner still shows after this — it is a browser cache issue.
Run: python3 fix_smtp_verify.py /opt/riskuw/frontend/src/pages/SystemConfigPage.tsx
"""
import sys, os

path = sys.argv[1] if len(sys.argv) > 1 else "frontend/src/pages/SystemConfigPage.tsx"
with open(path) as f:
    c = f.read()

checks = [
    ("if (r?.smtp_host) setStatus(r)",          "useEffect key check"),
    ("{smtpStatus?.smtp_host ? (",               "banner visibility check"),
    ("{smtpStatus.smtp_host}",                   "banner display - host"),
]
print("Verifying frontend SMTP keys...")
for pattern, label in checks:
    found = pattern in c
    print(f"  {'✅' if found else '❌'} {label}: {'present' if found else 'MISSING'}")

print("\\nIf all ✅ and banner still shows:")
print("  1. Hard-refresh browser: Ctrl+Shift+R")
print("  2. Or clear localStorage in DevTools → Application → Clear site data")
print("  3. Or open in incognito window")
'''
        fname = "fix_smtp_verify.py"

    elif mode == "db":
        script = '''\
#!/usr/bin/env python3
"""
fix_smtp_db.py — Checks if SMTP config is actually in the database.
Run ON the server: python3 fix_smtp_db.py
"""
import os, sys

# Read DB URL from env
db_url = os.environ.get("DATABASE_URL", "")
if not db_url:
    # Try reading from .env
    for env_file in ["/opt/riskuw/.env", "/opt/riskuw/backend/.env", ".env"]:
        if os.path.isfile(env_file):
            for line in open(env_file):
                if line.startswith("DATABASE_URL"):
                    db_url = line.split("=", 1)[1].strip()
                    break
        if db_url:
            break

print(f"DB URL: {db_url[:40]}..." if db_url else "No DATABASE_URL found")

try:
    import psycopg2
    conn = psycopg2.connect(db_url)
    cur  = conn.cursor()

    # Check system_config table for SMTP keys
    print("\\n--- Checking system_config table ---")
    cur.execute("""
        SELECT config_key, config_value
        FROM system_config
        WHERE config_key ILIKE '%smtp%' OR config_key ILIKE '%mail%'
        ORDER BY config_key
    """)
    rows = cur.fetchall()
    if rows:
        for k, v in rows:
            display = v if "password" not in k.lower() else "***hidden***"
            print(f"  {k} = {display}")
    else:
        print("  ❌ No SMTP keys found in system_config table")
        print("     SMTP settings were never saved to DB")
        print("     → Save them again from the UI and check backend logs")

    # Check if there is a separate smtp_config table
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name ILIKE '%smtp%'
    """)
    smtp_tables = [r[0] for r in cur.fetchall()]
    if smtp_tables:
        print(f"\\n--- Found SMTP-specific tables: {smtp_tables} ---")
        for t in smtp_tables:
            cur.execute(f"SELECT * FROM {t} LIMIT 5")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            print(f"  Columns: {cols}")
            for row in rows:
                print(f"  Row: {dict(zip(cols, row))}")

    cur.close()
    conn.close()

except ImportError:
    print("psycopg2 not installed. Run: pip install psycopg2-binary --break-system-packages")
except Exception as e:
    print(f"DB error: {e}")
'''
        fname = "fix_smtp_db.py"

    with open(fname, "w") as f:
        f.write(script)
    print(f"\n  ✅ {fname} written to current directory.")
    return fname


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user",     required=True)
    parser.add_argument("--password", default=None)
    parser.add_argument("--url",      default=BASE)
    args     = parser.parse_args()
    base     = args.url.rstrip("/")
    password = args.password or getpass.getpass(f"Password for {args.user}: ")

    print(f"\n  RiskUW SMTP Debugger v3")
    print(f"  Target : {base}")
    print(f"  User   : {args.user}")

    # ── LOGIN ─────────────────────────────────────────────────────
    sep("1. LOGIN  →  POST /auth/login")
    status, data = req("POST", f"{base}/auth/login",
                       body={"username": args.user, "password": password})
    print(f"  HTTP   : {status}")
    print(f"  Body   : {json.dumps(data, indent=4)}")

    token = data.get("access_token")
    mfa   = data.get("mfa_required", False)

    if mfa:
        print("\n  ℹ️  MFA is enabled on this account.")
        code = input("  Enter your TOTP code: ").strip()
        mfa_session = data.get("mfa_session_token", "")
        status2, data2 = req("POST", f"{base}/auth/verify-mfa",
                             body={"username": args.user,
                                   "session_token": mfa_session,
                                   "totp_code": code})
        print(f"  MFA HTTP : {status2}")
        print(f"  MFA Body : {json.dumps(data2, indent=4)}")
        token = data2.get("access_token")

    if not token:
        print(f"\n  ❌ Login failed — HTTP {status}")
        if status == 401:
            print("     Wrong password. Check the admin password.")
            print("     Reset it with:")
            print("       docker exec -it riskuw_fastapi python3 -c \"")
            print("         import bcrypt")
            print("         print(bcrypt.hashpw(b'NewPassword123', bcrypt.gensalt()).decode())\"")
            print("     Then update in DB:")
            print("       docker exec -it riskuw_postgres psql -U uw_user -d riskuw -c \\")
            print("         \"UPDATE uw_user SET hashed_password='<hash>' WHERE username='admin';\"")
        sys.exit(1)

    print(f"\n  ✅ Token: {token[:50]}...")

    # ── GET /system/smtp ──────────────────────────────────────────
    sep("2. GET /system/smtp  —  raw backend response")
    s, d = req("GET", f"{base}/system/smtp", token)
    print(f"  HTTP   : {s}")
    print(f"  Body   : {json.dumps(d, indent=4)}")

    get_keys      = list(d.keys()) if isinstance(d, dict) else []
    has_smtp_host = bool(d.get("smtp_host"))
    has_host      = bool(d.get("host"))
    all_empty     = isinstance(d, dict) and not any(d.values())
    print(f"\n  Keys   : {get_keys}")

    if   has_smtp_host: print(f"  ✅ 'smtp_host' = '{d['smtp_host']}'")
    elif has_host:      print(f"  ⚠️  'host'      = '{d['host']}'  ← backend uses short key")
    elif all_empty:     print(f"  ⚠️  All values empty — SMTP config never saved to DB")
    elif s != 200:      print(f"  ❌ HTTP {s} — route may be missing or crashing")

    # ── POST /system/smtp ─────────────────────────────────────────
    sep("3. POST /system/smtp  —  which key format does backend accept?")
    p_long  = {"smtp_host":"smtp.gmail.com","smtp_port":587,
                "smtp_user":"t@t.com","smtp_password":"test",
                "smtp_from":"t@t.com","smtp_from_name":"Test","smtp_use_tls":True}
    p_short = {"host":"smtp.gmail.com","port":587,
                "username":"t@t.com","password":"test",
                "from_email":"t@t.com","from_name":"Test","use_tls":True}

    print("  → smtp_host / smtp_port / smtp_from  (frontend form field names)...")
    s1, d1 = req("POST", f"{base}/system/smtp", token, p_long)
    print(f"    HTTP {s1}  →  {json.dumps(d1)}")
    accepts_long = s1 in (200, 201)

    accepts_short = False
    if not accepts_long:
        print("  → host / port / from_email  (short keys)...")
        s2, d2 = req("POST", f"{base}/system/smtp", token, p_short)
        print(f"    HTTP {s2}  →  {json.dumps(d2)}")
        accepts_short = s2 in (200, 201)

    # ── GET again ─────────────────────────────────────────────────
    sep("4. GET /system/smtp after POST  —  did it persist?")
    s3, d3 = req("GET", f"{base}/system/smtp", token)
    print(f"  HTTP   : {s3}")
    print(f"  Body   : {json.dumps(d3, indent=4)}")
    persisted  = isinstance(d3, dict) and any(d3.values())
    after_keys = list(d3.keys()) if isinstance(d3, dict) else []

    # ── DIAGNOSIS ─────────────────────────────────────────────────
    sep("DIAGNOSIS  &  FIX")

    if has_smtp_host and accepts_long:
        print("  ✅ Backend returns smtp_host and accepts smtp_host on POST.")
        print("     Frontend fix is CORRECT.")
        print("     If banner still shows → hard-refresh:  Ctrl+Shift+R")
        fname = write_fix_script("align")
        print(f"  Run: python3 {fname} frontend/src/pages/SystemConfigPage.tsx")

    elif has_host or accepts_short:
        print("""
  ROOT CAUSE:
  Backend returns / accepts SHORT keys:  host / port / from_email
  Frontend now checks for LONG key:      smtp_host  ← broken after recent fix

  FIX: revert frontend to use short keys to match backend.""")
        fname = write_fix_script("revert")
        print(f"""
  Run:
    python3 {fname} /opt/riskuw/frontend/src/pages/SystemConfigPage.tsx
    docker build --no-cache -f Dockerfile.frontend .
    docker compose up -d frontend
""")

    elif all_empty or not persisted:
        print("  ROOT CAUSE: SMTP settings not in database.")
        print("  POST may succeed but data is not being committed.")
        fname = write_fix_script("db")
        print(f"  Run: python3 {fname}")
        print("  Then check backend logs:")
        print("    docker logs riskuw_fastapi --tail=50")

    else:
        print(f"  Keys before POST : {get_keys}")
        print(f"  Keys after  POST : {after_keys}")
        print("  Share this output for further diagnosis.")

if __name__ == "__main__":
    main()
