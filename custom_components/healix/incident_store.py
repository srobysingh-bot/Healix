"""Incident timeline storage for Healix."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DEFAULT_HISTORY_LIMIT, DOMAIN

STORAGE_KEY = f"{DOMAIN}.incidents"
STORAGE_VERSION = 1


@dataclass(slots=True)
class HealixIncident:
    """A Healix incident timeline entry."""

    incident_id: str
    created_at: str
    entity_id: str | None = None
    integration_domain: str | None = None
    config_entry_id: str | None = None
    device_id: str | None = None
    area_id: str | None = None
    old_state: str | None = None
    new_state: str | None = None
    failure_start_time: str | None = None
    ha_uptime_seconds: int | None = None
    network_health: str | None = None
    affected_entities: list[str] = field(default_factory=list)
    decision: str | None = None
    reload_attempted: bool = False
    blocked_reason: str | None = None
    recovery_result: str | None = None
    recovered_after_seconds: float | None = None
    dry_run: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class HealixIncidentStore:
    """Persist a bounded incident timeline."""

    def __init__(self, hass: HomeAssistant, limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self.hass = hass
        self.limit = limit
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._incidents: deque[HealixIncident] = deque(maxlen=limit)

    @property
    def incidents(self) -> list[HealixIncident]:
        """Return incidents newest last."""
        return list(self._incidents)

    @property
    def last_incident(self) -> HealixIncident | None:
        """Return the newest incident."""
        if not self._incidents:
            return None
        return self._incidents[-1]

    async def async_load(self) -> None:
        """Load incident history."""
        data = await self._store.async_load() or {}
        for item in data.get("incidents", [])[-self.limit :]:
            try:
                self._incidents.append(HealixIncident(**item))
            except TypeError:
                continue

    async def async_save(self) -> None:
        """Persist incident history."""
        await self._store.async_save(
            {"incidents": [asdict(incident) for incident in self._incidents]}
        )

    async def async_add(self, **kwargs: Any) -> HealixIncident:
        """Add an incident and persist it."""
        incident = HealixIncident(
            incident_id=f"{dt_util.utcnow().timestamp():.6f}",
            created_at=dt_util.utcnow().isoformat(),
            **kwargs,
        )
        self._incidents.append(incident)
        await self.async_save()
        return incident

    def counts_today(self) -> dict[str, int]:
        """Return simple daily counters."""
        today = dt_util.now().date()
        reloads = 0
        blocked = 0
        active = 0
        for incident in self._incidents:
            try:
                created = datetime.fromisoformat(incident.created_at).date()
            except ValueError:
                continue
            if created != today:
                continue
            if incident.reload_attempted:
                reloads += 1
            if incident.blocked_reason:
                blocked += 1
            if incident.recovery_result not in {"recovered", "would_recover"}:
                active += 1
        return {"reloads": reloads, "blocked": blocked, "active": active}

    def export_report(self) -> str:
        """Generate a compact JSON report."""
        return json.dumps(
            {
                "generated_at": dt_util.utcnow().isoformat(),
                "incident_count": len(self._incidents),
                "incidents": [asdict(incident) for incident in self._incidents],
            },
            indent=2,
            sort_keys=True,
        )
