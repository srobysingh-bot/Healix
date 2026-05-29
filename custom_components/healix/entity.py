"""Shared Healix entity helpers."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, NAME


class HealixEntity(Entity):
    """Base class for Healix dashboard entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, key: str, name: str) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=NAME,
            manufacturer="Healix",
            model="Recovery Supervisor",
        )
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self._remove_listener = self.coordinator.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Remove coordinator listener."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
