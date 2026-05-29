# Healix

Smart self-healing for Home Assistant.

Healix is a Home Assistant custom integration that watches important entities, diagnoses failures, and safely recovers only the affected config entry when policy allows. It is designed as a cautious recovery supervisor, not a broad auto-reloader.

## Status

This is an MVP release. Install and test in dry-run mode first.

## Features

- UI setup with config flow and options flow
- Dry-run mode enabled by default
- Auto-discovery of entities, devices, integrations, areas, labels, automations, and scripts where available
- Policy modes: ignore, monitor only, notify only, background recovery, on-demand recovery, protected
- Protected integrations by default for infrastructure and safety-sensitive systems
- Network health gate and broad-outage detection before reloads
- Startup grace period, cooldowns, retry limits, and exponential backoff
- Safe on-demand service wrappers for remotes and service calls
- Persistent notifications, Repair issues, and incident history
- Dashboard sensors and buttons

## HACS Installation

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository.
3. Select category `Integration`.
4. Install Healix.
5. Restart Home Assistant.
6. Go to Settings > Devices & services > Add integration.
7. Search for `Healix`.
8. Keep `Dry run / Observe only` selected for the first test period.

## Manual Installation

Copy `custom_components/healix` into the `custom_components` directory in your Home Assistant config folder, then restart Home Assistant.

## First Dry-Run Test

Start with dry-run mode. Healix will observe failures, classify affected entities, diagnose likely causes, and record what it would have done without reloading integrations or forwarding unsafe wrapped service calls when the target entity is still unavailable.

Recommended first checks:

- Confirm `sensor.healix_active_issues` exists.
- Press `button.healix_run_diagnosis`.
- Review persistent notifications and Home Assistant logs.
- Add network health entities in Advanced options if you have router or internet ping sensors.

## Services

### `healix.safe_remote_command`

Safely send a remote command after checking the target entity.

```yaml
service: healix.safe_remote_command
data:
  entity_id: remote.tata_play_remote
  command: volume_up
```

### `healix.safe_service_call`

Safely call a Home Assistant service after checking target entities.

```yaml
service: healix.safe_service_call
data:
  domain: remote
  service: send_command
  target:
    entity_id: remote.example
  data:
    command: power
```

### `healix.manual_recover`

Manually reload the owning config entry for an entity or a specific config entry. Manual recovery is audited in incident history.

## Labels

Healix supports these Home Assistant labels:

- `healix_critical`
- `healix_ignore`
- `healix_protected`
- `healix_on_demand`
- `healix_background`
- `healix_notify_only`

Labels override automatic classification.

## Safety Model

Healix diagnoses before reload. It will block automatic recovery when:

- Home Assistant is inside the startup grace period
- Network health entities indicate an outage
- Many unrelated integrations are failing together
- The integration is protected
- Cooldown is active
- Retry limits are reached
- The entity is ignored, disabled, hidden, diagnostic, battery, RSSI, signal, linkquality, or status/debug by default

Healix never restarts Home Assistant.

## Dashboard Entities

Healix exposes:

- `sensor.healix_active_issues`
- `sensor.healix_last_failed_entity`
- `sensor.healix_last_recovery_result`
- `sensor.healix_reload_count_today`
- `sensor.healix_blocked_count_today`
- `sensor.healix_network_health`
- `binary_sensor.healix_recovery_active`
- `binary_sensor.healix_network_outage`
- `button.healix_run_diagnosis`
- `button.healix_pause_recovery`
- `button.healix_resume_recovery`
- `button.healix_export_report`

## Release Notes

### v0.1.0

Initial MVP release with dry-run mode, classification, safety policy, background and on-demand recovery, dashboard entities, notifications, repairs, and incident history.
