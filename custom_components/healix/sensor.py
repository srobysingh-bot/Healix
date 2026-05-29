"""Healix dashboard sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HealixEntity


@dataclass(frozen=True, kw_only=True)
class HealixSensorDescription(SensorEntityDescription):
    """Healix sensor description."""

    value_fn: Any


SENSORS = (
    HealixSensorDescription(
        key="active_issues",
        name="Active issues",
        icon="mdi:alert-circle-outline",
        value_fn=lambda coordinator: coordinator.active_issue_count,
    ),
    HealixSensorDescription(
        key="last_failed_entity",
        name="Last failed entity",
        icon="mdi:home-alert-outline",
        value_fn=lambda coordinator: coordinator.last_failed_entity or "none",
    ),
    HealixSensorDescription(
        key="last_recovery_result",
        name="Last recovery result",
        icon="mdi:history",
        value_fn=lambda coordinator: coordinator.last_recovery_result or "none",
    ),
    HealixSensorDescription(
        key="reload_count_today",
        name="Reload count today",
        icon="mdi:reload",
        value_fn=lambda coordinator: coordinator.incident_store.counts_today()["reloads"],
    ),
    HealixSensorDescription(
        key="blocked_count_today",
        name="Blocked count today",
        icon="mdi:block-helper",
        value_fn=lambda coordinator: coordinator.incident_store.counts_today()["blocked"],
    ),
    HealixSensorDescription(
        key="network_health",
        name="Network health",
        icon="mdi:network-outline",
        value_fn=lambda coordinator: coordinator.last_network_status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healix sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(HealixSensor(coordinator, description) for description in SENSORS)


class HealixSensor(HealixEntity, SensorEntity):
    """A Healix dashboard sensor."""

    entity_description: HealixSensorDescription

    def __init__(self, coordinator, description: HealixSensorDescription) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description
        self._attr_icon = description.icon

    @property
    def native_value(self) -> Any:
        """Return sensor state."""
        return self.entity_description.value_fn(self.coordinator)
