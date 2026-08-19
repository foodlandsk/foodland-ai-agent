"""
app/admin_auth.py  -  V2.12.1 Part B: three-tier scoped admin authorization.

Before this module, every /admin/* endpoint (14 of them - see
docs/runtime-state-inventory.md section 9) shared one flat check:
ADMIN_ANALYTICS_TOKEN OR ADMIN_RELOAD_TOKEN, either one granting access to
every admin capability including, once Part C lands, ranking-profile
promotion. A token minted purely to view analytics dashboards therefore
had, by construction, the same blast radius as a token meant to promote a
learning candidate into production ranking config - there was no way to
hand out read-only access without also handing out promotion power.

Three scopes, ranked (higher satisfies lower - see the auth test matrix in
tests/test_admin_auth.py):
  READ        - view analytics/learning status/history. No side effects.
  OPERATIONS  - trigger feed refresh, embeddings rebuild, learning-cycle
                run. Real work, but never moves config/ranking_profiles/
                active.json (a manually-triggered learning cycle can reach
                at most READY_FOR_APPROVAL - see app.learning_lifecycle,
                whose only ACTIVE-reaching function is approve_and_activate(),
                which is not called from the run-cycle endpoint).
  PROMOTION   - approve a candidate or roll back. The only scope that can
                ever change what ranking profile is live for real
                customers.

Legacy compatibility: ADMIN_ANALYTICS_TOKEN, if set, is honored as a
READ-scope token; ADMIN_RELOAD_TOKEN, if set, is honored as an
OPERATIONS-scope token - both exactly as before this module existed, so
an existing deployment that has only ever set these two keeps working
unchanged. Neither legacy token is ever granted PROMOTION - an operator
who wants promotion capability must explicitly provision
ADMIN_PROMOTION_TOKEN. This is a one-way widening of what's possible,
never a narrowing of what already worked (mirrors the same non-surprise
principle app.ranking_config's profile resolution documents for
`ranking_profile=None`).
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from fastapi import HTTPException

SCOPE_READ = "READ"
SCOPE_OPERATIONS = "OPERATIONS"
SCOPE_PROMOTION = "PROMOTION"

_SCOPE_RANK = {SCOPE_READ: 1, SCOPE_OPERATIONS: 2, SCOPE_PROMOTION: 3}


@dataclass(frozen=True)
class _ScopeSource:
    scope: str
    env_var: str


# Highest-ranked source first: if the same token value happens to be
# reused across multiple env vars (e.g. an operator copy-pasted one
# secret into two slots), it resolves to the HIGHEST scope it matches,
# never a lower one - a token is never silently downgraded by var
# ordering.
_SOURCES: tuple[_ScopeSource, ...] = (
    _ScopeSource(SCOPE_PROMOTION, "ADMIN_PROMOTION_TOKEN"),
    _ScopeSource(SCOPE_OPERATIONS, "ADMIN_OPERATIONS_TOKEN"),
    _ScopeSource(SCOPE_OPERATIONS, "ADMIN_RELOAD_TOKEN"),      # legacy -> OPERATIONS
    _ScopeSource(SCOPE_READ, "ADMIN_READ_TOKEN"),
    _ScopeSource(SCOPE_READ, "ADMIN_ANALYTICS_TOKEN"),         # legacy -> READ
)


def _compare(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)


def any_admin_token_configured() -> bool:
    return any(os.getenv(source.env_var, "").strip() for source in _SOURCES)


def resolve_token_scope(x_admin_token: str | None) -> str | None:
    """The HIGHEST scope the presented token is valid for, or None if it
    matches no configured admin token at all."""
    if not x_admin_token:
        return None
    best_rank = 0
    best_scope: str | None = None
    for source in _SOURCES:
        expected = os.getenv(source.env_var, "").strip()
        if not expected:
            continue
        if _SCOPE_RANK[source.scope] > best_rank and _compare(str(x_admin_token), expected):
            best_rank = _SCOPE_RANK[source.scope]
            best_scope = source.scope
    return best_scope


def require_admin_scope(x_admin_token: str | None, required_scope: str) -> str:
    """Replaces the old flat require_admin_token(). Raises 404 if admin
    auth isn't configured at all (preserves the pre-V2.12.1 behavior of
    hiding the endpoint's existence rather than exposing a 401/403 when
    nobody has set up any admin token), 401 if the presented token
    matches nothing configured, 403 if it matches a real token but at too
    low a scope for this endpoint. Returns the granted scope on success
    so callers can include it in an audit log entry."""
    if required_scope not in _SCOPE_RANK:
        raise ValueError(f"unknown admin scope {required_scope!r}")
    if not any_admin_token_configured():
        raise HTTPException(status_code=404, detail="Admin rozhranie nie je zapnuté.")
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Neplatný admin token.")
    granted = resolve_token_scope(x_admin_token)
    if granted is None:
        raise HTTPException(status_code=401, detail="Neplatný admin token.")
    if _SCOPE_RANK[granted] < _SCOPE_RANK[required_scope]:
        raise HTTPException(
            status_code=403,
            detail=f"Admin token má rozsah {granted}, táto operácia vyžaduje {required_scope}.",
        )
    return granted
