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
| `EXPORTER_TYPE` | enum | `console` | Supported: `console`, `otlp_http`, `datadog_otlp`, `datadog_native`, `newrelic_otlp` |
| `OTLP_HTTP_ENDPOINT` | absolute URL (`http/https`) | none | Required when `EXPORTER_TYPE=otlp_http`; startup fails if missing/invalid |
| `OTLP_HTTP_HEADERS` | comma-separated `key=value` pairs | empty | Optional headers added to OTLP HTTP requests; malformed values fail fast |
| `OTLP_RESOURCE_ATTRIBUTES` | comma-separated `key=value` pairs | empty | Optional attributes mapped to `resourceMetrics.resource.attributes`; malformed values fail fast |
| `OTLP_HTTP_TIMEOUT_SECONDS` | positive integer | `10` | HTTP request timeout for OTLP sends |
| `OTLP_HTTP_RETRY_MAX_ATTEMPTS` | positive integer | `5` | Maximum attempts per export call (includes first attempt) |
| `OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS` | positive float | `1.0` | Initial retry delay for transient failures |
| `OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS` | positive float | `5.0` | Upper bound for exponential retry delay |
| `NEWRELIC_OTLP_ENDPOINT` | absolute URL (`http/https`) | none | Required when `EXPORTER_TYPE=newrelic_otlp`; startup fails if missing/invalid |
| `NEWRELIC_API_KEY` | string | none | Required when `EXPORTER_TYPE=newrelic_otlp`; injected as `api-key` OTLP header |
| `NEWRELIC_SERVICE_NAME` | string | none | Required when `EXPORTER_TYPE=newrelic_otlp`; mapped to resource `service.name` |
| `NEWRELIC_ENVIRONMENT` | string | empty | Optional; mapped to resource `deployment.environment` |
| `NEWRELIC_HOST_NAME` | string | empty | Optional; mapped to resource `host.name` |
| `DATADOG_SITE` | string domain | none | Required when `EXPORTER_TYPE=datadog_otlp` or `datadog_native`; must match allowed Datadog sites |
| `DATADOG_API_KEY` | string | none | Required when `EXPORTER_TYPE=datadog_otlp` or `datadog_native`; must be non-empty |
| `DATADOG_HOSTNAME` | string | empty | Optional host override for Datadog exporters |
| `DATADOG_TAGS` | comma-separated `key:value` pairs | empty | Optional default Datadog tags; malformed values fail fast |
| `DATADOG_METRIC_PREFIX` | string | empty | Optional Datadog native metric prefix; blank-after-trim fails fast |

## Exporter Selector

`EXPORTER_TYPE` currently provides deterministic selection configuration with normalization (`strip` + lowercase).

- Missing value: defaults to `console`
- Unsupported value: startup fails fast with explicit error

## Exporter Validation Outcomes

| `EXPORTER_TYPE` value | Startup result |
|---|---|
| _missing_ | resolves to `console` and starts |
| `console` | starts with console exporter |
| `otlp_http` | starts when OTLP config is valid; fails fast when endpoint/key-value settings are invalid |
| `datadog_otlp` | starts when Datadog site/API key and tag settings are valid; endpoint and auth header are derived |
| `datadog_native` | starts when Datadog site/API key and tag settings are valid; native endpoint is derived |
| `newrelic_otlp` | starts when New Relic preset config is valid; fails fast when required values are missing/invalid |
| any other value | fails fast (`RuntimeError`: invalid selector value) |

## New Relic Preset Mode

When `EXPORTER_TYPE=newrelic_otlp`, the runtime resolves New Relic settings into OTLP HTTP exporter internals.

Preset behavior:

- `NEWRELIC_OTLP_ENDPOINT` is required and must be an absolute `http://` or `https://` URL.
- `NEWRELIC_API_KEY` is required and is injected as OTLP header `api-key`.
- `NEWRELIC_SERVICE_NAME` is required and mapped to `service.name`.
- `NEWRELIC_ENVIRONMENT` is optional and mapped to `deployment.environment`.
- `NEWRELIC_HOST_NAME` is optional and mapped to `host.name`.
- `NEWRELIC_*` values take precedence over conflicting OTLP values in preset mode.

