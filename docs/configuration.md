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
| `OTLP_HTTP_ENDPOINT` | absolute URL (`http/https`) | none | Required when `EXPORTER_TYPE=otlp_http`; startup fails if missing/invalid |
| `OTLP_HTTP_HEADERS` | comma-separated `key=value` pairs | empty | Optional headers added to OTLP HTTP requests; malformed values fail fast |
| `OTLP_RESOURCE_ATTRIBUTES` | comma-separated `key=value` pairs | empty | Optional attributes mapped to `resourceMetrics.resource.attributes`; malformed values fail fast |
| `OTLP_HTTP_TIMEOUT_SECONDS` | positive integer | `10` | HTTP request timeout for OTLP sends |
| `OTLP_HTTP_RETRY_MAX_ATTEMPTS` | positive integer | `5` | Maximum attempts per export call (includes first attempt) |
| `OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS` | positive float | `1.0` | Initial retry delay for transient failures |
| `OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS` | positive float | `5.0` | Upper bound for exponential retry delay |

## Exporter Selector

`EXPORTER_TYPE` currently provides deterministic selection configuration with normalization (`strip` + lowercase).

- Missing value: defaults to `console`
- Unsupported value: startup fails fast with explicit error
- Configured but unimplemented exporter (`datadog_native`, `newrelic_otlp`): startup fails fast with explicit error

## Exporter Validation Outcomes

| `EXPORTER_TYPE` value | Startup result |
|---|---|
| _missing_ | resolves to `console` and starts |
| `console` | starts with console exporter |
| `otlp_http` | starts when OTLP config is valid; fails fast when endpoint/key-value settings are invalid |
| `datadog_native` | fails fast (`RuntimeError`: exporter not implemented) |
| `newrelic_otlp` | fails fast (`RuntimeError`: exporter not implemented) |
| any other value | fails fast (`RuntimeError`: invalid selector value) |

## OTLP Key-Value Format

`OTLP_HTTP_HEADERS` and `OTLP_RESOURCE_ATTRIBUTES` use this format:

```text
key=value,key2=value2
```

Validation rules:

- entries are comma-delimited
- each entry must include one `=`
- keys and values are trimmed and must be non-empty

## OTLP Retry Behavior

Retry policy applies to OTLP HTTP exports when transient failures occur.

- Retryable: transport errors, HTTP `408`, HTTP `429`, and HTTP `5xx`
- Not retryable: HTTP `400`, `401`, `403`, `404` and other non-transient client errors
- Backoff uses capped exponential growth:
  - delay = `min(OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS, OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS * 2^(attempt-1))`

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
EXPORTER_TYPE=otlp_http
OTLP_HTTP_ENDPOINT=http://localhost:4318/v1/metrics
OTLP_HTTP_HEADERS=api-key=replace_me
OTLP_RESOURCE_ATTRIBUTES=service.name=heka-insights-agent,host.name=localhost
OTLP_HTTP_TIMEOUT_SECONDS=10
OTLP_HTTP_RETRY_MAX_ATTEMPTS=5
OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS=1
OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS=5
```

## Production Guidance

- Prefer absolute paths for `LOG_LOCATION`.
- Ensure the service user can create/write the configured log file.
- Override values via process environment in systemd or containers when needed.
