# Heka Insights Agent Configuration

## Overview

The current implementation uses two configuration variables:

- `LOG_LOCATION`
- `CPU_POLL_INTERVAL_SECONDS`

These are loaded from different places in the current codebase, so this document shows exact resolution order and recommended setup.

## Configuration Sources

### `LOG_LOCATION`

Used by `src/logger/config.py` to initialize the file logger.

Resolution order:

1. Process environment variable `LOG_LOCATION`
2. Repository root `.env` file (`./.env`)
3. Fail fast with `RuntimeError` if not found or empty

Notes:

- Relative paths are resolved against the repository root.
- The logger attempts to create/open the file at startup; permission errors stop startup.

### `CPU_POLL_INTERVAL_SECONDS`

Used by `src/main.py` to control the collector loop cadence.

Resolution behavior:

1. `src/.env` is loaded with `load_dotenv(..., override=False)`
2. Existing process env value (if set) is not overridden
3. If missing: default to `5.0`
4. If invalid (non-numeric or `<= 0`): warn and use `5.0`

## Variable Reference

| Variable | Type | Default | Where it is read | Example |
|---|---|---|---|---|
| `LOG_LOCATION` | string path | none (required) | `src/logger/config.py` | `LOG_LOCATION=./log/heka_agent.log` |
| `CPU_POLL_INTERVAL_SECONDS` | float (`> 0`) | `5.0` | `src/main.py` | `CPU_POLL_INTERVAL_SECONDS=10` |

## Recommended Local Setup

Create both env files used by the current implementation:

```bash
cp .env.example .env
cp src/.env.example src/.env
```

Then set values:

`./.env`

```env
LOG_LOCATION=./log/heka_agent.log
```

`src/.env`

```env
CPU_POLL_INTERVAL_SECONDS=10
```

## Production Guidance

- Prefer an absolute log path for `LOG_LOCATION` in production.
- Ensure the service user has write permission to the log directory.
- Keep `CPU_POLL_INTERVAL_SECONDS` high enough to avoid unnecessary host overhead.
- If you set values via your process manager (systemd, container env), those values take precedence over dotenv-loaded values.

## Effective Configuration Summary

At startup:

1. Logger initializes first and requires `LOG_LOCATION` (env or root `.env`)
2. `src/.env` is loaded for runtime settings like `CPU_POLL_INTERVAL_SECONDS`
3. Collector loop starts with validated poll interval

## Known Quirk (Current State)

Configuration is currently split between:

- root `.env` for logger
- `src/.env` for polling interval

This is intentional in current code behavior, but future refactoring should consolidate to a single config source.
