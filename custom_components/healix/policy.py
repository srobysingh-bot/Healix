"""Policy engine for Healix."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    BACKGROUND_RECOVERY_INTEGRATIONS,
    CONF_BACKGROUND_INTEGRATIONS,
    CONF_COOLDOWN_PER_CONFIG_ENTRY,
    CONF_DRY_RUN,
    CONF_EXPONENTIAL_BACKOFF,
    CONF_IGNORED_INTEGRATIONS,
    CONF_MAX_RETRIES_PER_DAY,
    CONF_MAX_RETRIES_PER_HOUR,
    CONF_ON_DEMAND_INTEGRATIONS,
    CONF_PROTECTED_INTEGRATIONS,
    DEFAULT_COOLDOWN_PER_CONFIG_ENTRY,
    DEFAULT_MAX_RETRIES_PER_DAY,
    DEFAULT_MAX_RETRIES_PER_HOUR,
    LABEL_BACKGROUND,
    LABEL_IGNORE,
    LABEL_NOTIFY_ONLY,
    LABEL_ON_DEMAND,
    LABEL_PROTECTED,
    MONITOR_ONLY_INTEGRATIONS,
    ON_DEMAND_INTEGRATIONS,
    PolicyMode,
    PROTECTED_INTEGRATIONS,
)


@dataclass(slots=True)
class PolicyDecision:
    """A recovery policy decision."""

    allowed: bool
    mode: PolicyMode
    reason: str
    dry_run: bool = False
    notify: bool = True


class HealixPolicyEngine:
    """Evaluate Healix safety policy."""

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self._last_reload_by_entry: dict[str, float] = {}
        self._attempts_by_entry: dict[str, deque[float]] = defaultdict(deque)

    @property
    def dry_run(self) -> bool:
        """Return whether recovery is disabled."""
        return bool(self.options.get(CONF_DRY_RUN, True))

    def mode_for(
        self,
        *,
        integration_domain: str | None,
        entity_domain: str | None,
        labels: set[str],
        is_important: bool,
        low_importance: bool = False,
        disabled_or_hidden: bool = False,
    ) -> PolicyMode:
        """Return the policy mode for an entity."""
        if LABEL_IGNORE in labels:
            return PolicyMode.IGNORE
        if disabled_or_hidden:
            return PolicyMode.IGNORE
        if low_importance:
            return PolicyMode.MONITOR_ONLY
        if LABEL_PROTECTED in labels:
            return PolicyMode.PROTECTED
        if LABEL_ON_DEMAND in labels:
            return PolicyMode.ON_DEMAND_RECOVERY
        if LABEL_BACKGROUND in labels:
            return PolicyMode.BACKGROUND_RECOVERY
        if LABEL_NOTIFY_ONLY in labels:
            return PolicyMode.NOTIFY_ONLY

        domain = integration_domain or ""
        if domain in set(self.options.get(CONF_IGNORED_INTEGRATIONS, [])):
            return PolicyMode.IGNORE
        if domain in self.protected_integrations:
            return PolicyMode.PROTECTED
        if domain in self.on_demand_integrations or entity_domain in {"remote", "media_player"}:
            return PolicyMode.ON_DEMAND_RECOVERY
        if domain in self.background_integrations:
            return PolicyMode.BACKGROUND_RECOVERY
        if domain in MONITOR_ONLY_INTEGRATIONS:
            return PolicyMode.MONITOR_ONLY
        if is_important:
            return PolicyMode.NOTIFY_ONLY
        return PolicyMode.MONITOR_ONLY

    @property
    def protected_integrations(self) -> set[str]:
        """Return protected integrations."""
        return PROTECTED_INTEGRATIONS | set(
            self.options.get(CONF_PROTECTED_INTEGRATIONS, [])
        )

    @property
    def on_demand_integrations(self) -> set[str]:
        """Return on-demand integrations."""
        return ON_DEMAND_INTEGRATIONS | set(
            self.options.get(CONF_ON_DEMAND_INTEGRATIONS, [])
        )

    @property
    def background_integrations(self) -> set[str]:
        """Return background recovery integrations."""
        return BACKGROUND_RECOVERY_INTEGRATIONS | set(
            self.options.get(CONF_BACKGROUND_INTEGRATIONS, [])
        )

    def evaluate_recovery(
        self,
        *,
        mode: PolicyMode,
        config_entry_id: str | None,
        startup_grace_active: bool,
        network_blocked: bool,
        broad_outage: bool,
        failed_setup: bool,
        manual: bool = False,
        on_demand: bool = False,
    ) -> PolicyDecision:
        """Decide if a reload is allowed."""
        if mode == PolicyMode.IGNORE:
            return PolicyDecision(False, mode, "ignored", notify=False)
        if startup_grace_active and not manual:
            return PolicyDecision(False, mode, "startup_grace_period")
        if network_blocked:
            return PolicyDecision(False, mode, "network_health_gate")
        if broad_outage:
            return PolicyDecision(False, mode, "broad_outage")
        if failed_setup and not manual:
            return PolicyDecision(False, mode, "setup_failure_waiting_for_home_assistant")
        if mode == PolicyMode.PROTECTED and not manual:
            return PolicyDecision(False, mode, "protected_integration")
        if manual:
            if not config_entry_id:
                return PolicyDecision(False, mode, "no_config_entry")
        elif mode == PolicyMode.MONITOR_ONLY:
            return PolicyDecision(False, mode, "monitor_only", notify=False)
        elif mode == PolicyMode.NOTIFY_ONLY:
            return PolicyDecision(False, mode, "notify_only")
        elif mode == PolicyMode.ON_DEMAND_RECOVERY and not on_demand:
            return PolicyDecision(False, mode, "on_demand_only")
        if not config_entry_id:
            return PolicyDecision(False, mode, "no_config_entry")

        retry_reason = self._retry_block_reason(config_entry_id)
        if retry_reason:
            return PolicyDecision(False, mode, retry_reason)

        cooldown_reason = self._cooldown_block_reason(config_entry_id)
        if cooldown_reason and not manual:
            return PolicyDecision(False, mode, cooldown_reason)

        if self.dry_run and not manual:
            return PolicyDecision(True, mode, "dry_run_would_reload", dry_run=True)

        return PolicyDecision(True, mode, "reload_allowed")

    def record_attempt(self, config_entry_id: str) -> None:
        """Record a reload attempt."""
        now = dt_util.utcnow().timestamp()
        self._last_reload_by_entry[config_entry_id] = now
        attempts = self._attempts_by_entry[config_entry_id]
        attempts.append(now)
        self._trim_attempts(attempts, hours=24)

    def _cooldown_block_reason(self, config_entry_id: str) -> str | None:
        last = self._last_reload_by_entry.get(config_entry_id)
        if last is None:
            return None
        cooldown = int(
            self.options.get(
                CONF_COOLDOWN_PER_CONFIG_ENTRY, DEFAULT_COOLDOWN_PER_CONFIG_ENTRY
            )
        )
        if self.options.get(CONF_EXPONENTIAL_BACKOFF, True):
            attempts = len(self._attempts_by_entry.get(config_entry_id, ()))
            cooldown *= max(1, min(4, attempts))
        remaining = cooldown - (dt_util.utcnow().timestamp() - last)
        if remaining > 0:
            return f"cooldown_active_{int(remaining)}s"
        return None

    def _retry_block_reason(self, config_entry_id: str) -> str | None:
        attempts = self._attempts_by_entry[config_entry_id]
        self._trim_attempts(attempts, hours=24)
        now = dt_util.utcnow()
        max_hour = int(
            self.options.get(CONF_MAX_RETRIES_PER_HOUR, DEFAULT_MAX_RETRIES_PER_HOUR)
        )
        max_day = int(
            self.options.get(CONF_MAX_RETRIES_PER_DAY, DEFAULT_MAX_RETRIES_PER_DAY)
        )
        hour_floor = (now - timedelta(hours=1)).timestamp()
        day_floor = (now - timedelta(days=1)).timestamp()
        hour_count = sum(1 for item in attempts if item >= hour_floor)
        day_count = sum(1 for item in attempts if item >= day_floor)
        if hour_count >= max_hour:
            return "retry_limit_hour_reached"
        if day_count >= max_day:
            return "retry_limit_day_reached"
        return None

    @staticmethod
    def _trim_attempts(attempts: deque[float], *, hours: int) -> None:
        floor = (dt_util.utcnow() - timedelta(hours=hours)).timestamp()
        while attempts and attempts[0] < floor:
            attempts.popleft()
