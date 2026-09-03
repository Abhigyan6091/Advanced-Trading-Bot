"""RBAC roles.

Three roles, each a strict superset of the one before it. Every route
declares the minimum role it requires; a higher role always satisfies a
lower requirement.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    #: Read-only access to the dashboard.
    VIEWER = "viewer"
    #: Everything a viewer can do, plus running backtests and (once wired)
    #: submitting trades.
    TRADER = "trader"
    #: Everything a trader can do, plus user management and audit logs.
    ADMIN = "admin"


#: Ranking used to decide whether a role satisfies a requirement.
_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.TRADER: 1, Role.ADMIN: 2}


def satisfies(actual: Role, required: Role) -> bool:
    """True when ``actual`` meets or exceeds ``required``."""
    return _RANK[actual] >= _RANK[required]