Example:

```env
EXPORTER_TYPE=newrelic_otlp
NEWRELIC_OTLP_ENDPOINT=https://otlp.nr-data.net/v1/metrics
NEWRELIC_API_KEY=<your_license_key>
NEWRELIC_SERVICE_NAME=heka-insights-agent
NEWRELIC_ENVIRONMENT=production
NEWRELIC_HOST_NAME=node-a
```

Region endpoint examples:

- US: `https://otlp.nr-data.net/v1/metrics`
- EU: `https://otlp.eu01.nr-data.net/v1/metrics`

## Datadog Site Validation

When `EXPORTER_TYPE` is `datadog_otlp` or `datadog_native`, `DATADOG_SITE` is required and must be one of:

- `datadoghq.com`
- `datadoghq.eu`
- `us3.datadoghq.com`
- `us5.datadoghq.com`
- `ap1.datadoghq.com`
- `ap2.datadoghq.com`
- `ddog-gov.com`

Invalid or missing values fail fast during startup configuration.

## Datadog OTLP Preset Mode

When `EXPORTER_TYPE=datadog_otlp`, runtime derives OTLP settings from Datadog configuration:

- endpoint: `https://otlp.<DATADOG_SITE>/v1/metrics`
- auth header: `dd-api-key: <DATADOG_API_KEY>`
- optional host override: `DATADOG_HOSTNAME` -> `host.name` resource attribute
- optional `DATADOG_TAGS` are mapped into OTLP resource attributes (`key:value` -> `key=value`)

## Datadog Native Mapping Rules

When `EXPORTER_TYPE=datadog_native`, runtime derives the native endpoint:

- `https://api.<DATADOG_SITE>/api/v1/series`

Mapping behavior:

- canonical `gauge` -> Datadog `gauge`
- canonical `counter` -> Datadog `count`
- `timestamp_unix_ms` -> Datadog point timestamp (Unix seconds)
- `counter` includes `interval` derived from `CPU_POLL_INTERVAL_SECONDS` (rounded, minimum `1`)
- label tags and default tags are deterministic; `DATADOG_TAGS` override label tags for matching keys
- `DATADOG_HOSTNAME` overrides host identity from metric labels

## Datadog OTLP vs Datadog Native

Use this section to choose between `datadog_otlp` and `datadog_native`.

| Dimension | `datadog_otlp` | `datadog_native` |
|---|---|---|
| Exporter type | `EXPORTER_TYPE=datadog_otlp` | `EXPORTER_TYPE=datadog_native` |
| Transport endpoint | `https://otlp.<DATADOG_SITE>/v1/metrics` | `https://api.<DATADOG_SITE>/api/v1/series` |
| Auth header | `dd-api-key` (derived from `DATADOG_API_KEY`) | `DD-API-KEY` (derived from `DATADOG_API_KEY`) |
| Delivery model | OTLP HTTP exporter internals with Datadog preset | Datadog API v1 native series payload |
| Mapping control | OTLP mapping with Datadog resource/tag preset behavior | Explicit Datadog series mapping (`gauge`/`count`, `interval`) |
| Counter interval behavior | OTLP exporter behavior | `count` includes `interval` derived from `CPU_POLL_INTERVAL_SECONDS` |
| Portability | Higher portability across OTLP-compatible backends | Datadog-specific integration path |

### Choosing Guidance

- Choose `datadog_otlp` when you want OTLP-aligned behavior and better cross-backend portability.
- Choose `datadog_native` when you want Datadog-specific metric semantics and explicit native series control.

### Shared Datadog Validation

Both modes enforce the same startup validation:

- `DATADOG_SITE` must be an allowed full domain.
- `DATADOG_API_KEY` must be non-empty.
- `DATADOG_TAGS` must use strict `key:value` format.
- `DATADOG_HOSTNAME` overrides label-derived host when provided.

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
