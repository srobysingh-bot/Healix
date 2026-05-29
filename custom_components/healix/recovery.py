"""Safe config-entry recovery for Healix."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant

from .const import STATE_UNAVAILABLE_VALUES


@dataclass(slots=True)
class RecoveryResult:
    """Result of a recovery attempt."""

    attempted: bool
    success: bool
    result: str
    recovered_after_seconds: float | None = None
    error: str | None = None


class HealixRecoveryManager:
    """Reload config entries and verify entity recovery."""

    def __init__(self, hass: HomeAssistant, recovery_wait: int) -> None:
        self.hass = hass
        self.recovery_wait = recovery_wait
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_reload_and_verify(
        self,
        *,
        config_entry_id: str,
        entity_ids: list[str],
    ) -> RecoveryResult:
        """Reload one config entry and verify affected entities."""
        lock = self._locks.setdefault(config_entry_id, asyncio.Lock())
        async with lock:
            started = monotonic()
            try:
                ok = await self.hass.config_entries.async_reload(config_entry_id)
            except Exception as err:  # noqa: BLE001 - recovery must not crash HA
                return RecoveryResult(
                    attempted=True,
                    success=False,
                    result="reload_exception",
                    error=str(err),
                )
            if ok is False:
                return RecoveryResult(
                    attempted=True,
                    success=False,
                    result="reload_rejected",
                )

            await asyncio.sleep(self.recovery_wait)
            if not entity_ids:
                return RecoveryResult(
                    attempted=True,
                    success=True,
                    result="reload_complete_unverified",
                )
            recovered = self._entities_recovered(entity_ids)
            return RecoveryResult(
                attempted=True,
                success=recovered,
                result="recovered" if recovered else "still_unavailable",
                recovered_after_seconds=round(monotonic() - started, 1)
                if recovered
                else None,
            )

    def _entities_recovered(self, entity_ids: list[str]) -> bool:
        if not entity_ids:
            return True
        for entity_id in set(entity_ids):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in STATE_UNAVAILABLE_VALUES:
                return False
        return True
