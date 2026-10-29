"""Identity and role-based access.

Identity sources, checked in this order:

1. **SSO proxy** (``SEMLIFT_TRUST_PROXY_HEADERS=1``): an authenticating reverse proxy such as oauth2-proxy,
   an API gateway or an ingress with OIDC sets ``X-Forwarded-Email`` / ``X-Forwarded-User`` and
   ``X-Forwarded-Groups``. Only enable this when the app is reachable exclusively through that proxy.
2. **Personal API tokens** from the users file (``SEMLIFT_USERS_FILE``), stored as SHA-256 hashes.
3. **Legacy shared token** (``SEMLIFT_API_TOKEN``): one administrator identity called ``api``.
4. **Open mode**: nothing configured, every caller is the local administrator (single-user / evaluation).

Users file::

    users:
      - name: Priya Shah
        email: priya@client.com
        token_sha256: 5e884898da...          # sha256 of the personal token
        roles: [viewer]                      # roles in every project
        projects: {"acme-*": [steward, approver]}
    groups:                                  # IdP group -> {project pattern: roles}
      semanticlift-admins: {"*": [admin]}
      acme-data-stewards: {"acme-*": [steward]}
"""
from __future__ import annotations

import fnmatch
import hashlib
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = ("viewer", "analyst", "steward", "approver", "deployer", "admin")
ROLE_HELP = {
    "viewer": "read every page and download the package",
    "analyst": "upload exports and run the pipeline",
    "steward": "record report, KPI, source, finding and suggestion decisions",
    "approver": "approve, edit or reject generated objects",
    "deployer": "commit approved objects to Git and run parity checks",
    "admin": "create and archive projects and change settings (implies every role)",
}


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Identity:
    name: str
    email: str = ""
    mode: str = "open"                               # open | token | users | proxy
    roles: set[str] = field(default_factory=set)     # roles in every project
    project_roles: list[tuple[str, set[str]]] = field(default_factory=list)   # (fnmatch pattern, roles)

    def roles_for(self, project: str | None) -> set[str]:
        out = set(self.roles)
        if project:
            for pat, roles in self.project_roles:
                if fnmatch.fnmatchcase(project, pat):
                    out |= roles
        if "admin" in out:
            return set(ROLES)
        return out | ({"viewer"} if out else set())

    def can(self, role: str, project: str | None) -> bool:
        return role in self.roles_for(project)

    def is_admin(self) -> bool:
        return "admin" in self.roles or any(p == "*" and "admin" in r for p, r in self.project_roles)

    def public(self, project: str | None = None) -> dict:
        return {"name": self.name, "email": self.email, "auth_mode": self.mode, "admin": self.is_admin(),
                "roles": sorted(self.roles_for(project), key=ROLES.index)}


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_cache: tuple[str, float, dict] | None = None


def users_config() -> dict:
    """Users file, re-read when it changes so access can be granted without a restart."""
    global _cache
    path = os.environ.get("SEMLIFT_USERS_FILE")
    if not path or not Path(path).exists():
        return {}
    mtime = Path(path).stat().st_mtime
    if _cache is None or _cache[0] != path or _cache[1] != mtime:
        _cache = (path, mtime, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    return _cache[2]


def _check_roles(roles) -> set[str]:
    bad = set(roles or []) - set(ROLES)
    if bad:
        raise AuthError(500, f"unknown role(s) in users file: {', '.join(sorted(bad))}")
    return set(roles or [])


def _from_user(u: dict, mode: str) -> Identity:
    return Identity(name=u.get("name") or u.get("email", "user"), email=u.get("email", ""), mode=mode,
                    roles=_check_roles(u.get("roles")),
                    project_roles=[(p, _check_roles(r)) for p, r in (u.get("projects") or {}).items()])


def _truthy(v: str | None) -> bool:
    return (v or "").lower() in ("1", "true", "yes", "on")


def auth_mode() -> str:
    if _truthy(os.environ.get("SEMLIFT_TRUST_PROXY_HEADERS")):
        return "proxy"
    if os.environ.get("SEMLIFT_USERS_FILE"):
        return "users"
    if os.environ.get("SEMLIFT_API_TOKEN"):
        return "token"
    return "open"


def resolve_identity(headers) -> Identity:
    """headers: a case-insensitive mapping (Starlette Headers)."""
    cfg = users_config()
    users = cfg.get("users") or []
    if _truthy(os.environ.get("SEMLIFT_TRUST_PROXY_HEADERS")):
        email = headers.get("x-forwarded-email") or ""
        user = headers.get("x-forwarded-preferred-username") or headers.get("x-forwarded-user") or email
        if user:
            groups = [g.strip() for g in (headers.get("x-forwarded-groups") or "").split(",") if g.strip()]
            known = next((u for u in users if email and u.get("email", "").lower() == email.lower()), None)
            ident = _from_user(known, "proxy") if known else Identity(name=user, email=email, mode="proxy")
            ident.name = known.get("name", user) if known else user
            for gname in groups:
                for pat, roles in ((cfg.get("groups") or {}).get(gname) or {}).items():
                    ident.project_roles.append((pat, _check_roles(roles)))
            return ident
    authz = headers.get("authorization") or ""
    token = authz[7:] if authz.lower().startswith("bearer ") else ""
    shared = os.environ.get("SEMLIFT_API_TOKEN")
    if token and shared and hmac.compare_digest(token, shared):
        return Identity(name="api", mode="token", roles={"admin"})
    if token and users:
        h = sha256(token)
        for u in users:
            if u.get("token_sha256") and hmac.compare_digest(h, u["token_sha256"].lower()):
                return _from_user(u, "users")
    if auth_mode() == "open":
        return Identity(name=headers.get("x-semlift-user") or "local", mode="open", roles={"admin"})
    raise AuthError(401, "sign in required: missing or invalid credentials")
