"""Healix dashboard binary sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HealixEntity


@dataclass(frozen=True, kw_only=True)
class HealixBinarySensorDescription(BinarySensorEntityDescription):
    """Healix binary sensor description."""

    value_fn: Any


BINARY_SENSORS = (
    HealixBinarySensorDescription(
        key="recovery_active",
        name="Recovery active",
        icon="mdi:autorenew",
        value_fn=lambda coordinator: coordinator.recovery_active,
    ),
    HealixBinarySensorDescription(
        key="network_outage",
        name="Network outage",
        icon="mdi:network-off-outline",
        value_fn=lambda coordinator: coordinator.network_outage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healix binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HealixBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class HealixBinarySensor(HealixEntity, BinarySensorEntity):
    """A Healix binary sensor."""

    entity_description: HealixBinarySensorDescription

    def __init__(self, coordinator, description: HealixBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description
        self._attr_icon = description.icon

    @property
    def is_on(self) -> bool:
        """Return binary sensor state."""
        return bool(self.entity_description.value_fn(self.coordinator))
