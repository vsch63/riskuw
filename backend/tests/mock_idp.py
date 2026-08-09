"""
backend/tests/mock_idp.py
──────────────────────────
In-process mock OpenID Connect provider for SSO tests.

Served as a FastAPI ASGI app. The test fixture boots it with uvicorn on a
random 127.0.0.1 port and sets BASE_URL to that origin, so the app under test
reaches it over plain sync HTTP (httpx.ASGITransport is async-only in 0.28).

  GET /.well-known/openid-configuration   discovery document
  GET /jwks                               RSA public JWK (kid=test-key-1)
  GET /authorize                          302 → redirect_uri?code=…&state=…
  POST /token                             issues an RS256 ID token for a seeded code

The test seeds the per-code identity registry with seed_code() before driving
the backend's callback, so the issued ID token carries the right
sub/email/name/nonce for the flow row the backend just created.
"""
from __future__ import annotations

import base64
from urllib.parse import parse_qs

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import jwt as jose_jwt

# Tests set BASE_URL to the uvicorn origin once the server is up; every
# discovery endpoint and ID-token issuer is derived from it.
BASE_URL = "http://idp"
CLIENT_ID = "test-sso-client"
KID = "test-key-1"

app = FastAPI(title="Mock OIDC IdP")

# In-process RSA keypair (fine for tests).
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


def _b64_int(n: int) -> str:
    return base64.urlsafe_b64encode(
        n.to_bytes((n.bit_length() + 7) // 8, "big")
    ).rstrip(b"=").decode()


def _public_jwk() -> dict:
    pub = _PRIVATE_KEY.public_key().public_numbers()
    return {
        "kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
        "n": _b64_int(pub.n), "e": _b64_int(pub.e),
    }


# code → identity the test seeds before the callback
_codes: dict[str, dict] = {}


def seed_code(code: str, *, sub: str, email: str, name: str, nonce: str,
              verifier: str | None = None) -> None:
    _codes[code] = {"sub": sub, "email": email, "name": name,
                    "nonce": nonce, "verifier": verifier}


def reset_codes() -> None:
    _codes.clear()


def issue_id_token(sub: str, email: str, name: str, nonce: str) -> str:
    return jose_jwt.encode(
        {"iss": BASE_URL, "sub": sub, "aud": CLIENT_ID,
         "email": email, "name": name, "nonce": nonce,
         "preferred_username": email.split("@")[0],
         "iat": 1700000000, "exp": 4100000000},
        _PEM, algorithm="RS256", headers={"kid": KID},
    )


@app.get("/.well-known/openid-configuration")
def discovery():
    return {
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/authorize",
        "token_endpoint": f"{BASE_URL}/token",
        "jwks_uri": f"{BASE_URL}/jwks",
        "response_types_supported": ["code"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/jwks")
def jwks():
    return {"keys": [_public_jwk()]}


@app.get("/authorize")
def authorize(client_id: str = "", redirect_uri: str = "", state: str = ""):
    return RedirectResponse(url=f"{redirect_uri}?code=TEST_CODE&state={state}",
                            status_code=302)


@app.post("/token")
async def token(request: Request):
    body = await request.body()
    form = parse_qs(body.decode())
    code = (form.get("code") or [""])[0]
    client_id = (form.get("client_id") or [""])[0]
    verifier = (form.get("code_verifier") or [None])[0]
    identity = _codes.get(code)
    if not identity or client_id != CLIENT_ID:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if identity.get("verifier") and identity.get("verifier") != verifier:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    id_token = issue_id_token(identity["sub"], identity["email"],
                              identity["name"], identity["nonce"])
    return {"id_token": id_token, "access_token": "test-access",
            "token_type": "Bearer", "expires_in": 3600}
