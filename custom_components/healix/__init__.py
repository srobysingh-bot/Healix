"""Healix custom integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import HealixCoordinator
from .services import async_register_services, async_unregister_services

HealixConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: HealixConfigEntry) -> bool:
    """Set up Healix from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = HealixCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HealixConfigEntry) -> bool:
    """Unload Healix."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_unload()
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        async_unregister_services(hass)
        hass.data.pop(DOMAIN, None)
    return unload_ok
