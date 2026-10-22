"""Role -> permission matrix. Change access rules HERE, nowhere else."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    row_scope: str            # "all" = every row, "own" = only rows where OWNER = username
    can_insert: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_export: bool = False
    can_manage_users: bool = False
    can_view_audit: bool = False


POLICIES: dict[str, Policy] = {
    "ADMIN": Policy("all", True, True, True, True, True, True),
    "EDITOR": Policy("own", can_insert=True, can_edit=True, can_export=True),
    "ANALYST": Policy("all", can_export=True),
    "VIEWER": Policy("own"),
}

ROLE_DESCRIPTIONS = {
    "ADMIN": "Full access: all rows, create/edit/delete, user management, audit log",
    "EDITOR": "Own rows only: create and edit, export",
    "ANALYST": "All rows, read-only, export",
    "VIEWER": "Own rows only, read-only",
}


def policy_for(role: str | None) -> Policy:
    """Fail closed: unknown roles get the most restrictive policy."""
    return POLICIES.get((role or "").upper(), POLICIES["VIEWER"])
