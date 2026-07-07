
#!/usr/bin/env python3
"""
find_login.py
-------------
Scans your Flask backend to find the correct login endpoint.
Run this ON your server where the backend code lives.

Usage:
    python3 find_login.py --app-dir /opt/riskuw/backend
    python3 find_login.py --app-dir /opt/riskuw          (searches recursively)
"""

import os
import re
import sys
import json
import argparse
import urllib.request
import urllib.error
import getpass

# ── Try to find login route in source code ────────────────────────────────────
def find_routes_in_source(app_dir):
    print(f"\n  Scanning source files in: {app_dir}")
    candidates = []

    login_pattern   = re.compile(r'["\']([/\w-]*login[/\w-]*)["\']', re.IGNORECASE)
    token_pattern   = re.compile(r'["\']([/\w-]*token[/\w-]*)["\']', re.IGNORECASE)
    route_pattern   = re.compile(r'@.*route\(["\']([^"\']+)["\']', re.IGNORECASE)
    bearer_pattern  = re.compile(r'access_token|jwt_token|create_access_token', re.IGNORECASE)

    for root, dirs, files in os.walk(app_dir):
        # Skip node_modules, .git, __pycache__, venv
        dirs[:] = [d for d in dirs if d not in
                   {'node_modules', '.git', '__pycache__', 'venv', '.venv', 'env', 'dist', 'build'}]

        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except:
                continue

            # Find files that deal with JWT / access tokens
            if not bearer_pattern.search(content):
                continue

            routes = route_pattern.findall(content)
            logins = login_pattern.findall(content)
            tokens = token_pattern.findall(content)

            found = list(set(routes + logins + tokens))
            if found:
                rel = os.path.relpath(fpath, app_dir)
                print(f"    📄 {rel}")
                for r in sorted(found):
                    print(f"       → {r}")
                    candidates.append(r)

    return list(set(candidates))

