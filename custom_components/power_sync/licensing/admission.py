"""Local admission generation; recovery remains owned by the hardware lifecycle."""
from __future__ import annotations
import time

from .permission import VerifiedPermission


class OptimizerAdmission:
    """Close dispatch synchronously before awaiting an expiry cleanup."""

    def __init__(self, *, enforced: bool = False):
        self.enforced = enforced
        self.permission: VerifiedPermission | None = None
        self.generation = 0
        self.suspended = False

    def replace(self, permission: VerifiedPermission) -> None:
        previous = self.permission
        if previous and (permission.epoch, permission.revision) < (previous.epoch, previous.revision):
            raise ValueError("stale_revision")
        if self.enforced and previous and previous.entitled and permission.issued_at >= previous.expires_at:
            self.suspend()
        self.permission = permission
        if not permission.entitled:
            if self.enforced:
                self.suspend()
            elif previous is None or previous.entitled:
                self.generation += 1  # Shadow observations fence old work without inventing an access gap.

    def suspend(self) -> None:
        if self.suspended:
            return
        self.suspended = True
        self.generation += 1

    def permits(self, now: int, *, generation: int | None = None) -> bool:
        if generation is not None and generation != self.generation:
            return False
        if not self.enforced:
            return True
        if self.permission and not self.suspended and now >= self.permission.expires_at:
            self.suspend()
        return bool(not self.suspended and (generation is None or generation == self.generation)
                    and self.permission and self.permission.allows_optimization(now))

    def resume(self, now: int) -> None:
        if self.enforced and not (self.permission and self.permission.allows_optimization(now)):
            raise ValueError("optimizer_access_required")
        self.suspended = False
        self.generation += 1

    def api_status(self, now: int | None = None) -> dict:
        now = int(time.time()) if now is None else now
        permission = self.permission
        valid = bool(permission and permission.allows_optimization(now))
        return {"schema": 1, "enforcement_mode": "enforced" if self.enforced else "shadow",
                "can_optimize": self.permits(now), "would_allow": valid,
                "access_state": permission.source if valid else ("expired" if permission and permission.entitled else "unpaired" if not permission else permission.source),
                "valid_until": permission.expires_at if permission else None,
                "last_verified_at": permission.issued_at if permission else None,
                "requires_resume": self.suspended and valid}
