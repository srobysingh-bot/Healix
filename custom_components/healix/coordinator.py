"""Runtime coordinator for Healix."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .classifier import EntityProfile, HealixClassifier
from .const import (
    CONF_FAILURE_DURATION,
    CONF_NOTIFY_FAILED_SETUP,
    CONF_RECOVERY_WAIT,
    CONF_NOTIFICATION_LEVEL,
    CONF_STARTUP_GRACE_PERIOD,
    DEFAULT_FAILURE_DURATION,
    DEFAULT_RECOVERY_WAIT,
    DEFAULT_STARTUP_GRACE_PERIOD,
    DOMAIN,
    NotificationLevel,
    NAME,
    PolicyMode,
    STATE_UNAVAILABLE_VALUES,
)
from .diagnostics import Diagnosis, HealixDiagnostics
from .incident_store import HealixIncidentStore
from .policy import HealixPolicyEngine
from .recovery import HealixRecoveryManager, RecoveryResult
from .repairs import async_create_failed_setup_issue, async_create_retry_limit_issue

_LOGGER = logging.getLogger(__name__)


class HealixCoordinator:
    """Central Healix runtime manager."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.started_at = dt_util.utcnow()
        self.paused = False
        self.recovery_active = False
        self.last_failed_entity: str | None = None
        self.last_recovery_result: str | None = None
        self.last_network_status = "unknown"
        self.network_outage = False
        self._listeners: list[Callable[[], None]] = []
        self._failure_tasks: dict[str, asyncio.Task[Any]] = {}
        self._failure_started: dict[str, datetime] = {}
        self._notified_network_status: str | None = None
        self._setup_scan_task: asyncio.Task[Any] | None = None
        self._notified_failed_setups: set[str] = set()
        self._active_failed_setups: dict[str, str] = {}
        self._state_unsub: Callable[[], None] | None = None
        self._watched_entity_ids: set[str] = set()

        self.policy = HealixPolicyEngine(self.options)
        self.classifier = HealixClassifier(hass, self.policy)
        self.diagnostics = HealixDiagnostics(hass, self.options)
        self.recovery = HealixRecoveryManager(
            hass,
            int(self.options.get(CONF_RECOVERY_WAIT, DEFAULT_RECOVERY_WAIT)),
        )
        self.incident_store = HealixIncidentStore(hass)

    @property
    def options(self) -> dict[str, Any]:
        """Merged entry options."""
        return {**self.entry.data, **self.entry.options}

    @property
    def startup_grace_active(self) -> bool:
        """Return whether startup grace period is active."""
        grace = int(
            self.options.get(CONF_STARTUP_GRACE_PERIOD, DEFAULT_STARTUP_GRACE_PERIOD)
        )
        return self.ha_uptime_seconds < grace

    @property
    def ha_uptime_seconds(self) -> int:
        """Return Healix-observed HA uptime in seconds."""
        return int((dt_util.utcnow() - self.started_at).total_seconds())

    @property
    def notification_level(self) -> NotificationLevel:
        """Return configured notification level."""
        raw = self.options.get(CONF_NOTIFICATION_LEVEL, NotificationLevel.NORMAL.value)
        try:
            return NotificationLevel(raw)
        except ValueError:
            return NotificationLevel.NORMAL

    @property
    def notify_failed_setup(self) -> bool:
        """Return whether failed setup notifications are enabled."""
        return bool(self.options.get(CONF_NOTIFY_FAILED_SETUP, True))

    @property
    def active_issue_count(self) -> int:
        """Return current active issues, not incident volume."""
        failed_entities = {
            entity_id
            for entity_id, profile in self.classifier.entities.items()
            if (
                profile.policy_mode != PolicyMode.IGNORE
                and
                (state := self.hass.states.get(entity_id)) is not None
                and state.state in STATE_UNAVAILABLE_VALUES
            )
        }
        failed_setups = self._current_failed_setup_entries()
        return len(failed_entities) + len(failed_setups)

    async def async_setup(self) -> None:
        """Set up coordinator listeners."""
        await self.incident_store.async_load()
        await self.async_refresh_classification()
        self._setup_scan_task = self.hass.async_create_task(
            self._async_failed_setup_loop()
        )
        _LOGGER.debug(
            "Healix coordinator started with %s profiles",
            len(self.classifier.entities),
        )

    async def async_unload(self) -> None:
        """Unload coordinator."""
        for task in self._failure_tasks.values():
            task.cancel()
        if self._failure_tasks:
            await asyncio.gather(*self._failure_tasks.values(), return_exceptions=True)
        self._failure_tasks.clear()
        if self._setup_scan_task:
            self._setup_scan_task.cancel()
            await asyncio.gather(self._setup_scan_task, return_exceptions=True)
            self._setup_scan_task = None
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        self._watched_entity_ids.clear()
        self._listeners.clear()

    async def async_refresh_classification(self) -> None:
        """Refresh discovery and re-register watched state listeners."""
        await self.classifier.async_refresh()
        watched = {
            entity_id
            for entity_id, profile in self.classifier.entities.items()
            if profile.policy_mode != PolicyMode.IGNORE
        }
        if watched == self._watched_entity_ids:
            return
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        self._watched_entity_ids = watched
        if watched:
            self._state_unsub = async_track_state_change_event(
                self.hass,
                sorted(watched),
                self._async_state_changed,
            )
        _LOGGER.debug("Healix now watches %s entities", len(watched))

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register a dashboard entity update listener."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def async_update_listeners(self) -> None:
        """Notify dashboard entities."""
        for listener in list(self._listeners):
            listener()

    @callback
    def _async_state_changed(self, event: Event[Any]) -> None:
        """Handle entity state changes."""
        data = event.data
        entity_id = data.get("entity_id")
        if not entity_id or entity_id.startswith(f"{DOMAIN}."):
            return
        new_state: State | None = data.get("new_state")
        old_state: State | None = data.get("old_state")
        if new_state is None:
            return
        if entity_id not in self.classifier.entities:
            self.hass.async_create_task(self.async_refresh_classification())
        if new_state.state in STATE_UNAVAILABLE_VALUES:
            self._schedule_failure_check(entity_id, old_state, new_state)
            return
        task = self._failure_tasks.pop(entity_id, None)
        if task:
            task.cancel()
        self._failure_started.pop(entity_id, None)

    @callback
    def _schedule_failure_check(
        self, entity_id: str, old_state: State | None, new_state: State
    ) -> None:
        if entity_id in self._failure_tasks:
            return
        self._failure_started[entity_id] = dt_util.utcnow()
        task = self.hass.async_create_task(
            self._async_handle_persistent_failure(entity_id, old_state, new_state)
        )
        self._failure_tasks[entity_id] = task

    async def _async_handle_persistent_failure(
        self, entity_id: str, old_state: State | None, new_state: State
    ) -> None:
        delay = int(self.options.get(CONF_FAILURE_DURATION, DEFAULT_FAILURE_DURATION))
        try:
            await asyncio.sleep(delay)
            state = self.hass.states.get(entity_id)
            if state is None or state.state not in STATE_UNAVAILABLE_VALUES:
                return
            await self.async_process_failure(
                entity_id,
                old_state=old_state.state if old_state else None,
                new_state=state.state,
                on_demand=False,
                manual=False,
            )
        finally:
            self._failure_tasks.pop(entity_id, None)

    async def async_process_failure(
        self,
        entity_id: str,
        *,
        old_state: str | None = None,
        new_state: str | None = None,
        on_demand: bool = False,
        manual: bool = False,
    ) -> RecoveryResult | None:
        """Diagnose, decide, recover, notify, and record an entity failure."""
        await self.async_refresh_classification()
        profile = self.classifier.profile_for(entity_id)
        if profile is None:
            _LOGGER.debug("Skipping %s because it has no Healix profile", entity_id)
            return None

        self.last_failed_entity = entity_id
        diagnosis = self.diagnostics.diagnose(profile.config_entry_id)
        self.last_network_status = diagnosis.network_status
        self.network_outage = not diagnosis.network_healthy or diagnosis.broad_outage

        if self.paused and not manual:
            decision_reason = "recovery_paused"
            await self._record_and_notify(
                profile,
                diagnosis,
                decision=decision_reason,
                old_state=old_state,
                new_state=new_state,
                reload_attempted=False,
                blocked_reason=decision_reason,
                recovery_result="blocked",
            )
            self.async_update_listeners()
            return RecoveryResult(False, False, "recovery_paused")

        decision = self.policy.evaluate_recovery(
            mode=profile.policy_mode,
            config_entry_id=profile.config_entry_id,
            startup_grace_active=self.startup_grace_active,
            network_blocked=not diagnosis.network_healthy,
            broad_outage=diagnosis.broad_outage,
            failed_setup=diagnosis.failed_setup,
            manual=manual,
            on_demand=on_demand,
        )

        if diagnosis.failed_setup:
            await async_create_failed_setup_issue(
                self.hass,
                config_entry_id=profile.config_entry_id,
                integration_domain=profile.integration_domain,
            )

        if not decision.allowed:
            if decision.reason.startswith("retry_limit"):
                await async_create_retry_limit_issue(
                    self.hass,
                    config_entry_id=profile.config_entry_id,
                    integration_domain=profile.integration_domain,
                    reason=decision.reason,
                )
            await self._record_and_notify(
                profile,
                diagnosis,
                decision=profile.policy_mode.value,
                old_state=old_state,
                new_state=new_state,
                reload_attempted=False,
                blocked_reason=decision.reason,
                recovery_result="blocked",
                notify=decision.notify,
            )
            self.last_recovery_result = f"blocked:{decision.reason}"
            self.async_update_listeners()
            return RecoveryResult(False, False, decision.reason)

        if decision.dry_run:
            await self._record_and_notify(
                profile,
                diagnosis,
                decision=profile.policy_mode.value,
                old_state=old_state,
                new_state=new_state,
                reload_attempted=False,
                recovery_result="would_recover",
                dry_run=True,
            )
            self.last_recovery_result = "dry_run_would_recover"
            self.async_update_listeners()
            return RecoveryResult(False, False, "dry_run_would_recover")

        if not profile.config_entry_id:
            return RecoveryResult(False, False, "no_config_entry")

        self.recovery_active = True
        self.async_update_listeners()
        affected = self._failed_entities_for_config_entry(
            profile.config_entry_id,
            include_entity_id=entity_id,
        )
        self.policy.record_attempt(profile.config_entry_id)
        result = await self.recovery.async_reload_and_verify(
            config_entry_id=profile.config_entry_id,
            entity_ids=affected or [entity_id],
        )
        self.recovery_active = False
        self.last_recovery_result = result.result
        await self._record_and_notify(
            profile,
            diagnosis,
            decision=profile.policy_mode.value,
            old_state=old_state,
            new_state=new_state,
            reload_attempted=result.attempted,
            recovery_result=result.result,
            recovered_after_seconds=result.recovered_after_seconds,
            blocked_reason=result.error,
        )
        self.async_update_listeners()
        return result

    async def async_manual_recover(
        self, *, entity_id: str | None = None, config_entry_id: str | None = None
    ) -> RecoveryResult | None:
        """Run manual recovery for an entity or config entry."""
        if entity_id:
            state = self.hass.states.get(entity_id)
            return await self.async_process_failure(
                entity_id,
                old_state=None,
                new_state=state.state if state else None,
                manual=True,
            )
        if config_entry_id:
            await self.async_refresh_classification()
            entity_ids = self._failed_entities_for_config_entry(config_entry_id)
            all_entities = self.classifier.affected_entities(config_entry_id)
            diagnosis = self.diagnostics.diagnose(config_entry_id)
            config_entry = self.hass.config_entries.async_get_entry(config_entry_id)
            self.policy.record_attempt(config_entry_id)
            result = await self.recovery.async_reload_and_verify(
                config_entry_id=config_entry_id,
                entity_ids=entity_ids,
            )
            await self.incident_store.async_add(
                integration_domain=config_entry.domain if config_entry else None,
                config_entry_id=config_entry_id,
                ha_uptime_seconds=self.ha_uptime_seconds,
                network_health=diagnosis.network_status,
                affected_entities=all_entities,
                decision="manual_recover",
                reload_attempted=result.attempted,
                blocked_reason=result.error,
                recovery_result=result.result,
                recovered_after_seconds=result.recovered_after_seconds,
                details={
                    "diagnosis": diagnosis.reason,
                    "target_failed_entities": entity_ids,
                    "title": config_entry.title if config_entry else None,
                },
            )
            self.last_recovery_result = result.result
            await self._async_notify_config_entry_manual(
                config_entry_id=config_entry_id,
                integration_domain=config_entry.domain if config_entry else None,
                title=config_entry.title if config_entry else config_entry_id,
                diagnosis=diagnosis,
                result=result,
                target_failed_entities=entity_ids,
            )
            self.async_update_listeners()
            return result
        return None

    async def async_run_diagnosis(self) -> None:
        """Refresh discovery and diagnostics."""
        await self.async_refresh_classification()
        diagnosis = self.diagnostics.diagnose()
        self.last_network_status = diagnosis.network_status
        self.network_outage = not diagnosis.network_healthy or diagnosis.broad_outage
        await self.incident_store.async_add(
            network_health=diagnosis.network_status,
            ha_uptime_seconds=self.ha_uptime_seconds,
            decision="manual_diagnosis",
            recovery_result=diagnosis.reason,
            details={
                "affected_unavailable_count": diagnosis.affected_unavailable_count,
                "affected_config_entries": diagnosis.affected_config_entries,
            },
        )
        self.last_recovery_result = diagnosis.reason
        self.async_update_listeners()

    async def async_pause(self) -> None:
        """Pause automatic recovery."""
        self.paused = True
        self.last_recovery_result = "paused"
        self.async_update_listeners()

    async def async_resume(self) -> None:
        """Resume automatic recovery."""
        self.paused = False
        self.last_recovery_result = "resumed"
        self.async_update_listeners()

    def export_report(self) -> str:
        """Return incident report."""
        return self.incident_store.export_report()

    def _failed_entities_for_config_entry(
        self,
        config_entry_id: str | None,
        *,
        include_entity_id: str | None = None,
    ) -> list[str]:
        """Return currently failed entities in a config entry."""
        if not config_entry_id:
            return [include_entity_id] if include_entity_id else []
        failed: set[str] = set()
        for entity_id in self.classifier.affected_entities(config_entry_id):
            state = self.hass.states.get(entity_id)
            if state is not None and state.state in STATE_UNAVAILABLE_VALUES:
                failed.add(entity_id)
        if include_entity_id:
            failed.add(include_entity_id)
        return sorted(failed)

    async def _async_failed_setup_loop(self) -> None:
        """Periodically detect setup failures separately from entity failures."""
        while True:
            await self._async_scan_failed_setups()
            await asyncio.sleep(300)

    async def _async_scan_failed_setups(self) -> None:
        failed_entries = self._current_failed_setup_entries()
        self._active_failed_setups = {
            entry.entry_id: entry.title for entry in failed_entries
        }

        for config_entry in failed_entries:
            if config_entry.entry_id in self._notified_failed_setups:
                continue
            self._notified_failed_setups.add(config_entry.entry_id)
            await async_create_failed_setup_issue(
                self.hass,
                config_entry_id=config_entry.entry_id,
                integration_domain=config_entry.domain,
            )
            await self.incident_store.async_add(
                integration_domain=config_entry.domain,
                config_entry_id=config_entry.entry_id,
                ha_uptime_seconds=self.ha_uptime_seconds,
                decision="failed_setup_detected",
                reload_attempted=False,
                blocked_reason="setup_failure_waiting_for_home_assistant",
                recovery_result=str(config_entry.state),
                details={"title": config_entry.title},
            )

        await self._async_notify_failed_setup_summary(failed_entries)
        if failed_entries:
            self.last_recovery_result = "failed_setup_detected"
        self.async_update_listeners()

    def _current_failed_setup_entries(self) -> list[ConfigEntry]:
        """Return config entries currently in failed setup states."""
        failed_states = {
            ConfigEntryState.SETUP_ERROR,
            ConfigEntryState.SETUP_RETRY,
            getattr(ConfigEntryState, "MIGRATION_ERROR", object()),
        }
        return [
            config_entry
            for config_entry in self.hass.config_entries.async_entries()
            if config_entry.domain != DOMAIN and config_entry.state in failed_states
        ]

    async def _async_notify_failed_setup_summary(
        self, failed_entries: list[ConfigEntry]
    ) -> None:
        """Update failed setup notification according to verbosity."""
        summary_notification_id = f"{DOMAIN}_failed_setup_summary"
        if not self.notify_failed_setup or not failed_entries:
            persistent_notification.async_dismiss(
                self.hass, notification_id=summary_notification_id
            )
            return

        titles = [entry.title for entry in failed_entries]
        preview = ", ".join(titles[:3])
        if len(titles) > 3:
            preview = f"{preview}..."
        persistent_notification.async_create(
            self.hass,
            (
                f"Healix detected {len(titles)} setup failures: {preview}\n\n"
                "Action: Home Assistant retry is allowed to continue. Healix will not "
                "repeatedly reload these integrations."
            ),
            title=f"{NAME}: setup failures",
            notification_id=summary_notification_id,
        )

        if self.notification_level != NotificationLevel.VERBOSE:
            return

        for config_entry in failed_entries:
            if config_entry.entry_id not in self._notified_failed_setups:
                continue
            persistent_notification.async_create(
                self.hass,
                (
                    f"Healix detected setup failure for {config_entry.title}.\n\n"
                    "Action: Home Assistant retry is allowed to continue. Healix will "
                    "not repeatedly reload this integration."
                ),
                title=f"{NAME}: setup failure",
                notification_id=f"{DOMAIN}_failed_setup_{config_entry.entry_id}",
            )

    async def _record_and_notify(
        self,
        profile: EntityProfile,
        diagnosis: Diagnosis,
        *,
        decision: str,
        old_state: str | None,
        new_state: str | None,
        reload_attempted: bool,
        recovery_result: str,
        blocked_reason: str | None = None,
        recovered_after_seconds: float | None = None,
        dry_run: bool = False,
        notify: bool = True,
    ) -> None:
        affected = self.classifier.affected_entities(profile.config_entry_id)
        failure_started = self._failure_started.get(profile.entity_id)
        await self.incident_store.async_add(
            entity_id=profile.entity_id,
            integration_domain=profile.integration_domain,
            config_entry_id=profile.config_entry_id,
            device_id=profile.device_id,
            area_id=profile.area_id,
            old_state=old_state,
            new_state=new_state,
            failure_start_time=failure_started.isoformat() if failure_started else None,
            ha_uptime_seconds=self.ha_uptime_seconds,
            network_health=diagnosis.network_status,
            affected_entities=affected,
            decision=decision,
            reload_attempted=reload_attempted,
            blocked_reason=blocked_reason,
            recovery_result=recovery_result,
            recovered_after_seconds=recovered_after_seconds,
            dry_run=dry_run,
            details={
                "diagnosis": diagnosis.reason,
                "policy_reason": profile.reason,
                "policy_mode": profile.policy_mode.value,
            },
        )
        if self._should_notify(
            notify=notify,
            reload_attempted=reload_attempted,
            recovery_result=recovery_result,
            blocked_reason=blocked_reason,
            dry_run=dry_run,
            diagnosis=diagnosis,
        ):
            await self._async_notify(
                profile,
                diagnosis,
                reload_attempted=reload_attempted,
                recovery_result=recovery_result,
                blocked_reason=blocked_reason,
                recovered_after_seconds=recovered_after_seconds,
                dry_run=dry_run,
            )

    def _should_notify(
        self,
        *,
        notify: bool,
        reload_attempted: bool,
        recovery_result: str,
        blocked_reason: str | None,
        dry_run: bool,
        diagnosis: Diagnosis,
    ) -> bool:
        """Apply notification_level."""
        level = self.notification_level
        if level == NotificationLevel.VERBOSE:
            return True
        if not notify:
            return False
        if level == NotificationLevel.QUIET:
            return (
                reload_attempted
                or recovery_result not in {"blocked", "would_recover"}
                or (blocked_reason or "").startswith("retry_limit")
                or blocked_reason in {"network_health_gate", "broad_outage"}
                or diagnosis.reason in {"network_issue", "failed_setup"}
            )
        return True

    async def _async_notify(
        self,
        profile: EntityProfile,
        diagnosis: Diagnosis,
        *,
        reload_attempted: bool,
        recovery_result: str,
        blocked_reason: str | None,
        recovered_after_seconds: float | None,
        dry_run: bool,
    ) -> None:
        if diagnosis.reason == "network_issue":
            if self._notified_network_status == diagnosis.network_status:
                return
            self._notified_network_status = diagnosis.network_status

        title = f"{NAME}: {profile.entity_id}"
        if dry_run:
            message = (
                f"Healix dry run: {profile.entity_id} stayed unavailable. "
                f"It would reload {profile.integration_domain or 'the owning integration'} "
                f"after diagnosis. Reason: {diagnosis.reason}."
            )
        elif blocked_reason:
            message = (
                f"Healix blocked recovery for {profile.entity_id}.\n\n"
                f"Reason: {blocked_reason}.\n"
                f"Diagnosis: {diagnosis.reason}.\n"
                "Action: notify only."
            )
        elif reload_attempted and recovery_result == "recovered":
            message = (
                f"Healix recovered {profile.entity_id}.\n\n"
                "Reason: entity stayed unavailable, network was healthy, and safety checks passed.\n"
                "Action: reloaded one owning config entry.\n"
                f"Result: recovered after {recovered_after_seconds} seconds."
            )
        else:
            message = (
                f"Healix recovery result for {profile.entity_id}: {recovery_result}.\n\n"
                f"Diagnosis: {diagnosis.reason}."
            )

        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=f"{DOMAIN}_{profile.entity_id.replace('.', '_')}",
        )

    async def _async_notify_config_entry_manual(
        self,
        *,
        config_entry_id: str,
        integration_domain: str | None,
        title: str,
        diagnosis: Diagnosis,
        result: RecoveryResult,
        target_failed_entities: list[str],
    ) -> None:
        """Notify about manual config-entry recovery."""
        if self.notification_level == NotificationLevel.QUIET and result.success:
            return
        persistent_notification.async_create(
            self.hass,
            (
                f"Healix manual recovery ran for {title}.\n\n"
                f"Integration: {integration_domain or 'unknown'}\n"
                f"Config entry: {config_entry_id}\n"
                f"Diagnosis: {diagnosis.reason}\n"
                f"Failed entities checked: {', '.join(target_failed_entities) or 'none'}\n"
                f"Result: {result.result}"
            ),
            title=f"{NAME}: manual recovery",
            notification_id=f"{DOMAIN}_manual_{config_entry_id}",
        )
