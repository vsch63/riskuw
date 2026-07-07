
#!/usr/bin/env python3
"""
debug_smtp.py
-------------
Diagnoses why the SMTP "not configured" warning persists.
Auto-logs in to get a fresh token — no manual token needed.

Usage:
    python3 debug_smtp.py --url http://localhost:8000 --user admin@example.com --password yourpassword
    python3 debug_smtp.py --url http://localhost:8000 --user admin@example.com   (prompts for password)
"""

import sys
import json
import argparse
import urllib.request
import urllib.error
import getpass

# ── HTTP helpers ──────────────────────────────────────────────────────────────
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
        except: return e.code, {"raw": raw}
    except Exception as ex:
        return 0, {"error": str(ex)}

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# ── Step 1: Login & get token ─────────────────────────────────────────────────
def get_token(base, username, password):
    section("0. LOGIN — getting fresh token")

    endpoints = [
        ("/auth/login",     {"username": username, "password": password}),
        ("/auth/login",     {"email":    username, "password": password}),
        ("/api/auth/login", {"username": username, "password": password}),
        ("/api/auth/login", {"email":    username, "password": password}),
        ("/api/login",      {"username": username, "password": password}),
        ("/api/login",      {"email":    username, "password": password}),
        ("/login",          {"username": username, "password": password}),
        ("/login",          {"email":    username, "password": password}),
        ("/token",          {"username": username, "password": password}),
    ]

    for path, payload in endpoints:
        url = f"{base}{path}"
        print(f"  Trying {url} ...", end=" ", flush=True)
        status, data = req("POST", url, body=payload)
        print(f"HTTP {status}")

        if status in (200, 201) and isinstance(data, dict):
            token = (
                data.get("access_token") or
                data.get("token") or
                data.get("jwt") or
                (data.get("data") or {}).get("access_token") or
                (data.get("data") or {}).get("token")
            )
            if token:
                print(f"\n  ✅ Logged in via {path}")
                print(f"  Token preview: {token[:40]}...")
                return token
            else:
                print(f"  ⚠️  HTTP 200 but no token field. Keys: {list(data.keys())}")

    print("\n  ❌ Could not log in — try --login-path to specify your login endpoint")
    return None

