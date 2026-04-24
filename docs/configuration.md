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
- Unsupported value: startup fails fast with explicit error
- Configured but unimplemented exporter (`otlp_http`, `datadog_native`, `newrelic_otlp`): startup fails fast with explicit error

## Exporter Validation Outcomes

| `EXPORTER_TYPE` value | Startup result |
|---|---|
| _missing_ | resolves to `console` and starts |
| `console` | starts with console exporter |
| `otlp_http` | fails fast (`RuntimeError`: exporter not implemented) |
| `datadog_native` | fails fast (`RuntimeError`: exporter not implemented) |
| `newrelic_otlp` | fails fast (`RuntimeError`: exporter not implemented) |
| any other value | fails fast (`RuntimeError`: invalid selector value) |

## Lifecycle Notes

Exporter lifecycle is always:

1. `initialize()` on startup
2. `export(metrics)` on each collection cycle
3. `shutdown()` in application teardown (`finally`)

For full delivery architecture and responsibility boundaries, see `docs/architecture.md`.

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
