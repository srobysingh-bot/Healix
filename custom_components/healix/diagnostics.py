"""Diagnostics helpers for Healix."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import CONF_NETWORK_HEALTH_ENTITIES, STATE_UNAVAILABLE_VALUES


@dataclass(slots=True)
class Diagnosis:
    """A Healix diagnosis result."""

    network_healthy: bool
    network_status: str
    broad_outage: bool
    failed_setup: bool
    reason: str
    affected_unavailable_count: int = 0
    affected_config_entries: int = 0


class HealixDiagnostics:
    """Diagnose failures before any recovery action."""

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        self.hass = hass
        self.options = options
        self._network_outage_notified = False

    @property
    def network_health_entities(self) -> list[str]:
        """Return configured network health entities."""
        return list(self.options.get(CONF_NETWORK_HEALTH_ENTITIES, []))

    def network_health(self) -> tuple[bool, str]:
        """Evaluate configured network health entities."""
        configured = self.network_health_entities
        if not configured:
            return True, "not_configured"

        bad: list[str] = []
        unknown: list[str] = []
        for entity_id in configured:
            state = self.hass.states.get(entity_id)
            if state is None:
                unknown.append(entity_id)
                continue
            if state.state in STATE_UNAVAILABLE_VALUES or state.state == "off":
                bad.append(entity_id)

        if bad:
            return False, f"network_health_entities_down:{','.join(bad)}"
        if unknown and len(unknown) == len(configured):
            return False, f"network_health_entities_unknown:{','.join(unknown)}"
        return True, "healthy"

    def broad_outage(self) -> tuple[bool, int, int]:
        """Detect broad unrelated entity outage."""
        unavailable = [
            state.entity_id
            for state in self.hass.states.async_all()
            if state.state in STATE_UNAVAILABLE_VALUES
        ]
        total = max(1, len(self.hass.states.async_all()))
        affected_entries: set[str] = set()
        for entity_id in unavailable:
            entry = self._entity_registry_entry(entity_id)
            if entry and getattr(entry, "config_entry_id", None):
                affected_entries.add(entry.config_entry_id)

        count = len(unavailable)
        entry_count = len(affected_entries)
        broad = count >= 10 and entry_count >= 4 and count / total >= 0.08
        return broad, count, entry_count

    def failed_setup(self, config_entry_id: str | None) -> bool:
        """Return whether a config entry is in setup failure/retry state."""
        if not config_entry_id:
            return False
        entry = self.hass.config_entries.async_get_entry(config_entry_id)
        if not entry:
            return False
        failed_states = {
            ConfigEntryState.SETUP_ERROR,
            ConfigEntryState.SETUP_RETRY,
            getattr(ConfigEntryState, "MIGRATION_ERROR", object()),
        }
        return entry.state in failed_states

    def diagnose(self, config_entry_id: str | None = None) -> Diagnosis:
        """Run all safety diagnostics."""
        network_healthy, network_status = self.network_health()
        broad, unavailable_count, entry_count = self.broad_outage()
        failed_setup = self.failed_setup(config_entry_id)
        if not network_healthy:
            reason = "network_issue"
        elif broad:
            reason = "broad_outage"
        elif failed_setup:
            reason = "failed_setup"
        else:
            reason = "entity_or_config_entry_failure"
        return Diagnosis(
            network_healthy=network_healthy,
            network_status=network_status,
            broad_outage=broad,
            failed_setup=failed_setup,
            reason=reason,
            affected_unavailable_count=unavailable_count,
            affected_config_entries=entry_count,
        )

    def _entity_registry_entry(self, entity_id: str) -> Any:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(self.hass).async_get(entity_id)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Any
) -> dict[str, Any]:
    """Return diagnostics download data for Healix."""
    coordinator = hass.data.get("healix", {}).get(entry.entry_id)
    if coordinator is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "paused": coordinator.paused,
        "dry_run": coordinator.policy.dry_run,
        "summary": coordinator.classifier.integration_summary(),
        "incidents": [
            asdict(incident) for incident in coordinator.incident_store.incidents[-50:]
        ],
    }
