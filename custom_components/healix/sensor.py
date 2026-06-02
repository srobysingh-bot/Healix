"""Healix dashboard sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HealixEntity

MAX_VISIBLE_ENTITY_NAME_LENGTH = 35


@dataclass(frozen=True, kw_only=True)
class HealixSensorDescription(SensorEntityDescription):
    """Healix sensor description."""

    value_fn: Any


SENSORS = (
    HealixSensorDescription(
        key="status",
        name="Status",
        icon="mdi:heart-pulse",
        value_fn=lambda coordinator: coordinator.status,
    ),
    HealixSensorDescription(
        key="active_issues",
        name="Active issues",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.active_issue_count,
    ),
    HealixSensorDescription(
        key="unavailable_entities_total",
        name="Unavailable entities total",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.unavailable_entities_total,
    ),
    HealixSensorDescription(
        key="actionable_issues",
        name="Actionable issues",
        icon="mdi:alert-decagram-outline",
        value_fn=lambda coordinator: coordinator.actionable_issue_count,
    ),
    HealixSensorDescription(
        key="ignored_issues",
        name="Ignored issues",
        icon="mdi:bell-off-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.ignored_issue_count,
    ),
    HealixSensorDescription(
        key="last_failed_entity",
        name="Last failed entity",
        icon="mdi:home-alert-outline",
        value_fn=lambda coordinator: _last_failed_entity_value(coordinator),
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
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.incident_store.counts_today()["reloads"],
    ),
    HealixSensorDescription(
        key="blocked_count_today",
        name="Blocked count today",
        icon="mdi:block-helper",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.incident_store.counts_today()["blocked"],
    ),
    HealixSensorDescription(
        key="network_health",
        name="Network health",
        icon="mdi:network-outline",
        value_fn=lambda coordinator: _network_health_value(coordinator),
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
        self._attr_entity_category = description.entity_category

    @property
    def native_value(self) -> Any:
        """Return sensor state."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return sensor attributes."""
        if self.entity_description.key == "last_failed_entity":
            if not self.coordinator.last_failed_entity:
                return None
            return {"full_entity_id": self.coordinator.last_failed_entity}
        if self.entity_description.key == "network_health":
            raw_status = self.coordinator.last_network_status
            if ":" not in raw_status:
                return None
            return {
                "full_status": raw_status,
                "entity_ids": raw_status.split(":", 1)[1].split(","),
            }
        return None


def _last_failed_entity_value(coordinator) -> str:
    """Return a compact display value for the last failed entity."""
    entity_id = coordinator.last_failed_entity
    if not entity_id:
        return "none"

    state = coordinator.hass.states.get(entity_id)
    friendly_name = None
    if state is not None:
        friendly_name = state.attributes.get("friendly_name")

    return _short_entity_name(entity_id, friendly_name)


def _network_health_value(coordinator) -> str:
    """Return a compact display value for network health."""
    status = coordinator.last_network_status
    if status.startswith("network_health_entities_down:"):
        return "down"
    if status.startswith("network_health_entities_unknown:"):
        return "unknown"
    return status


def _short_entity_name(entity_id: str, friendly_name: Any = None) -> str:
    """Return a short friendly name for an entity id."""
    raw_name = friendly_name if isinstance(friendly_name, str) else None
    candidate = raw_name or entity_id.split(".", 1)[-1]
    words = _entity_words(candidate)
    domain = entity_id.split(".", 1)[0]

    if "snapcast" in words and "client" in words:
        return "Snapcast client"
    if "wiz" in words and (domain == "light" or "light" in words):
        return "WiZ light"
    if "tuya" in words and (domain == "switch" or "switch" in words):
        return "Tuya switch"
    if (
        ("google" in words and "tv" in words)
        or "googletv" in words
        or "androidtv" in words
    ):
        return "Google TV"

    cleaned = _format_entity_words(words)
    if not cleaned:
        cleaned = entity_id
    if len(cleaned) <= MAX_VISIBLE_ENTITY_NAME_LENGTH:
        return cleaned
    return f"{cleaned[: MAX_VISIBLE_ENTITY_NAME_LENGTH - 3].rstrip()}..."


def _entity_words(value: str) -> list[str]:
    """Split an entity name into readable words."""
    normalized = value.replace("_", " ").replace("-", " ").replace(".", " ")
    words = []
    for word in normalized.split():
        lowered = word.lower()
        if lowered in {"server"}:
            continue
        if len(lowered) >= 4 and all(char in "0123456789abcdef" for char in lowered):
            continue
        words.append(lowered)
    return words


def _format_entity_words(words: list[str]) -> str:
    """Format cleaned entity words for display."""
    if not words:
        return ""

    display_words: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        if word == "wiz":
            display_words.append("WiZ")
        elif word == "tv":
            display_words.append("TV")
        else:
            display_words.append(word.capitalize())
    return " ".join(display_words)
