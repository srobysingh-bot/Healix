"""Repair issue helpers for Healix."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


async def async_create_retry_limit_issue(
    hass: HomeAssistant,
    *,
    config_entry_id: str | None,
    integration_domain: str | None,
    reason: str,
) -> None:
    """Create or update a repair issue when auto recovery is exhausted."""
    issue_id = f"retry_limit_{config_entry_id or integration_domain or 'unknown'}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="retry_limit_reached",
        translation_placeholders={
            "integration": integration_domain or "unknown",
            "reason": reason,
        },
    )


async def async_create_failed_setup_issue(
    hass: HomeAssistant,
    *,
    config_entry_id: str | None,
    integration_domain: str | None,
) -> None:
    """Create a repair issue for persistent setup failures."""
    issue_id = f"failed_setup_{config_entry_id or integration_domain or 'unknown'}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="failed_setup",
        translation_placeholders={
            "integration": integration_domain or "unknown",
        },
    )
