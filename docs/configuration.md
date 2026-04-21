# Heka Insights Agent Configuration

## Overview

Runtime settings are now loaded through a unified configuration module.

All variables are resolved using one consistent order:

1. Process environment variables
2. Repository root `.env` (`./.env`)
3. Per-setting default (if defined)

## Configuration File

Use only one dotenv file:

- `./.env` (repository root)

`src/.env` is no longer used for runtime configuration.

## Variable Reference

| Variable | Type | Default | Current behavior |
|---|---|---|---|
| `LOG_LOCATION` | string path | none (required) | Startup fails if missing/empty or unwritable |
| `CPU_POLL_INTERVAL_SECONDS` | float (`> 0`) | `5.0` | Invalid values fall back to default with warning |
| `EXPORTER_TYPE` | enum | `console` | Supported: `console`, `otlp_http`, `datadog_native`, `newrelic_otlp` |

## Exporter Selector

`EXPORTER_TYPE` currently provides deterministic selection configuration with normalization (`strip` + lowercase).

- Missing value: defaults to `console`
- Unsupported value: falls back to `console` and logs a warning

Strict fail-fast validation for unsupported exporter values is planned for Milestone M3-4.

## Recommended Local Setup

```bash
cp .env.example .env
```

Then edit `./.env`:

```env
LOG_LOCATION=./log/heka_agent.log
CPU_POLL_INTERVAL_SECONDS=10
EXPORTER_TYPE=console
```

## Production Guidance

- Prefer absolute paths for `LOG_LOCATION`.
- Ensure the service user can create/write the configured log file.
- Override values via process environment in systemd or containers when needed.