# ── Step 2: SMTP diagnostics ──────────────────────────────────────────────────
def diagnose_smtp(base, token):

    # GET /system/smtp
    section("1. GET /system/smtp — raw backend response")
    status, data = req("GET", f"{base}/system/smtp", token)
    print(f"  HTTP Status : {status}")
    print(f"  Response    :\n{json.dumps(data, indent=6)}")

    get_keys      = list(data.keys()) if isinstance(data, dict) else []
    has_smtp_host = isinstance(data, dict) and bool(data.get("smtp_host"))
    has_host      = isinstance(data, dict) and bool(data.get("host"))

    print(f"\n  Keys returned: {get_keys}")
    if   has_smtp_host: print(f"  ✅ 'smtp_host' = '{data['smtp_host']}'")
    elif has_host:      print(f"  ⚠️  'host' = '{data['host']}' (not 'smtp_host')")
    elif status == 200: print(f"  ⚠️  All values are empty — SMTP never saved to DB")
    else:               print(f"  ❌ Non-200 — route missing or crashing")

    # POST with smtp_host keys
    section("2. POST /system/smtp — which key format does backend accept?")
    payload_smtp = {
        "smtp_host": "smtp.gmail.com", "smtp_port": 587,
        "smtp_user": "test@test.com",  "smtp_password": "test",
        "smtp_from": "test@test.com",  "smtp_from_name": "Test",
        "smtp_use_tls": True,
    }
    payload_short = {
        "host": "smtp.gmail.com", "port": 587,
        "username": "test@test.com", "password": "test",
        "from_email": "test@test.com", "from_name": "Test",
        "use_tls": True,
    }

    print("\n  → Trying smtp_host / smtp_port / smtp_from (frontend form keys)...")
    s1, d1 = req("POST", f"{base}/system/smtp", token, payload_smtp)
    print(f"    HTTP {s1}  →  {json.dumps(d1)}")
    backend_uses_smtp = s1 in (200, 201)

    backend_uses_short = False
    if not backend_uses_smtp:
        print("\n  → Trying host / port / from_email (short keys)...")
        s2, d2 = req("POST", f"{base}/system/smtp", token, payload_short)
        print(f"    HTTP {s2}  →  {json.dumps(d2)}")
        backend_uses_short = s2 in (200, 201)

    # GET again
    section("3. GET /system/smtp after POST — did it persist?")
    status3, data3 = req("GET", f"{base}/system/smtp", token)
    print(f"  HTTP Status : {status3}")
    print(f"  Response    :\n{json.dumps(data3, indent=6)}")
    persisted      = isinstance(data3, dict) and any(data3.values())
    get_keys_after = list(data3.keys()) if isinstance(data3, dict) else []

    # SUMMARY
    section("DIAGNOSIS & RECOMMENDED FIX")

    if has_smtp_host and backend_uses_smtp:
        print("""
  ✅ Backend and frontend both use smtp_host keys correctly.
     If banner still shows → hard-refresh browser (Ctrl+Shift+R)
     or clear localStorage and log in again.
""")

    elif has_host or backend_uses_short:
        print("""
  ROOT CAUSE FOUND:
  Backend uses SHORT keys:  host / port / from_email / username
  Frontend form uses LONG:  smtp_host / smtp_port / smtp_from / smtp_user

  The original frontend code used r?.host which matched the backend.
  The SMTP fix changed it to r?.smtp_host — which broke the match.

  ──────────────────────────────────────────────────────────────
  FIX: Run this to revert only the SMTP key check in frontend:
  ──────────────────────────────────────────────────────────────

    python3 fix_smtp_keys.py frontend/src/pages/SystemConfigPage.tsx

  (Script generated below — copy and save it as fix_smtp_keys.py)
""")
        # Print the fix script inline so user has it immediately
        print("=" * 60)
        print("  fix_smtp_keys.py — save this as a file and run it")
        print("=" * 60)
        print(r'''
import sys, re

path = sys.argv[1]
with open(path, "r") as f:
    c = f.read()

fixes = [
    ("if (r?.smtp_host) setStatus(r)",           "if (r?.host) setStatus(r)"),
    ("{smtpStatus?.smtp_host ? (",                "{smtpStatus?.host ? ("),
    ("<strong>{smtpStatus.smtp_host}</strong> port {smtpStatus.smtp_port} from <strong>{smtpStatus.smtp_from}</strong>",
     "<strong>{smtpStatus.host}</strong> port {smtpStatus.port} from <strong>{smtpStatus.from_email}</strong>"),
]

for old, new in fixes:
    if old in c:
        c = c.replace(old, new)
        print(f"  FIXED: {old[:50]}...")
    else:
        print(f"  SKIP : {old[:50]}...")

with open(path, "w") as f:
    f.write(c)
print("Done. Rebuild with: docker build --no-cache -f Dockerfile.frontend .")
''')

    elif not persisted:
        print("""
  ROOT CAUSE: SMTP settings not persisting to database.
  POST returns 200 but data is gone on next GET.
  Check your Flask /system/smtp POST route — it may not be
  committing to DB (missing db.session.commit() ?).
""")

    else:
        print(f"""
  Unclear — share this full output for further diagnosis.
  GET keys before: {get_keys}
  GET keys after : {get_keys_after}
""")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="RiskUW SMTP Debugger — auto-login version")
    parser.add_argument("--url",        default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--user",       required=True,  help="Login email or username")
    parser.add_argument("--password",   default=None,   help="Password (prompted if not given)")
    parser.add_argument("--login-path", default=None,   help="Override login path e.g. /auth/login")
    args = parser.parse_args()

    base     = args.url.rstrip("/")
    password = args.password or getpass.getpass(f"Password for {args.user}: ")

    print(f"\n RiskUW SMTP Debugger")
    print(f"  Target : {base}")
    print(f"  User   : {args.user}")

    if args.login_path:
        url = f"{base}{args.login_path}"
        print(f"\n  Trying {url} ...")
        _, data = req("POST", url, body={"email": args.user, "password": password})
        if not data.get("access_token"):
            _, data = req("POST", url, body={"username": args.user, "password": password})
        token = data.get("access_token") or data.get("token")
    else:
        token = get_token(base, args.user, password)

    if not token:
        print("\n  Cannot proceed without token. Exiting.")
        sys.exit(1)

    diagnose_smtp(base, token)

if __name__ == "__main__":
    main()

