"""Auto-discovery and importance classification for Healix."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, State, split_entity_id
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_IMPORTANT_AREAS,
    IMPORTANT_ENTITY_DOMAINS,
    LABEL_CRITICAL,
    LOW_IMPORTANCE_SENSOR_HINTS,
    PolicyMode,
)
from .policy import HealixPolicyEngine


@dataclass(slots=True)
class EntityProfile:
    """Healix entity classification profile."""

    entity_id: str
    entity_domain: str
    integration_domain: str | None
    config_entry_id: str | None
    device_id: str | None
    area_id: str | None
    labels: set[str] = field(default_factory=set)
    disabled: bool = False
    hidden: bool = False
    diagnostic: bool = False
    important: bool = False
    low_importance: bool = False
    reason: str = "auto"
    policy_mode: PolicyMode = PolicyMode.MONITOR_ONLY


class HealixClassifier:
    """Classify entities, devices, integrations, areas, and labels."""

    def __init__(self, hass: HomeAssistant, policy: HealixPolicyEngine) -> None:
        self.hass = hass
        self.policy = policy
        self.entities: dict[str, EntityProfile] = {}
        self.by_config_entry: dict[str, set[str]] = {}
        self.by_integration: dict[str, set[str]] = {}

    async def async_refresh(self) -> None:
        """Refresh all classification data."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        important_areas = set(self.policy.options.get(CONF_IMPORTANT_AREAS, []))

        entities: dict[str, EntityProfile] = {}
        by_entry: dict[str, set[str]] = {}
        by_integration: dict[str, set[str]] = {}

        for state in self.hass.states.async_all():
            if state.domain in {"automation", "script"}:
                continue
            entry = entity_registry.async_get(state.entity_id)
            profile = self._build_profile(
                state,
                entry,
                device_registry,
                area_registry,
                important_areas,
            )
            profile.policy_mode = self.policy.mode_for(
                integration_domain=profile.integration_domain,
                entity_domain=profile.entity_domain,
                labels=profile.labels,
                is_important=profile.important,
                low_importance=profile.low_importance
                and LABEL_CRITICAL not in profile.labels,
                disabled_or_hidden=(profile.disabled or profile.hidden)
                and LABEL_CRITICAL not in profile.labels,
            )
            entities[state.entity_id] = profile
            if profile.config_entry_id:
                by_entry.setdefault(profile.config_entry_id, set()).add(state.entity_id)
            if profile.integration_domain:
                by_integration.setdefault(profile.integration_domain, set()).add(
                    state.entity_id
                )

        self.entities = entities
        self.by_config_entry = by_entry
        self.by_integration = by_integration

    def profile_for(self, entity_id: str) -> EntityProfile | None:
        """Return a profile for an entity."""
        return self.entities.get(entity_id)

    def affected_entities(self, config_entry_id: str | None) -> list[str]:
        """Return known entities for a config entry."""
        if not config_entry_id:
            return []
        return sorted(self.by_config_entry.get(config_entry_id, set()))

    def integration_summary(self) -> dict[str, list[str]]:
        """Return policy buckets for setup review."""
        buckets = {
            "protected": [],
            "background": [],
            "on_demand": [],
            "monitor_only": [],
            "notify_only": [],
            "ignored": [],
        }
        for domain, entity_ids in sorted(self.by_integration.items()):
            modes = {
                self.entities[entity_id].policy_mode
                for entity_id in entity_ids
                if entity_id in self.entities
            }
            if PolicyMode.PROTECTED in modes:
                buckets["protected"].append(domain)
            elif PolicyMode.BACKGROUND_RECOVERY in modes:
                buckets["background"].append(domain)
            elif PolicyMode.ON_DEMAND_RECOVERY in modes:
                buckets["on_demand"].append(domain)
            elif PolicyMode.NOTIFY_ONLY in modes:
                buckets["notify_only"].append(domain)
            elif PolicyMode.IGNORE in modes:
                buckets["ignored"].append(domain)
            else:
                buckets["monitor_only"].append(domain)
        return buckets

    def _build_profile(
        self,
        state: State,
        entry: er.RegistryEntry | None,
        device_registry: dr.DeviceRegistry,
        area_registry: ar.AreaRegistry,
        important_areas: set[str],
    ) -> EntityProfile:
        entity_domain = split_entity_id(state.entity_id)[0]
        labels = set(getattr(entry, "labels", set()) or set()) if entry else set()
        device_id = entry.device_id if entry else None
        area_id = entry.area_id if entry else None
        if not area_id and device_id:
            device = device_registry.async_get(device_id)
            area_id = device.area_id if device else None

        integration_domain = None
        config_entry_id = None
        if entry:
            platform = getattr(entry, "platform", None)
            integration_domain = platform or None
            config_entry_id = getattr(entry, "config_entry_id", None)
        if not integration_domain and device_id:
            device = device_registry.async_get(device_id)
            if device and device.config_entries:
                config_entry_id = next(iter(device.config_entries), None)
                integration_domain = self._domain_from_config_entry(config_entry_id)

        hidden = bool(getattr(entry, "hidden_by", None)) if entry else False
        disabled = bool(getattr(entry, "disabled_by", None)) if entry else False
        entity_category = getattr(entry, "entity_category", None) if entry else None
        diagnostic = str(entity_category) == "diagnostic"
        low_importance = self._is_low_importance(state, diagnostic)

        important = False
        reason = "auto"
        if LABEL_CRITICAL in labels:
            important = True
            reason = "label_critical"
        elif disabled or hidden or low_importance:
            important = False
            reason = "disabled_hidden_or_diagnostic"
        elif entity_domain in IMPORTANT_ENTITY_DOMAINS:
            important = True
            reason = "critical_domain"
        elif area_id and area_id in important_areas:
            important = True
            reason = "important_area"
        elif self._is_referenced_by_automation_or_script(state.entity_id):
            important = True
            reason = "referenced_by_automation_or_script"

        if area_id and not area_registry.async_get_area(area_id):
            area_id = None

        return EntityProfile(
            entity_id=state.entity_id,
            entity_domain=entity_domain,
            integration_domain=integration_domain,
            config_entry_id=config_entry_id,
            device_id=device_id,
            area_id=area_id,
            labels=labels,
            disabled=disabled,
            hidden=hidden,
            diagnostic=diagnostic,
            important=important,
            low_importance=low_importance,
            reason=reason,
        )

    def _domain_from_config_entry(self, config_entry_id: str | None) -> str | None:
        if not config_entry_id:
            return None
        entry = self.hass.config_entries.async_get_entry(config_entry_id)
        return entry.domain if entry else None

    def _is_referenced_by_automation_or_script(self, entity_id: str) -> bool:
        needle = entity_id.lower()
        for state in self.hass.states.async_all(["automation", "script"]):
            attrs: dict[str, Any] = dict(state.attributes)
            if needle in str(attrs).lower():
                return True
        return False

    @staticmethod
    def _is_low_importance(state: State, diagnostic: bool) -> bool:
        if diagnostic:
            return True
        name = f"{state.entity_id} {state.name}".lower()
        device_class = str(state.attributes.get("device_class", "")).lower()
        entity_category = str(state.attributes.get("entity_category", "")).lower()
        haystack = f"{name} {device_class} {entity_category}"
        return any(hint in haystack for hint in LOW_IMPORTANCE_SENSOR_HINTS)
