"""
backend/routers/auth.py
────────────────────────
Handles:  POST /auth/login
          POST /auth/verify-mfa
          GET  /auth/users
          GET  /auth/users/:username
          POST /auth/register
          POST /auth/users/:username/deactivate
          POST /auth/users/:username/activate
          POST /auth/users/:username/change-role
          POST /auth/users/:username/reset-password
          PATCH /auth/users/:username

Tables:   uw_user · mfa_config · login_attempts · audit_trail
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from deps import CurrentUser, AdminOnly, TokenData, get_current_user, SECRET_KEY, ALGORITHM
from schemas.auth import (
    LoginRequest, MFAVerifyRequest, TokenResponse,
    UserCreate, UserOut, PasswordReset,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Helpers ───────────────────────────────────────────────────────

def _get_db():
    from database import get_conn, release_conn
    return get_conn(), release_conn

def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def _verify(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

def _make_token(username: str, role: str, tenant_id: str | None, expires_minutes: int = 480) -> str:
    payload = {
        "sub": username,
        "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def _audit(conn, event_type: str, actor: str, entity_id: str, after: dict, ip: str | None = None):
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_trail
              (event_category, event_type, actor_username, entity_type,
               entity_id, after_state, actor_ip, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'API')
            """,
            ("AUTH", event_type, actor, "uw_user", entity_id,
             __import__("json").dumps(after), ip),
        )
        cur.close()
    except Exception:
        pass  # audit failure must never break the primary operation


# ── Login ─────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    conn, release = _get_db()
    ip = request.client.host if request.client else None
    try:
        cur = conn.cursor()

        # Check lockout
        cur.execute(
            "SELECT locked_until FROM login_attempts WHERE username = %s",
            (body.username,),
        )
        row = cur.fetchone()
        if row:
            locked = row[0] if isinstance(row, tuple) else row.get("locked_until")
            if locked and locked > datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Account locked until {locked.isoformat()}. Too many failed attempts.",
                )

        # Fetch user — accept both username and email (industry standard)
        cur.execute(
            "SELECT u.username, u.hashed_password, u.role, u.is_active, "
            "u.tenant_id::text, t.tenant_name "
            "FROM uw_user u LEFT JOIN tenant t ON t.id = u.tenant_id "
            "WHERE u.username = %s AND u.is_deleted = false",
            (body.username,),
        )
        user = cur.fetchone()

        # Fallback: try email lookup if username not found
        if not user and "@" in (body.username or ""):
            cur.execute(
                "SELECT u.username, u.hashed_password, u.role, u.is_active, "
                "u.tenant_id::text, t.tenant_name "
                "FROM uw_user u LEFT JOIN tenant t ON t.id = u.tenant_id "
                "WHERE u.email = %s AND u.is_deleted = false",
                (body.username,),
            )
            user = cur.fetchone()
        user_dict: dict[str, Any] = (
            dict(user) if hasattr(user, "keys") else
            dict(zip(["username", "hashed_password", "role", "is_active", "tenant_id", "tenant_name"], user))
        ) if user else {}

        if not user or not user_dict.get("is_active"):
            _record_failed(conn, body.username, ip)
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if not _verify(body.password, user_dict["hashed_password"] or ""):
            _record_failed(conn, body.username, ip)
            raise HTTPException(status_code=401, detail="Invalid username or password")

        # Clear failed attempts on success
        cur.execute(
            "INSERT INTO login_attempts (username, failed_count, updated_at) VALUES (%s, 0, now()) "
            "ON CONFLICT (username) DO UPDATE SET failed_count=0, locked_until=NULL, updated_at=now()",
            (body.username,),
        )

        # Check MFA
        cur.execute(
            "SELECT is_enabled, is_verified, totp_secret FROM mfa_config WHERE username = %s",
            (body.username,),
        )
        mfa_row = cur.fetchone()
        mfa_dict = (
            dict(mfa_row) if mfa_row and hasattr(mfa_row, "keys") else
            dict(zip(["is_enabled", "is_verified", "totp_secret"], mfa_row)) if mfa_row else {}
        )

        conn.commit()
        cur.close()

        mfa_required = bool(mfa_dict.get("is_enabled") and mfa_dict.get("is_verified"))

        if mfa_required:
            # Issue short-lived MFA session token (5 min)
            session_tok = _make_token(
                body.username, user_dict["role"], user_dict["tenant_id"],
                expires_minutes=5,
            )
            _audit(conn, "MFA_CHALLENGE", body.username, body.username, {"ip": ip}, ip)
            return TokenResponse(
                access_token="",
                username=body.username,
                role=user_dict["role"],
                tenant_id=user_dict.get("tenant_id"),
                mfa_required=True,
                mfa_session_token=session_tok,
            )

        # No MFA — issue full token
        token = _make_token(body.username, user_dict["role"], user_dict["tenant_id"])
        _update_last_login(conn, body.username)
        _audit(conn, "LOGIN_SUCCESS", body.username, body.username, {"ip": ip, "mfa": False}, ip)
        conn.commit()

        return TokenResponse(
            access_token=token,
            username=body.username,
            role=user_dict["role"],
            tenant_id=user_dict.get("tenant_id"),
            tenant_name=user_dict.get("tenant_name"),
        )
    finally:
        release(conn)