# ── Probe each candidate endpoint ─────────────────────────────────────────────
def probe_endpoints(base, candidates, username, password):
    print(f"\n  Probing {len(candidates)} candidate endpoint(s)...")

    payloads = [
        {"username": username, "password": password},
        {"email":    username, "password": password},
        {"user":     username, "password": password},
        {"login":    username, "password": password},
    ]

    # Always include common patterns even if not found in source
    always_try = [
        "/auth/login", "/auth/token", "/api/auth/login",
        "/api/login",  "/login",      "/token",
        "/users/login","/user/login", "/api/token",
        "/auth/jwt/login", "/v1/auth/login",
    ]
    all_paths = list(dict.fromkeys(candidates + always_try))  # deduplicated, order preserved

    found_token = None
    found_path  = None

    for path in all_paths:
        url = f"{base}{path}"
        for payload in payloads:
            try:
                data_bytes = json.dumps(payload).encode()
                r = urllib.request.Request(
                    url, data=data_bytes,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(r, timeout=5) as res:
                    status = res.status
                    body   = json.loads(res.read().decode())
            except urllib.error.HTTPError as e:
                status = e.code
                try:    body = json.loads(e.read().decode())
                except: body = {}
            except:
                continue

            if status in (200, 201) and isinstance(body, dict):
                token = (
                    body.get("access_token") or
                    body.get("token")         or
                    body.get("jwt")           or
                    (body.get("data") or {}).get("access_token") or
                    (body.get("data") or {}).get("token")
                )
                if token:
                    print(f"\n  ✅ LOGIN SUCCESS")
                    print(f"     Endpoint : {url}")
                    print(f"     Payload  : {json.dumps(payload)}")
                    print(f"     Token    : {token[:50]}...")
                    found_token = token
                    found_path  = path
                    break
                else:
                    print(f"  ⚠  {path} → HTTP {status} but no token. Keys: {list(body.keys())}")
            elif status == 422:
                print(f"  ⚠  {path} → HTTP 422 validation error: {body}")
            elif status not in (404, 405, 0):
                print(f"  →  {path} → HTTP {status}")

        if found_token:
            break

    return found_token, found_path

# ── Quick SMTP check once we have a token ─────────────────────────────────────
def quick_smtp_check(base, token):
    print(f"\n{'='*60}")
    print(f"  SMTP ENDPOINT CHECK")
    print(f"{'='*60}")

    def req(method, url, body=None):
        data = json.dumps(body).encode() if body else None
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        }
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as res:
                raw = res.read().decode()
                return res.status, json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:    return e.code, json.loads(raw)
            except: return e.code, {"raw": raw[:200]}
        except Exception as ex:
            return 0, {"error": str(ex)}

    print("\n  GET /system/smtp")
    s, d = req("GET", f"{base}/system/smtp")
    print(f"  HTTP {s}  →  {json.dumps(d, indent=4)}")

    keys = list(d.keys()) if isinstance(d, dict) else []
    print(f"\n  Keys: {keys}")

    if d.get("smtp_host"):
        print("  ✅ Backend returns smtp_host  → frontend fix (smtp_host) is CORRECT")
    elif d.get("host"):
        print("  ⚠️  Backend returns 'host' not 'smtp_host'")
        print("     → Frontend fix needs to be REVERTED to use 'host'")
        print("""
  Run this on your server to revert the SMTP key check:

    python3 - << 'EOF'
import sys
path = "frontend/src/pages/SystemConfigPage.tsx"
with open(path) as f: c = f.read()
fixes = [
    ("if (r?.smtp_host) setStatus(r)",    "if (r?.host) setStatus(r)"),
    ("{smtpStatus?.smtp_host ? (",         "{smtpStatus?.host ? ("),
    ("{smtpStatus.smtp_host}",             "{smtpStatus.host}"),
    ("{smtpStatus.smtp_port}",             "{smtpStatus.port}"),
    ("{smtpStatus.smtp_from}",             "{smtpStatus.from_email}"),
]
for old, new in fixes:
    count = c.count(old)
    c = c.replace(old, new)
    print(f"{'FIXED' if count else 'SKIP ':5s} {old[:55]}")
with open(path, "w") as f: f.write(c)
print("Done — rebuild now.")
EOF
""")
    elif not any((d or {}).values()):
        print("  ⚠️  All values empty — SMTP was never saved to DB")
    else:
        print(f"  ❓ Unexpected — share this output")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Find login endpoint + diagnose SMTP")
    parser.add_argument("--url",      default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--user",     required=True,  help="Login username or email")
    parser.add_argument("--password", default=None,   help="Password (prompted if omitted)")
    parser.add_argument("--app-dir",  default=".",    help="Path to app source (for route scanning)")
    args = parser.parse_args()

    base     = args.url.rstrip("/")
    password = args.password or getpass.getpass(f"Password for {args.user}: ")

    print(f"\n  RiskUW Login Finder + SMTP Debugger")
    print(f"  Target  : {base}")
    print(f"  User    : {args.user}")
    print(f"  App dir : {args.app_dir}")

    print(f"\n{'='*60}")
    print(f"  STEP 1 — Scanning source for login routes")
    print(f"{'='*60}")
    candidates = find_routes_in_source(args.app_dir)

    print(f"\n{'='*60}")
    print(f"  STEP 2 — Probing endpoints")
    print(f"{'='*60}")
    token, path = probe_endpoints(base, candidates, args.user, password)

    if not token:
        print("""
  ❌ Could not log in with any endpoint.

  Things to try:
  1. Check username/password are correct
  2. Run with --app-dir pointing to your backend:
       python3 find_login.py --app-dir /opt/riskuw/backend --user admin --url http://localhost:8000
  3. Check if backend is running:
       curl http://localhost:8000/health
  4. Look at your backend routes manually:
       grep -r "login\|token" /opt/riskuw/backend --include="*.py" -l
""")
        sys.exit(1)

    print(f"\n  Use this in debug_smtp.py:")
    print(f"    python3 debug_smtp.py --url {base} --user {args.user} --login-path {path}")

    quick_smtp_check(base, token)

if __name__ == "__main__":
    main()

