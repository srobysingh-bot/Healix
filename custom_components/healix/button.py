"""Healix dashboard buttons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HealixEntity


@dataclass(frozen=True, kw_only=True)
class HealixButtonDescription(ButtonEntityDescription):
    """Healix button description."""

    action: Callable[[object], Awaitable[None]]


async def _run_diagnosis(coordinator) -> None:
    await coordinator.async_run_diagnosis()


async def _pause(coordinator) -> None:
    await coordinator.async_pause()


async def _resume(coordinator) -> None:
    await coordinator.async_resume()


async def _export(coordinator) -> None:
    from homeassistant.components import persistent_notification

    persistent_notification.async_create(
        coordinator.hass,
        f"Latest Healix report is available in the Home Assistant log.\n\n{coordinator.export_report()[:1200]}",
        title="Healix report",
        notification_id="healix_export_report",
    )


BUTTONS = (
    HealixButtonDescription(
        key="run_diagnosis",
        name="Run diagnosis",
        icon="mdi:stethoscope",
        action=_run_diagnosis,
    ),
    HealixButtonDescription(
        key="pause_recovery",
        name="Pause recovery",
        icon="mdi:pause-circle-outline",
        action=_pause,
    ),
    HealixButtonDescription(
        key="resume_recovery",
        name="Resume recovery",
        icon="mdi:play-circle-outline",
        action=_resume,
    ),
    HealixButtonDescription(
        key="export_report",
        name="Export report",
        icon="mdi:file-export-outline",
        action=_export,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healix buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(HealixButton(coordinator, description) for description in BUTTONS)


class HealixButton(HealixEntity, ButtonEntity):
    """A Healix dashboard button."""

    entity_description: HealixButtonDescription

    def __init__(self, coordinator, description: HealixButtonDescription) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description
        self._attr_icon = description.icon

    async def async_press(self) -> None:
        """Handle button press."""
        await self.entity_description.action(self.coordinator)