def _record_failed(conn, username: str, ip: str | None):
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO login_attempts (username, failed_count, last_failed_at, updated_at)
            VALUES (%s, 1, now(), now())
            ON CONFLICT (username) DO UPDATE SET
              failed_count = login_attempts.failed_count + 1,
              last_failed_at = now(),
              updated_at = now(),
              locked_until = CASE
                WHEN login_attempts.failed_count + 1 >= 5
                THEN now() + interval '15 minutes'
                ELSE NULL
              END
            """,
            (username,),
        )
        conn.commit()
        cur.close()
    except Exception:
        pass


def _update_last_login(conn, username: str):
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uw_user SET last_login_at = now() WHERE username = %s",
            (username,),
        )
        cur.close()
    except Exception:
        pass


# ── MFA Verify ────────────────────────────────────────────────────

@router.post("/verify-mfa", response_model=TokenResponse)
async def verify_mfa(body: MFAVerifyRequest, request: Request):
    ip = request.client.host if request.client else None

    # Decode the short-lived session token
    from deps import decode_token
    try:
        token_data = decode_token(body.session_token or "")
    except HTTPException:
        raise HTTPException(status_code=401, detail="MFA session expired or invalid")

    if token_data.username != body.username:
        raise HTTPException(status_code=401, detail="Username mismatch")

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT totp_secret FROM mfa_config WHERE username = %s AND is_enabled = true",
            (body.username,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="MFA not configured for this user")

        secret = row[0] if isinstance(row, tuple) else row.get("totp_secret")
        totp = pyotp.TOTP(secret)
        if not totp.verify(body.totp_code.strip(), valid_window=1):
            raise HTTPException(status_code=401, detail="Invalid or expired code")

        # Fetch role + tenant for full token
        cur.execute(
            "SELECT role, tenant_id::text FROM uw_user WHERE username = %s",
            (body.username,),
        )
        u = cur.fetchone()
        role = (u[0] if isinstance(u, tuple) else u.get("role")) if u else "viewer"
        tenant_id = (u[1] if isinstance(u, tuple) else u.get("tenant_id")) if u else None

        # Update last_used_at
        cur.execute(
            "UPDATE mfa_config SET last_used_at = now() WHERE username = %s",
            (body.username,),
        )
        conn.commit()
        cur.close()

        token = _make_token(body.username, role, tenant_id)
        _update_last_login(conn, body.username)
        _audit(conn, "MFA_SUCCESS", body.username, body.username, {"ip": ip}, ip)
        conn.commit()

        return TokenResponse(access_token=token, username=body.username, role=role, tenant_id=tenant_id)
    finally:
        release(conn)


# ── Users ─────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        if current.role == "super_admin":
            # Super admin sees all users across all tenants
            cur.execute("""
                SELECT u.username, u.email, u.full_name, u.role,
                       u.is_active, u.tenant_id::text,
                       t.tenant_name, t.tenant_code
                FROM uw_user u
                LEFT JOIN tenant t ON t.id = u.tenant_id
                WHERE u.is_deleted = false
                ORDER BY t.tenant_name, u.username
            """)
        else:
            # Admin/others see only their own tenant's users
            cur.execute("""
                SELECT u.username, u.email, u.full_name, u.role,
                       u.is_active, u.tenant_id::text,
                       t.tenant_name, t.tenant_code
                FROM uw_user u
                LEFT JOIN tenant t ON t.id = u.tenant_id
                WHERE u.is_deleted = false
                  AND u.tenant_id = %s::uuid
                ORDER BY u.username
            """, (current.tenant_id,))
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            try:
                row_dict = dict(r) if hasattr(r, "keys") else dict(zip(
                    ["username", "email", "full_name", "role", "is_active",
                     "tenant_id", "tenant_name", "tenant_code"], r
                ))
                row_dict["is_active"] = bool(row_dict.get("is_active", False))
                result.append(UserOut(**{k: v for k, v in row_dict.items()
                                         if k in UserOut.model_fields}))
            except Exception as e:
                print(f"DEBUG skipping bad user row {r}: {e}")
        return result
    finally:
        release(conn)

@router.get("/users/{username}", response_model=UserOut)
async def get_user(username: str, current: CurrentUser):
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username, email, full_name, role, is_active, tenant_id::text "
            "FROM uw_user WHERE username = %s AND is_deleted = false",
            (username,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        row_dict = dict(row) if hasattr(row, "keys") else dict(zip(["username", "email", "full_name", "role", "is_active", "tenant_id"], row))
        row_dict["is_active"] = bool(row_dict.get("is_active", False))
        return UserOut(**{k: v for k, v in row_dict.items() if k in UserOut.model_fields})
    finally:
        release(conn)


@router.post("/register", response_model=UserOut, status_code=201)
async def register_user(body: UserCreate, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Only admins can create users")

    # ── Tenant assignment ──────────────────────────────────────────
    if current.role == "super_admin":
        # Super admin must specify which tenant the user belongs to
        tenant_id = body.tenant_id
        if not tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id is required for super_admin user creation")
    else:
        # Admin can only create users within their own tenant
        tenant_id = current.tenant_id
        if body.tenant_id and body.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Admins can only create users in their own tenant")

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        # Check username uniqueness within the tenant
        cur.execute(
            "SELECT 1 FROM uw_user WHERE username = %s AND tenant_id = %s::uuid",
            (body.username, tenant_id)
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Username already exists in this tenant")
        cur.execute(
            """
            INSERT INTO uw_user
              (id, username, email, hashed_password, full_name, role,
               is_active, tenant_id, created_by, updated_by, version, is_deleted)
            VALUES
              (gen_random_uuid(), %s, %s, %s, %s, %s,
               true, %s::uuid, %s, %s, 1, false)
            RETURNING username, email, full_name, role, is_active, tenant_id::text
            """,
            (
                body.username, body.email, _hash(body.password),
                body.full_name, body.role, tenant_id,
                current.username, current.username,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        row_dict = dict(row) if hasattr(row, "keys") else dict(zip(["username", "email", "full_name", "role", "is_active", "tenant_id"], row))
        row_dict["is_active"] = bool(row_dict.get("is_active", False))
        return UserOut(**{k: v for k, v in row_dict.items() if k in UserOut.model_fields})
    finally:
        release(conn)


@router.patch("/users/{username}", response_model=UserOut)
async def update_user(username: str, updates: dict, current: CurrentUser):
    if current.role not in ("admin", "super_admin") and current.username != username:
        raise HTTPException(status_code=403, detail="Forbidden")
    allowed = {"email", "full_name"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        raise HTTPException(status_code=400, detail="No updatable fields provided")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        sets = ", ".join(f"{k} = %s" for k in safe)
        cur.execute(
            f"UPDATE uw_user SET {sets}, updated_at=now(), updated_by=%s "
            f"WHERE username=%s AND is_deleted=false "
            f"RETURNING username, email, full_name, role, is_active, tenant_id::text",
            (*safe.values(), current.username, username),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        row_dict = dict(row) if hasattr(row, "keys") else dict(zip(["username", "email", "full_name", "role", "is_active", "tenant_id"], row))
        row_dict["is_active"] = bool(row_dict.get("is_active", False))
        return UserOut(**{k: v for k, v in row_dict.items() if k in UserOut.model_fields})
    finally:
        release(conn)


@router.post("/users/{username}/deactivate")
async def deactivate_user(username: str, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uw_user SET is_active=false, updated_at=now(), updated_by=%s "
            "WHERE username=%s AND is_deleted=false",
            (current.username, username),
        )
        conn.commit()
        cur.close()
        return {"status": "deactivated", "username": username}
    finally:
        release(conn)


@router.post("/users/{username}/activate")
async def activate_user(username: str, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uw_user SET is_active=true, updated_at=now(), updated_by=%s "
            "WHERE username=%s AND is_deleted=false",
            (current.username, username),
        )
        conn.commit()
        cur.close()
        return {"status": "activated", "username": username}
    finally:
        release(conn)


@router.post("/users/{username}/change-role")
async def change_role(username: str, body: dict, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    new_role = body.get("role")
    if not new_role:
        raise HTTPException(status_code=400, detail="role is required")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uw_user SET role=%s, updated_at=now(), updated_by=%s "
            "WHERE username=%s AND is_deleted=false",
            (new_role, current.username, username),
        )
        conn.commit()
        cur.close()
        return {"status": "role_changed", "username": username, "role": new_role}
    finally:
        release(conn)


@router.post("/users/{username}/reset-password")
async def reset_password(username: str, body: PasswordReset, current: CurrentUser):
    if current.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE uw_user SET hashed_password=%s, updated_at=now(), updated_by=%s "
            "WHERE username=%s AND is_deleted=false",
            (_hash(body.new_password), current.username, username),
        )
        conn.commit()
        _audit(conn, "PASSWORD_RESET", current.username, username, {"reset_by": current.username})
        conn.commit()
        cur.close()
        return {"status": "password_reset", "username": username}
    finally:
        release(conn)


# ── Forgot / Reset Password ───────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(body: dict, request: Request):
    """
    Step 1: User submits username or email.
    Generates a secure reset token (valid 30 min), stores it, sends email.
    Always returns 200 to avoid user enumeration.
    """
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    identifier = (body.get("identifier") or "").strip()
    if not identifier:
        return {"message": "If that account exists, a reset link has been sent."}

    conn, release = _get_db()
    try:
        cur = conn.cursor()

        # Look up by username or email
        cur.execute(
            """
            SELECT username, email, full_name, is_active
            FROM uw_user
            WHERE (username = %s OR email = %s)
              AND is_deleted = false
            LIMIT 1
            """,
            (identifier, identifier),
        )
        row = cur.fetchone()
        if not row:
            return {"message": "If that account exists, a reset link has been sent."}

        user = dict(row) if hasattr(row, "keys") else dict(
            zip(["username", "email", "full_name", "is_active"], row)
        )

        if not user.get("is_active"):
            return {"message": "If that account exists, a reset link has been sent."}

        email_addr = user.get("email")
        if not email_addr:
            return {"message": "No email address on file for this account. Contact your administrator."}

        # Check if user has MFA enabled
        cur.execute(
            "SELECT is_enabled, is_verified FROM mfa_config WHERE username = %s",
            (user["username"],),
        )
        mfa_row = cur.fetchone()
        mfa_dict = dict(mfa_row) if mfa_row and hasattr(mfa_row, "keys") else (
            dict(zip(["is_enabled", "is_verified"], mfa_row)) if mfa_row else {}
        )
        mfa_required = bool(mfa_dict.get("is_enabled") and mfa_dict.get("is_verified"))

        # Generate secure token
        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        # Store token — create table if needed
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token       TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                mfa_verified BOOLEAN DEFAULT FALSE,
                expires_at  TIMESTAMPTZ NOT NULL,
                used_at     TIMESTAMPTZ,
                created_at  TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        # Invalidate any existing tokens for this user
        cur.execute(
            "DELETE FROM password_reset_tokens WHERE username = %s",
            (user["username"],),
        )
        cur.execute(
            """
            INSERT INTO password_reset_tokens (token, username, mfa_verified, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (token, user["username"], not mfa_required, expires_at),
        )
        conn.commit()
        cur.close()

        # Build reset URL
        base_url = os.environ.get("FRONTEND_URL", "https://riskuw.online")
        reset_url = f"{base_url}/reset-password?token={token}"
        if mfa_required:
            reset_url += "&mfa=required"

        # Send email
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "")
        smtp_from = os.environ.get("SMTP_FROM", smtp_user)
        full_name  = user.get("full_name") or user["username"]

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;background:#0a1628;color:#e2e8f0;border-radius:12px;overflow:hidden;">
          <div style="background:linear-gradient(135deg,#0a1e44,#061828);padding:32px 40px;border-bottom:1px solid rgba(0,212,170,0.2);">
            <div style="font-size:20px;font-weight:700;color:#fff;">🛡️ RiskUW</div>
            <div style="font-size:11px;color:#00d4aa;letter-spacing:0.1em;margin-top:4px;">AUTOMATED UNDERWRITING</div>
          </div>
          <div style="padding:36px 40px;">
            <h2 style="color:#fff;font-size:22px;margin:0 0 12px;">Password Reset Request</h2>
            <p style="color:#94a3b8;line-height:1.7;margin:0 0 24px;">
              Hi {full_name},<br><br>
              We received a request to reset your RiskUW password.
              {"Since your account has <strong style='color:#00d4aa'>MFA enabled</strong>, you will need to verify your authenticator code before setting a new password." if mfa_required else ""}
            </p>
            <a href="{reset_url}" style="display:inline-block;background:#00d4aa;color:#0a1628;font-weight:700;font-size:15px;padding:14px 32px;border-radius:8px;text-decoration:none;">
              Reset My Password →
            </a>
            <p style="color:#64748b;font-size:12px;margin:28px 0 0;line-height:1.7;">
              This link expires in <strong style="color:#94a3b8">30 minutes</strong>.<br>
              If you did not request this, you can safely ignore this email.<br>
              Your password will not change unless you click the link above.
            </p>
          </div>
          <div style="padding:20px 40px;background:rgba(0,0,0,0.2);font-size:11px;color:#475569;">
            © 2025 RiskUW · riskuw.online · Secure · IRDAI-aligned
          </div>
        </div>
        """

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "RiskUW — Password Reset Request"
            msg["From"]    = smtp_from
            msg["To"]      = email_addr
            msg.attach(MIMEText(html_body, "html"))

            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, email_addr, msg.as_string())
        except Exception as mail_err:
            import logging
            logging.getLogger("uw_platform").error(f"Password reset email failed: {mail_err}")

        _audit(conn, "PASSWORD_RESET_REQUESTED", user["username"],
               user["username"], {"ip": request.client.host if request.client else None})
        conn.commit()

        return {"message": "If that account exists, a reset link has been sent."}
    finally:
        release(conn)


@router.post("/verify-reset-mfa")
async def verify_reset_mfa(body: dict):
    """
    Step 2 (MFA users only): Verify TOTP before allowing password reset.
    Marks the token as mfa_verified=true.
    """
    token     = (body.get("token") or "").strip()
    totp_code = (body.get("totp_code") or "").strip()

    if not token or not totp_code:
        raise HTTPException(status_code=400, detail="token and totp_code are required")

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, mfa_verified, expires_at, used_at
            FROM password_reset_tokens
            WHERE token = %s
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")

        t = dict(row) if hasattr(row, "keys") else dict(
            zip(["username", "mfa_verified", "expires_at", "used_at"], row)
        )
        if t.get("used_at"):
            raise HTTPException(status_code=400, detail="Reset link already used")
        if t["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Reset link has expired")

        # Verify TOTP
        cur.execute(
            "SELECT totp_secret FROM mfa_config WHERE username = %s AND is_enabled = true",
            (t["username"],),
        )
        mfa_row = cur.fetchone()
        if not mfa_row:
            raise HTTPException(status_code=400, detail="MFA not configured")

        secret = mfa_row[0] if isinstance(mfa_row, tuple) else mfa_row.get("totp_secret")
        totp   = pyotp.TOTP(secret)
        if not totp.verify(totp_code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid authenticator code")

        cur.execute(
            "UPDATE password_reset_tokens SET mfa_verified = true WHERE token = %s",
            (token,),
        )
        conn.commit()
        cur.close()
        return {"message": "MFA verified", "username": t["username"]}
    finally:
        release(conn)


@router.post("/reset-password-confirm")
async def reset_password_confirm(body: dict):
    """
    Final step: Set new password using the reset token.
    Token must be mfa_verified=true (auto-true for non-MFA users).
    """
    token        = (body.get("token") or "").strip()
    new_password = (body.get("new_password") or "").strip()

    if not token or not new_password:
        raise HTTPException(status_code=400, detail="token and new_password are required")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, mfa_verified, expires_at, used_at
            FROM password_reset_tokens
            WHERE token = %s
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired reset link")

        t = dict(row) if hasattr(row, "keys") else dict(
            zip(["username", "mfa_verified", "expires_at", "used_at"], row)
        )
        if t.get("used_at"):
            raise HTTPException(status_code=400, detail="Reset link already used")
        if t["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Reset link has expired")
        if not t.get("mfa_verified"):
            raise HTTPException(status_code=403, detail="MFA verification required before resetting password")

        # Update password and mark token used
        cur.execute(
            "UPDATE uw_user SET hashed_password=%s, updated_at=now(), updated_by='self_reset' "
            "WHERE username=%s AND is_deleted=false",
            (_hash(new_password), t["username"]),
        )
        cur.execute(
            "UPDATE password_reset_tokens SET used_at=now() WHERE token=%s",
            (token,),
        )
        # Clear any login lockouts
        cur.execute(
            "UPDATE login_attempts SET failed_count=0, locked_until=NULL WHERE username=%s",
            (t["username"],),
        )
        conn.commit()
        _audit(conn, "PASSWORD_RESET_COMPLETED", t["username"], t["username"],
               {"method": "self_reset"})
        conn.commit()
        cur.close()
        return {"message": "Password reset successfully. You can now log in."}
    finally:
        release(conn)


# ── MFA Setup ─────────────────────────────────────────────────────────────────

@router.get("/mfa/setup/{username}")
def get_mfa_setup(username: str, current: CurrentUser):
    """Generate (or retrieve) TOTP secret and return provisioning URI + QR data."""
    import pyotp, base64, io
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT totp_secret, is_enabled, is_verified FROM mfa_config WHERE username=%s",
            (username,),
        )
        row = cur.fetchone()
        row_dict = dict(row) if row and hasattr(row, "keys") else (
            dict(zip(["totp_secret","is_enabled","is_verified"], row)) if row else {}
        )

        # Generate new secret if none exists
        if not row_dict.get("totp_secret"):
            secret = pyotp.random_base32()
            cur.execute(
                """
                INSERT INTO mfa_config (username, totp_secret, is_enabled, is_verified, created_at)
                VALUES (%s, %s, false, false, now())
                ON CONFLICT (username) DO UPDATE SET totp_secret=%s
                """,
                (username, secret, secret),
            )
            conn.commit()
        else:
            secret = row_dict["totp_secret"]

        cur.close()

        # Build provisioning URI
        platform = os.environ.get("PLATFORM_NAME", "RiskUW")
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=username, issuer_name=platform)

        # Generate QR code as base64 PNG
        qr_b64 = ""
        try:
            import qrcode
            qr = qrcode.QRCode(box_size=6, border=2)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            qr_b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            print(f"QR FAILED: {type(e).__name__}: {e}")
        print("DEBUG returning qr_base64 length:", len(qr_b64))

        return {
            "username":    username,
            "secret":      secret,
            "uri":         uri,
            "qr_base64":   qr_b64,
            "is_enabled":  row_dict.get("is_enabled", False),
            "is_verified": row_dict.get("is_verified", False),
        }
    finally:
        release(conn)

@router.post("/mfa/enable/{username}")
def enable_mfa(username: str, body: dict, current: CurrentUser):
    """Verify a TOTP code and mark MFA as enabled+verified."""
    import pyotp
    totp_code = body.get("totp_code", "").strip()
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT totp_secret FROM mfa_config WHERE username=%s", (username,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(400, "MFA not set up for this user")
        secret = row[0] if isinstance(row, tuple) else row.get("totp_secret")
        totp = pyotp.TOTP(secret)
        if not totp.verify(totp_code, valid_window=1):
            raise HTTPException(400, "Invalid code — try again")
        cur.execute(
            "UPDATE mfa_config SET is_enabled=true, is_verified=true, enabled_at=now() WHERE username=%s",
            (username,),
        )
        conn.commit()
        cur.close()
        return {"status": "enabled", "username": username}
    finally:
        release(conn)


@router.post("/mfa/disable/{username}")
def disable_mfa(username: str, current: CurrentUser):
    if current.role not in ("admin", "super_admin") and current.username != username:
        raise HTTPException(403, "Forbidden")
    conn, release = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE mfa_config SET is_enabled=false, is_verified=false WHERE username=%s",
            (username,),
        )
        conn.commit()
        cur.close()
        return {"status": "disabled", "username": username}
    finally:
        release(conn)
