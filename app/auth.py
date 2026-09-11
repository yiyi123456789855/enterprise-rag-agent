from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Trusted request identity produced by the authentication boundary."""

    user_id: str
    tenant_id: str
    departments: tuple[str, ...] = ()
    roles: frozenset[str] = frozenset()
    authenticated: bool = True
    legacy: bool = False

    def has_any_role(self, *allowed: str) -> bool:
        return bool(self.roles.intersection(allowed))
