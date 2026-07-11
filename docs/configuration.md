# Heka Insights Agent Configuration

## Runtime Source

Packaged runtime configuration is loaded in this order:

1. Process environment variables
2. `/etc/heka-insights-agent/.env`
3. Per-setting defaults where supported

The packaged service does not read repository-root `.env`.

## Setup Flow

Package install attempts to launch the interactive setup wizard during packaged
installation:

- Debian / Ubuntu: `sudo dpkg -i heka-insights-agent_<version>_amd64.deb`
- EL9 RPM: `sudo dnf install -y ./heka-insights-agent-<version>-1.el9.x86_64.rpm`

If setup is cancelled or skipped, resume it with:

```bash
sudo /usr/local/bin/heka-insights-agent setup
```

Successful setup writes:

- config: `/etc/heka-insights-agent/.env`
- logs: `/var/log/heka-insights-agent/agent.log`

## Ownership And Permissions

The packaged runtime uses:

- service user: `heka-agent`
- service group: `heka-agent`
- config dir: `/etc/heka-insights-agent` owned by `root:heka-agent`, mode `750`
- config file: `/etc/heka-insights-agent/.env` owned by `root:heka-agent`, mode `640`
- log dir: `/var/log/heka-insights-agent` owned by `heka-agent:heka-agent`, mode `750`

## Variable Reference

| Variable | Type | Default | Current behavior |
|---|---|---|---|
| `LOG_LOCATION` | absolute path | none (required) | Startup fails if missing, empty, relative, or unwritable |
| `CPU_POLL_INTERVAL_SECONDS` | float (`> 0`) | `5.0` | Invalid values fall back to default with warning |
| `EXPORTER_TYPE` | enum | `console` | Supported: `console`, `otlp_http`, `datadog_otlp`, `datadog_native`, `newrelic_otlp` |
| `OTLP_HTTP_ENDPOINT` | absolute URL (`http/https`) | none | Required when `EXPORTER_TYPE=otlp_http` |
| `OTLP_HTTP_HEADERS` | `key=value` pairs | empty | Optional headers for OTLP HTTP-based exporters |
| `OTLP_RESOURCE_ATTRIBUTES` | `key=value` pairs | empty | Optional OTLP resource attributes |
| `OTLP_HTTP_TIMEOUT_SECONDS` | positive integer | `10` | Used by OTLP HTTP and Datadog native sender timeouts |
| `OTLP_HTTP_RETRY_MAX_ATTEMPTS` | positive integer | `5` | Used by OTLP HTTP-based exporters |
| `OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS` | positive float | `1.0` | Used by OTLP HTTP-based exporters |
| `OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS` | positive float | `5.0` | Used by OTLP HTTP-based exporters |
| `NEWRELIC_OTLP_ENDPOINT` | absolute URL (`http/https`) | none | Required when `EXPORTER_TYPE=newrelic_otlp` |
| `NEWRELIC_API_KEY` | string | none | Required when `EXPORTER_TYPE=newrelic_otlp` |
| `NEWRELIC_SERVICE_NAME` | string | none | Required when `EXPORTER_TYPE=newrelic_otlp` |
| `NEWRELIC_ENVIRONMENT` | string | empty | Optional |
| `NEWRELIC_HOST_NAME` | string | empty | Optional |
| `DATADOG_SITE` | string domain | none | Required when `EXPORTER_TYPE=datadog_otlp` or `datadog_native` |
| `DATADOG_API_KEY` | string | none | Required when `EXPORTER_TYPE=datadog_otlp` or `datadog_native` |
| `DATADOG_HOSTNAME` | string | empty | Optional |
| `DATADOG_TAGS` | `key:value` pairs | empty | Optional |
| `DATADOG_METRIC_PREFIX` | string | empty | Optional for `datadog_native` |

## Exporter Notes

### `console`

- Starts with no exporter-specific required configuration.

### `otlp_http`

- Requires `OTLP_HTTP_ENDPOINT`
- Accepts optional `OTLP_HTTP_HEADERS`
- Accepts optional `OTLP_RESOURCE_ATTRIBUTES`
- Uses OTLP retry settings

### `datadog_otlp`

- Requires `DATADOG_SITE`
- Requires `DATADOG_API_KEY`
- Accepts optional `DATADOG_HOSTNAME`
- Accepts optional `DATADOG_TAGS`
- Accepts optional OTLP headers and resource attributes
- Uses OTLP retry settings

### `datadog_native`

- Requires `DATADOG_SITE`
- Requires `DATADOG_API_KEY`
- Accepts optional `DATADOG_HOSTNAME`
- Accepts optional `DATADOG_TAGS`
- Accepts optional `DATADOG_METRIC_PREFIX`
- Uses `OTLP_HTTP_TIMEOUT_SECONDS` for sender timeout

### `newrelic_otlp`

- Requires `NEWRELIC_OTLP_ENDPOINT`
- Requires `NEWRELIC_API_KEY`
- Requires `NEWRELIC_SERVICE_NAME`
- Accepts optional `NEWRELIC_ENVIRONMENT`
- Accepts optional `NEWRELIC_HOST_NAME`
- Accepts optional OTLP headers and resource attributes
- Uses OTLP retry settings

## Example Packaged Config

```env
LOG_LOCATION=/var/log/heka-insights-agent/agent.log
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
