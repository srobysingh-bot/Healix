"""Services for Healix."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    ATTR_COMMAND,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    ATTR_TARGET,
    DOMAIN,
    SERVICE_EXPORT_REPORT,
    SERVICE_MANUAL_RECOVER,
    SERVICE_PAUSE_RECOVERY,
    SERVICE_RESUME_RECOVERY,
    SERVICE_RUN_DIAGNOSIS,
    SERVICE_SAFE_REMOTE_COMMAND,
    SERVICE_SAFE_SERVICE_CALL,
    STATE_UNAVAILABLE_VALUES,
)

_LOGGER = logging.getLogger(__name__)

SAFE_REMOTE_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_COMMAND): vol.Any(str, [str]),
    }
)

SAFE_SERVICE_CALL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DOMAIN): cv.string,
        vol.Required(ATTR_SERVICE): cv.string,
        vol.Optional(ATTR_TARGET, default={}): dict,
        vol.Optional(ATTR_SERVICE_DATA, default={}): dict,
    }
)

MANUAL_RECOVER_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register Healix services."""
    if hass.services.has_service(DOMAIN, SERVICE_SAFE_SERVICE_CALL):
        return

    async def async_safe_remote_command(call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        command = call.data[ATTR_COMMAND]
        await _async_safe_call(
            hass,
            domain="remote",
            service="send_command",
            target={ATTR_ENTITY_ID: entity_id},
            data={ATTR_COMMAND: command},
        )

    async def async_safe_service_call(call: ServiceCall) -> None:
        await _async_safe_call(
            hass,
            domain=call.data[ATTR_DOMAIN],
            service=call.data[ATTR_SERVICE],
            target=call.data.get(ATTR_TARGET) or {},
            data=call.data.get(ATTR_SERVICE_DATA) or {},
        )

    async def async_manual_recover(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        if coordinator is None:
            raise HomeAssistantError("Healix is not loaded")
        entity_id = call.data.get(ATTR_ENTITY_ID)
        config_entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if not entity_id and not config_entry_id:
            raise HomeAssistantError("Provide entity_id or config_entry_id")
        await coordinator.async_manual_recover(
            entity_id=entity_id,
            config_entry_id=config_entry_id,
        )

    async def async_run_diagnosis(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        if coordinator is not None:
            await coordinator.async_run_diagnosis()

    async def async_pause(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        if coordinator is not None:
            await coordinator.async_pause()

    async def async_resume(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        if coordinator is not None:
            await coordinator.async_resume()

    async def async_export_report(call: ServiceCall) -> None:
        coordinator = _coordinator(hass)
        if coordinator is None:
            return
        _LOGGER.info("Healix incident report:\n%s", coordinator.export_report())

    hass.services.async_register(
        DOMAIN,
        SERVICE_SAFE_REMOTE_COMMAND,
        async_safe_remote_command,
        schema=SAFE_REMOTE_COMMAND_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAFE_SERVICE_CALL,
        async_safe_service_call,
        schema=SAFE_SERVICE_CALL_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MANUAL_RECOVER,
        async_manual_recover,
        schema=MANUAL_RECOVER_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_RUN_DIAGNOSIS, async_run_diagnosis)
    hass.services.async_register(DOMAIN, SERVICE_PAUSE_RECOVERY, async_pause)
    hass.services.async_register(DOMAIN, SERVICE_RESUME_RECOVERY, async_resume)
    hass.services.async_register(DOMAIN, SERVICE_EXPORT_REPORT, async_export_report)


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Healix services."""
    for service in (
        SERVICE_SAFE_REMOTE_COMMAND,
        SERVICE_SAFE_SERVICE_CALL,
        SERVICE_MANUAL_RECOVER,
        SERVICE_RUN_DIAGNOSIS,
        SERVICE_PAUSE_RECOVERY,
        SERVICE_RESUME_RECOVERY,
        SERVICE_EXPORT_REPORT,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


async def _async_safe_call(
    hass: HomeAssistant,
    *,
    domain: str,
    service: str,
    target: dict[str, Any],
    data: dict[str, Any],
) -> None:
    coordinator = _coordinator(hass)
    entity_ids = _target_entity_ids(target)
    if coordinator is None or not entity_ids:
        await hass.services.async_call(
            domain, service, data, target=target, blocking=True
        )
        return

    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None or state.state in STATE_UNAVAILABLE_VALUES:
            result = await coordinator.async_process_failure(
                entity_id,
                old_state=None,
                new_state=state.state if state else None,
                on_demand=True,
                manual=False,
            )
            if result is None or not result.success:
                current = hass.states.get(entity_id)
                if current is not None and current.state not in STATE_UNAVAILABLE_VALUES:
                    continue
                raise HomeAssistantError(
                    f"Healix could not recover {entity_id}: "
                    f"{result.result if result else 'not_classified'}"
                )

    await hass.services.async_call(domain, service, data, target=target, blocking=True)


def _target_entity_ids(target: dict[str, Any]) -> list[str]:
    raw = target.get(ATTR_ENTITY_ID)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _coordinator(hass: HomeAssistant) -> Any:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        return None
    return next(iter(entries.values()))
