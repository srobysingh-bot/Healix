"""Constants for the Healix integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "healix"
NAME: Final = "Healix"
TAGLINE: Final = "Smart self-healing for Home Assistant."

PLATFORMS: Final = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

CONF_MODE: Final = "mode"
CONF_DRY_RUN: Final = "dry_run"
CONF_STARTUP_GRACE_PERIOD: Final = "startup_grace_period"
CONF_FAILURE_DURATION: Final = "failure_duration"
CONF_RECOVERY_WAIT: Final = "recovery_wait"
CONF_COOLDOWN_PER_CONFIG_ENTRY: Final = "cooldown_per_config_entry"
CONF_MAX_RETRIES_PER_HOUR: Final = "max_retries_per_hour"
CONF_MAX_RETRIES_PER_DAY: Final = "max_retries_per_day"
CONF_EXPONENTIAL_BACKOFF: Final = "exponential_backoff"
CONF_NETWORK_HEALTH_ENTITIES: Final = "network_health_entities"
CONF_NOTIFY_MONITOR_ONLY: Final = "notify_monitor_only"
CONF_NOTIFY_FAILED_SETUP: Final = "notify_failed_setup"
CONF_NOTIFICATION_LEVEL: Final = "notification_level"
CONF_ADVANCED: Final = "advanced"
CONF_IMPORTANT_AREAS: Final = "important_areas"
CONF_PROTECTED_INTEGRATIONS: Final = "protected_integrations"
CONF_BACKGROUND_INTEGRATIONS: Final = "background_integrations"
CONF_ON_DEMAND_INTEGRATIONS: Final = "on_demand_integrations"
CONF_IGNORED_INTEGRATIONS: Final = "ignored_integrations"

DEFAULT_STARTUP_GRACE_PERIOD: Final = 600
DEFAULT_FAILURE_DURATION: Final = 180
DEFAULT_RECOVERY_WAIT: Final = 60
DEFAULT_COOLDOWN_PER_CONFIG_ENTRY: Final = 900
DEFAULT_MAX_RETRIES_PER_HOUR: Final = 2
DEFAULT_MAX_RETRIES_PER_DAY: Final = 8
DEFAULT_HISTORY_LIMIT: Final = 200

STATE_UNAVAILABLE_VALUES: Final = {"unavailable", "unknown"}

LABEL_CRITICAL: Final = "healix_critical"
LABEL_IGNORE: Final = "healix_ignore"
LABEL_PROTECTED: Final = "healix_protected"
LABEL_ON_DEMAND: Final = "healix_on_demand"
LABEL_BACKGROUND: Final = "healix_background"
LABEL_NOTIFY_ONLY: Final = "healix_notify_only"
HEALIX_LABELS: Final = {
    LABEL_CRITICAL,
    LABEL_IGNORE,
    LABEL_PROTECTED,
    LABEL_ON_DEMAND,
    LABEL_BACKGROUND,
    LABEL_NOTIFY_ONLY,
}


class HealixMode(StrEnum):
    """Top-level operating modes."""

    DRY_RUN = "dry_run"
    SMART = "smart"


class PolicyMode(StrEnum):
    """Per-entity or per-integration policy modes."""

    IGNORE = "ignore"
    MONITOR_ONLY = "monitor_only"
    NOTIFY_ONLY = "notify_only"
    BACKGROUND_RECOVERY = "background_recovery"
    ON_DEMAND_RECOVERY = "on_demand_recovery"
    PROTECTED = "protected"


class NotificationLevel(StrEnum):
    """Notification verbosity."""

    QUIET = "quiet"
    NORMAL = "normal"
    VERBOSE = "verbose"


PROTECTED_INTEGRATIONS: Final = {
    "backup",
    "homeassistant",
    "homeassistant_supervisor",
    "knx",
    "matter",
    "mqtt",
    "mqtt_room_presence",
    "thread",
    "unifi",
    "zha",
    "zigbee_home_automation",
}

PROTECTED_DEVICE_CLASSES: Final = {
    "alarm",
    "lock",
    "safety",
    "security",
}

ON_DEMAND_INTEGRATIONS: Final = {
    "androidtv",
    "androidtv_remote",
    "apple_tv",
    "broadlink",
    "denon_avr",
    "dlna_dmr",
    "google_tv_remote",
    "kodi",
    "localtuya_ir_remote_control",
}

BACKGROUND_RECOVERY_INTEGRATIONS: Final = {
    "alexa",
    "dyson",
    "homekit_controller",
    "lg_thinq",
    "localtuya",
    "sonoff",
    "tplink",
    "tuya",
    "wiz",
}

MONITOR_ONLY_INTEGRATIONS: Final = {
    "google_sheets",
    "shopping_list",
    "spotify",
    "sun",
    "tts",
    "weather",
    "youtube",
}

IMPORTANT_ENTITY_DOMAINS: Final = {
    "alarm_control_panel",
    "climate",
    "fan",
    "humidifier",
    "light",
    "lock",
    "media_player",
    "remote",
    "switch",
    "vacuum",
    "water_heater",
}

LOW_IMPORTANCE_SENSOR_HINTS: Final = {
    "battery",
    "debug",
    "diagnostic",
    "linkquality",
    "link_quality",
    "lqi",
    "rssi",
    "signal",
    "status",
}

SERVICE_SAFE_REMOTE_COMMAND: Final = "safe_remote_command"
SERVICE_SAFE_SERVICE_CALL: Final = "safe_service_call"
SERVICE_MANUAL_RECOVER: Final = "manual_recover"
SERVICE_RUN_DIAGNOSIS: Final = "run_diagnosis"
SERVICE_PAUSE_RECOVERY: Final = "pause_recovery"
SERVICE_RESUME_RECOVERY: Final = "resume_recovery"
SERVICE_EXPORT_REPORT: Final = "export_report"

ATTR_ENTITY_ID: Final = "entity_id"
ATTR_COMMAND: Final = "command"
ATTR_DOMAIN: Final = "domain"
ATTR_SERVICE: Final = "service"
ATTR_TARGET: Final = "target"
ATTR_SERVICE_DATA: Final = "data"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
