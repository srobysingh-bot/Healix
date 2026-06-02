"""Config flow for Healix."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .classifier import HealixClassifier
from .const import (
    BACKGROUND_RECOVERY_INTEGRATIONS,
    CONF_BACKGROUND_INTEGRATIONS,
    CONF_COOLDOWN_PER_CONFIG_ENTRY,
    CONF_DRY_RUN,
    CONF_EXPONENTIAL_BACKOFF,
    CONF_FAILURE_DURATION,
    CONF_IGNORED_INTEGRATIONS,
    CONF_IMPORTANT_AREAS,
    CONF_MAX_RETRIES_PER_DAY,
    CONF_MAX_RETRIES_PER_HOUR,
    CONF_MODE,
    CONF_NETWORK_HEALTH_ENTITIES,
    CONF_NOTIFY_FAILED_SETUP,
    CONF_NOTIFICATION_LEVEL,
    CONF_ON_DEMAND_INTEGRATIONS,
    CONF_PROTECTED_INTEGRATIONS,
    CONF_RECOVERY_WAIT,
    CONF_STARTUP_GRACE_PERIOD,
    DEFAULT_COOLDOWN_PER_CONFIG_ENTRY,
    DEFAULT_FAILURE_DURATION,
    DEFAULT_MAX_RETRIES_PER_DAY,
    DEFAULT_MAX_RETRIES_PER_HOUR,
    DEFAULT_RECOVERY_WAIT,
    DEFAULT_STARTUP_GRACE_PERIOD,
    DOMAIN,
    HealixMode,
    NotificationLevel,
    ON_DEMAND_INTEGRATIONS,
    PROTECTED_INTEGRATIONS,
)
from .policy import HealixPolicyEngine

_OptionsFlowBase = getattr(
    config_entries, "OptionsFlowWithReload", config_entries.OptionsFlow
)


def _clean_csv_list(value: Any) -> list[str]:
    """Return CSV values with blank entries removed."""
    return [
        item.strip()
        for item in cv.ensure_list_csv(value)
        if isinstance(item, str) and item.strip()
    ]


def _default_options() -> dict[str, Any]:
    return {
        CONF_MODE: HealixMode.DRY_RUN.value,
        CONF_DRY_RUN: True,
        CONF_STARTUP_GRACE_PERIOD: DEFAULT_STARTUP_GRACE_PERIOD,
        CONF_FAILURE_DURATION: DEFAULT_FAILURE_DURATION,
        CONF_RECOVERY_WAIT: DEFAULT_RECOVERY_WAIT,
        CONF_COOLDOWN_PER_CONFIG_ENTRY: DEFAULT_COOLDOWN_PER_CONFIG_ENTRY,
        CONF_MAX_RETRIES_PER_HOUR: DEFAULT_MAX_RETRIES_PER_HOUR,
        CONF_MAX_RETRIES_PER_DAY: DEFAULT_MAX_RETRIES_PER_DAY,
        CONF_EXPONENTIAL_BACKOFF: True,
        CONF_NOTIFICATION_LEVEL: NotificationLevel.NORMAL.value,
        CONF_NOTIFY_FAILED_SETUP: True,
        CONF_NETWORK_HEALTH_ENTITIES: [],
        CONF_IMPORTANT_AREAS: [],
        CONF_PROTECTED_INTEGRATIONS: sorted(PROTECTED_INTEGRATIONS),
        CONF_BACKGROUND_INTEGRATIONS: sorted(BACKGROUND_RECOVERY_INTEGRATIONS),
        CONF_ON_DEMAND_INTEGRATIONS: sorted(ON_DEMAND_INTEGRATIONS),
        CONF_IGNORED_INTEGRATIONS: [],
    }


MODE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MODE, default=HealixMode.DRY_RUN.value): vol.In(
            {
                HealixMode.DRY_RUN.value: "Dry run / Observe only",
                HealixMode.SMART.value: "Smart recovery enabled",
            }
        )
    }
)

SAFETY_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_STARTUP_GRACE_PERIOD, default=DEFAULT_STARTUP_GRACE_PERIOD
        ): cv.positive_int,
        vol.Required(
            CONF_COOLDOWN_PER_CONFIG_ENTRY, default=DEFAULT_COOLDOWN_PER_CONFIG_ENTRY
        ): cv.positive_int,
        vol.Required(
            CONF_MAX_RETRIES_PER_HOUR, default=DEFAULT_MAX_RETRIES_PER_HOUR
        ): cv.positive_int,
        vol.Required(
            CONF_MAX_RETRIES_PER_DAY, default=DEFAULT_MAX_RETRIES_PER_DAY
        ): cv.positive_int,
        vol.Required(
            CONF_NOTIFICATION_LEVEL, default=NotificationLevel.NORMAL.value
        ): vol.In([level.value for level in NotificationLevel]),
    }
)


class HealixConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Healix."""

    VERSION = 1

    def __init__(self) -> None:
        self._options = _default_options()
        self._summary: dict[str, list[str]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Welcome step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return await self.async_step_mode()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose operating mode."""
        if user_input is not None:
            mode = user_input[CONF_MODE]
            self._options[CONF_MODE] = mode
            self._options[CONF_DRY_RUN] = mode == HealixMode.DRY_RUN.value
            return await self.async_step_policy_review()
        return self.async_show_form(step_id="mode", data_schema=MODE_SCHEMA)

    async def async_step_policy_review(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show auto-detected policy buckets."""
        if not self._summary:
            policy = HealixPolicyEngine(self._options)
            classifier = HealixClassifier(self.hass, policy)
            await classifier.async_refresh()
            self._summary = classifier.integration_summary()
        if user_input is not None:
            return await self.async_step_safety()
        return self.async_show_form(
            step_id="policy_review",
            data_schema=vol.Schema({}),
            description_placeholders=self._summary_placeholders(),
        )

    async def async_step_safety(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure simple safety settings."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_finish()
        return self.async_show_form(step_id="safety", data_schema=SAFETY_SCHEMA)

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Finish setup."""
        if user_input is not None:
            return self.async_create_entry(
                title="Healix",
                data={},
                options=self._options,
            )
        return self.async_show_form(
            step_id="finish",
            data_schema=vol.Schema({}),
            description_placeholders={
                "mode": "Dry run" if self._options[CONF_DRY_RUN] else "Smart recovery",
                "startup_grace": str(self._options[CONF_STARTUP_GRACE_PERIOD]),
                "cooldown": str(self._options[CONF_COOLDOWN_PER_CONFIG_ENTRY]),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return HealixOptionsFlow()

    def _summary_placeholders(self) -> dict[str, str]:
        return {
            "protected": _format_list(self._summary.get("protected")),
            "background": _format_list(self._summary.get("background")),
            "on_demand": _format_list(self._summary.get("on_demand")),
            "monitor_only": _format_list(self._summary.get("monitor_only")),
        }


class HealixOptionsFlow(_OptionsFlowBase):
    """Handle Healix options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show options menu."""
        if user_input is not None:
            if user_input.get("advanced"):
                return await self.async_step_advanced()
            options = {**self.config_entry.options, **user_input}
            options[CONF_DRY_RUN] = options[CONF_MODE] == HealixMode.DRY_RUN.value
            return self.async_create_entry(data=options)

        current = {**_default_options(), **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=current[CONF_MODE]): vol.In(
                    {
                        HealixMode.DRY_RUN.value: "Dry run / Observe only",
                        HealixMode.SMART.value: "Smart recovery enabled",
                    }
                ),
                vol.Required(
                    CONF_STARTUP_GRACE_PERIOD,
                    default=current[CONF_STARTUP_GRACE_PERIOD],
                ): cv.positive_int,
                vol.Required(
                    CONF_FAILURE_DURATION,
                    default=current[CONF_FAILURE_DURATION],
                ): cv.positive_int,
                vol.Required(
                    CONF_RECOVERY_WAIT,
                    default=current[CONF_RECOVERY_WAIT],
                ): cv.positive_int,
                vol.Required(
                    CONF_COOLDOWN_PER_CONFIG_ENTRY,
                    default=current[CONF_COOLDOWN_PER_CONFIG_ENTRY],
                ): cv.positive_int,
                vol.Required(
                    CONF_MAX_RETRIES_PER_HOUR,
                    default=current[CONF_MAX_RETRIES_PER_HOUR],
                ): cv.positive_int,
                vol.Required(
                    CONF_MAX_RETRIES_PER_DAY,
                    default=current[CONF_MAX_RETRIES_PER_DAY],
                ): cv.positive_int,
                vol.Required(
                    CONF_NOTIFICATION_LEVEL,
                    default=current[CONF_NOTIFICATION_LEVEL],
                ): vol.In([level.value for level in NotificationLevel]),
                vol.Required(
                    CONF_NOTIFY_FAILED_SETUP,
                    default=current[CONF_NOTIFY_FAILED_SETUP],
                ): bool,
                vol.Optional("advanced", default=False): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show advanced settings."""
        current = {**_default_options(), **self.config_entry.options}
        if user_input is not None:
            options = {**current}
            options[CONF_NETWORK_HEALTH_ENTITIES] = _clean_csv_list(
                user_input.get(CONF_NETWORK_HEALTH_ENTITIES, "")
            )
            options[CONF_IMPORTANT_AREAS] = _clean_csv_list(
                user_input.get(CONF_IMPORTANT_AREAS, "")
            )
            options[CONF_PROTECTED_INTEGRATIONS] = _clean_csv_list(
                user_input.get(CONF_PROTECTED_INTEGRATIONS, "")
            )
            options[CONF_BACKGROUND_INTEGRATIONS] = _clean_csv_list(
                user_input.get(CONF_BACKGROUND_INTEGRATIONS, "")
            )
            options[CONF_ON_DEMAND_INTEGRATIONS] = _clean_csv_list(
                user_input.get(CONF_ON_DEMAND_INTEGRATIONS, "")
            )
            options[CONF_IGNORED_INTEGRATIONS] = _clean_csv_list(
                user_input.get(CONF_IGNORED_INTEGRATIONS, "")
            )
            return self.async_create_entry(data=options)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_NETWORK_HEALTH_ENTITIES,
                    default=", ".join(current[CONF_NETWORK_HEALTH_ENTITIES]),
                ): str,
                vol.Optional(
                    CONF_IMPORTANT_AREAS,
                    default=", ".join(current[CONF_IMPORTANT_AREAS]),
                ): str,
                vol.Optional(
                    CONF_PROTECTED_INTEGRATIONS,
                    default=", ".join(current[CONF_PROTECTED_INTEGRATIONS]),
                ): str,
                vol.Optional(
                    CONF_BACKGROUND_INTEGRATIONS,
                    default=", ".join(current[CONF_BACKGROUND_INTEGRATIONS]),
                ): str,
                vol.Optional(
                    CONF_ON_DEMAND_INTEGRATIONS,
                    default=", ".join(current[CONF_ON_DEMAND_INTEGRATIONS]),
                ): str,
                vol.Optional(
                    CONF_IGNORED_INTEGRATIONS,
                    default=", ".join(current[CONF_IGNORED_INTEGRATIONS]),
                ): str,
            }
        )
        return self.async_show_form(step_id="advanced", data_schema=schema)


def _format_list(items: list[str] | None) -> str:
    if not items:
        return "None detected yet"
    return ", ".join(items[:12]) + (" ..." if len(items) > 12 else "")
