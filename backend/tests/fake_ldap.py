"""
backend/tests/fake_ldap.py
──────────────────────────
In-process fake LDAP directory for SSO tests.

ldap3 2.9.1 removed the old ldap3.utils.fake machinery, so this shim stands in
for the directory: it implements just enough of the ldap3 Server/Connection
surface that backend/services/sso.py's `ldap_authenticate` touches. Tests
monkeypatch ldap3.Server / ldap3.Connection to point here.

Supported surface:
  * a search bind (service account or anonymous) followed by a user search
  * a user re-bind that verifies the presented password (auto_bind)
  * attribute access shaped like ldap3's entry[attr].values
"""
from __future__ import annotations

import re


class FakeLdapEntry:
    """Shapes like an ldap3 Entry: entry_dn + entry[attr].values."""

    def __init__(self, dn: str, attributes: dict):
        self.entry_dn = dn
        self._attributes = {k.lower(): v for k, v in attributes.items()}

    def __getitem__(self, name: str):
        class _Attr:
            pass
        a = _Attr()
        value = self._attributes.get(name.lower())
        a.values = [value] if value is not None else []
        return a


class FakeLdapConnection:
    """Mimics the ldap3 Connection surface used by the SSO service."""

    def __init__(self, directory: "FakeLdapDirectory", user=None, password=None,
                 auto_bind: bool = False):
        self._directory = directory
        self._user = user
        self._password = password
        self.entries: list = []
        self.response: list = []
        if auto_bind and user:
            if not directory.verify_bind(user, password):
                raise ValueError("invalidCredentials")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def search(self, search_base, search_filter, attributes=None):
        username = self._directory.username_from_filter(search_filter)
        user = self._directory.find_user(username)
        if user is None:
            self.entries = []
            return False
        self.entries = [FakeLdapEntry(user["dn"], user["attributes"])]
        self.response = [{"dn": user["dn"]}]
        return True


class FakeLdapDirectory:
    """users: list of {username, password, dn, attributes}."""

    def __init__(self, users: list[dict]):
        self._users = {u["username"].lower(): u for u in users}

    def verify_bind(self, dn: str, password: str) -> bool:
        for u in self._users.values():
            if u["dn"] == dn:
                return u["password"] == password
        return False

    def username_from_filter(self, search_filter: str) -> str | None:
        # Pull the final (attr=value) clause — the service substitutes
        # {username} into the filter, so the leaf value is the username.
        clauses = re.findall(r"\(([^()]+)=([^()]+)\)", search_filter)
        return clauses[-1][1].strip() if clauses else None

    def find_user(self, username: str | None):
        return self._users.get((username or "").lower())
