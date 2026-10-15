"""Detect shared Tesla packages left incompatible by an earlier upgrade.

PowerSync no longer installs tesla-protocol. Removing a requirement does not
uninstall it, and HA checks its direct requirements rather than repairing an
already installed library's transitive dependencies. Inspect metadata without
importing Tesla modules or changing the running Python environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import logging

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

_LOGGER = logging.getLogger(__name__)
ISSUE_ID = "tesla_dependency_conflict"
_CLIENT_PACKAGES = {
    "tesla_fleet": {"tesla-fleet-api"},
    "tessie": {"tesla-fleet-api"},
    "teslemetry": {"tesla-fleet-api", "aiopowerwall"},
}
_SHARED_PACKAGES = {"tesla-protocol", "protobuf"}


@dataclass(frozen=True)
class DependencyCheck:
    """Only a complete successful inspection can clear an existing repair."""

    conflicts: tuple[str, ...]
    complete: bool


def inspect_tesla_dependencies(packages: set[str]) -> DependencyCheck:
    """Compare installed dependencies with their consumers' own contracts."""
    pending = set(packages)
    checked: set[str] = set()
    conflicts: set[str] = set()
    complete = True
    while pending:
        name = pending.pop()
        if name in checked:
            continue
        checked.add(name)
        try:
            consumer = metadata.distribution(name)
            Version(consumer.version)
            for text in consumer.requires or ():
                requirement = Requirement(text)
                dependency = canonicalize_name(requirement.name)
                if dependency not in _SHARED_PACKAGES:
                    continue
                if requirement.marker and not requirement.marker.evaluate():
                    continue
                if requirement.url:
                    complete = False  # A version cannot verify a direct URL.
                    continue
                try:
                    installed = metadata.version(dependency)
                except metadata.PackageNotFoundError:
                    installed = None
                if installed is None or not requirement.specifier.contains(
                    Version(installed), prereleases=True
                ):
                    conflicts.add(
                        f"{name} {consumer.version} requires {requirement}; "
                        f"installed {installed or 'missing'}"
                    )
                if installed is not None:
                    pending.add(dependency)
        except Exception:
            # Absent/unreadable consumer metadata is not proof of compatibility.
            complete = False
            _LOGGER.debug("Could not inspect %s dependency metadata", name, exc_info=True)
    return DependencyCheck(tuple(sorted(conflicts)), complete)


async def async_check_tesla_dependencies(hass) -> None:
    """Check after HA startup, once integration requirement installs settle."""
    from homeassistant.helpers import issue_registry as ir

    packages: set[str] = set()
    for entry in hass.config_entries.async_entries():
        # Disabled clients cannot be the source of an active startup failure.
        if getattr(entry, "disabled_by", None) is None:
            packages.update(_CLIENT_PACKAGES.get(entry.domain, set()))
    try:
        check = await hass.async_add_executor_job(inspect_tesla_dependencies, packages)
    except Exception:
        # Diagnostics must not prevent PowerSync's remaining startup work.
        _LOGGER.warning("Could not check shared Tesla dependencies", exc_info=True)
        return
    if check.conflicts:
        details = "\n".join(f"- {conflict}" for conflict in check.conflicts)
        ir.async_create_issue(
            hass,
            "power_sync",
            ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_ID,
            translation_placeholders={"conflicts": details},
        )
        _LOGGER.error(
            "Incompatible shared Tesla packages detected:\n%s\n"
            "PowerSync no longer installs tesla-protocol. An earlier update may "
            "have left incompatible packages installed. On Home Assistant OS, "
            "back up, then run 'ha core rebuild' in Terminal & SSH. A normal "
            "restart may retain the conflicting packages. See Settings > System "
            "> Repairs for recovery instructions.",
            details,
        )
    elif check.complete:
        ir.async_delete_issue(hass, "power_sync", ISSUE_ID)
