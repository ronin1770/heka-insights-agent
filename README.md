![Project Logo](./docs/assets/logo.png)

# Heka Insights Agent

**Heka Insights Agent** is a lightweight, extensible, open-source telemetry agent for Linux systems. It is designed to collect core host-level metrics in a unified structure so the output can be consumed by a wide range of observability and monitoring backends such as **Datadog**, **New Relic**, and similar platforms.

The project is being built to stay simple, portable, contributor-friendly, and flexible enough for future standalone executable packaging.

---

## Why This Project Exists

Many telemetry agents are either tightly coupled to a specific vendor, too heavy for smaller deployments, or difficult to extend for custom use cases.

Heka Insights Agent aims to provide:

- lightweight system telemetry collection
- a clean and modular Python codebase
- a unified internal output format
- compatibility with multiple Linux distributions
- an open-source foundation for community contributions
- a path toward standalone executable distribution

---

## Key Goals

- Collect essential host-level telemetry from Linux systems
- Normalize collected data into a common structure
- Support downstream integration with Datadog, New Relic, and similar backends
- Keep the runtime lightweight and easy to operate
- Allow future packaging as standalone executables
- Encourage open-source contributions and extensibility

---

## Supported Platforms

The agent is intended to work with Linux environments including:

- Debian
- Ubuntu
- CentOS
- Red Hat / RHEL-compatible systems

Linux is the primary target platform.

---

## Current PyPI Dependencies

This project currently uses:

- `python-dotenv`
- `psutil`

Install them with:

```bash
pip install python-dotenv psutil
````

Or through the project requirements file:

```bash
pip install -r requirements.txt
```

---

## Project Structure

Based on the current repository structure on the development machine:

```text
heka-insights-agent/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   ├── workflows/
│   └── pull_request_template.md
├── docs/
│   ├── architecture.md
│   ├── configuration.md
│   ├── development.md
│   ├── devto-build-log-2026-04-08.md
│   ├── roadmap.md
│   └── troubleshooting.md
├── hk_env/
├── log/
├── profiles/
│   ├── main_top_cumtime.txt
│   ├── main.pstats
│   └── time.txt
├── src/
│   ├── __pycache__/
│   ├── collectors/
│   └── logger/
├── tests/
├── .codex
├── .env
├── .env.example
├── .gitignore
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── Makefile
├── pyproject.toml
├── README.md
└── requirements.txt
```

---

## What the Agent Does

Heka Insights Agent is intended to collect and normalize machine telemetry such as:

* CPU usage
* memory usage
* disk I/O
* runtime health indicators
* internal application performance stats

The purpose is to emit telemetry in a **unified data format** so it can later be:

* transformed for backend-specific ingestion
* sent to external monitoring platforms
* logged locally
* batched and compressed
* adapted for future standards-based exporters

---

## Unified Output Philosophy

A core design goal of Heka Insights Agent is to separate **data collection** from **data delivery**.

Instead of binding collectors directly to one backend, the project is designed to:

1. collect raw system metrics
2. normalize them into a unified schema
3. allow adapters or senders to transform that data for target platforms

That design makes it easier to support:

* Datadog
* New Relic
* custom internal telemetry platforms
* future OpenMetrics or Prometheus-style exporters
* other observability pipelines

This keeps the agent reusable and vendor-agnostic.

---

## Open Source

Heka Insights Agent is intended to be an open-source project.

The repository already includes:

* `CONTRIBUTING.md`
* `CODE_OF_CONDUCT.md`
* `LICENSE`
* GitHub issue templates
* pull request template

Contributions are welcome from developers interested in:

* Linux telemetry
* observability tooling
* performance optimization
* agent architecture
* output adapters
* documentation
* standalone packaging

---

## Contributing

If you want to contribute, start by reviewing:

* `CONTRIBUTING.md`

Useful contribution areas include:

* new collectors
* logging improvements
* schema refinement
* cross-distro validation
* performance profiling
* standalone executable packaging
* tests and CI improvements
* backend adapter implementations

---

## Standalone Executable Direction

A longer-term goal of the project is to produce **standalone executables** for easier deployment.

This is useful when teams want:

* simpler distribution across Linux servers
* reduced dependency on preconfigured Python environments
* easier installation and rollout
* more controlled runtime packaging

The repository structure is being developed with that direction in mind.

---

## Documentation

The `docs/` directory is used to keep the project organized and contributor-friendly.

Current documentation includes:

* `architecture.md`
* `configuration.md`
* `development.md`
* `roadmap.md`
* `troubleshooting.md`

This should make the project easier to understand, extend, and operate.

---

## Performance Awareness

The project also includes a `profiles/` directory to capture early profiling and runtime measurement artifacts such as:

* cumulative timing output
* profiling stats
* execution timing notes

Performance is an important design concern for this project. The agent should remain lightweight enough to run continuously without becoming a system burden.

---

## Local Development Setup

### Clone the repository

```bash
git clone https://github.com/ronin1770/heka-insights-agent.git
cd heka-insights-agent
```

### Create and activate a virtual environment

```bash
python3 -m venv hk_env
source hk_env/bin/activate
```

### Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```


## Environment Configuration

Runtime configuration is loaded from a single file at repository root:

- `./.env`

Copy the example file:

```bash
cp .env.example .env
```

Set values in `./.env`:

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
# New Relic OTLP preset (optional)
NEWRELIC_OTLP_ENDPOINT=https://otlp.nr-data.net/v1/metrics
NEWRELIC_API_KEY=replace_with_new_relic_license_key
NEWRELIC_SERVICE_NAME=heka-insights-agent
NEWRELIC_ENVIRONMENT=dev
NEWRELIC_HOST_NAME=localhost
```

### Environment Variables

#### `LOG_LOCATION`

Path to the application log file. Relative paths resolve from the repository root.

#### `CPU_POLL_INTERVAL_SECONDS`

Defines collector loop cadence in seconds. Must be a positive number.
Invalid values fall back to `5.0` with a warning.

#### `EXPORTER_TYPE`

Exporter selection setting for the delivery layer foundation.

Supported values:

- `console`
- `otlp_http`
- `datadog_native`
- `newrelic_otlp`

Current behavior:

- missing value defaults to `console`
- unsupported values fail fast at startup with an explicit error
- `otlp_http` starts when OTLP config is valid
- `newrelic_otlp` starts when New Relic preset config is valid
- configured but unimplemented exporters (`datadog_native`) fail fast at startup with an explicit error

#### `OTLP_HTTP_ENDPOINT`

Required when `EXPORTER_TYPE=otlp_http`. Must be an absolute `http://` or `https://` URL.

#### `OTLP_HTTP_HEADERS`

Optional OTLP request headers in `key=value,key2=value2` format.

#### `OTLP_RESOURCE_ATTRIBUTES`

Optional resource attributes mapped to OTLP `resourceMetrics.resource.attributes` in `key=value,key2=value2` format.

#### `OTLP_HTTP_TIMEOUT_SECONDS`

OTLP HTTP request timeout in seconds. Must be a positive integer.

#### `OTLP_HTTP_RETRY_MAX_ATTEMPTS`

Maximum OTLP send attempts per export call, including the first attempt.

#### `OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS`

Initial retry delay for transient OTLP failures.

#### `OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS`

Maximum retry delay cap for OTLP exponential backoff.

#### `NEWRELIC_OTLP_ENDPOINT`

Required when `EXPORTER_TYPE=newrelic_otlp`. Must be an absolute `http://` or `https://` URL.

#### `NEWRELIC_API_KEY`

Required when `EXPORTER_TYPE=newrelic_otlp`. Injected automatically as OTLP header `api-key`.

#### `NEWRELIC_SERVICE_NAME`

Required when `EXPORTER_TYPE=newrelic_otlp`. Mapped to resource attribute `service.name`.

#### `NEWRELIC_ENVIRONMENT`

Optional when `EXPORTER_TYPE=newrelic_otlp`. Mapped to resource attribute `deployment.environment`.

#### `NEWRELIC_HOST_NAME`

Optional when `EXPORTER_TYPE=newrelic_otlp`. Mapped to resource attribute `host.name`.

### New Relic Preset Example

Use this preset to route telemetry to New Relic using OTLP HTTP internals:

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

## OTLP Collector Testing

Use the provided collector config file:

- `tests/otel-collector-config.yaml`

Start a local OpenTelemetry Collector with Docker:

```bash
cd tests
docker run --rm \
  -p 4318:4318 \
  -v "$(pwd)/otel-collector-config.yaml:/etc/otelcol/config.yaml" \
  otel/opentelemetry-collector-contrib:latest \
  --config=/etc/otelcol/config.yaml
```

Notes:

- Use `otel/opentelemetry-collector-contrib:latest` for auth extensions like `bearertokenauth`.
- If the collector config uses `scheme: "Bearer"` with `header: "key"`, set:

```env
OTLP_HTTP_HEADERS=key=Bearer abcd1234
```

- If the collector config uses `scheme: ""`, set:

```env
OTLP_HTTP_HEADERS=key=abcd1234
```

Run the agent from repo root in a separate terminal:

```bash
python src/main.py
```

### OTLP Integration Tests (Docker)

Integration tests automatically start and stop collector containers using fixture configs under:

- `tests/fixtures/otlp/`

Run only OTLP integration tests:

```bash
RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest -v tests.test_otlp_http_integration
```

Run full suite including integration tests:

```bash
RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run New Relic preset integration tests:

```bash
docker compose -f docker-compose.test.yml run --rm \
  -e RUN_OTLP_INTEGRATION=1 \
  -e OTLP_IT_HOST=host.docker.internal \
  test-runner \
  pytest -vv -s -rs tests/milestone-5/test_newrelic_otlp_integration.py
```

Expected result:

```text
collected 3 items

tests/milestone-5/test_newrelic_otlp_integration.py::NewRelicOtlpIntegrationTests::test_newrelic_preset_injects_api_key_header PASSED
tests/milestone-5/test_newrelic_otlp_integration.py::NewRelicOtlpIntegrationTests::test_newrelic_preset_overrides_conflicting_otlp_api_key_header PASSED
tests/milestone-5/test_newrelic_otlp_integration.py::NewRelicOtlpIntegrationTests::test_newrelic_preset_rejects_invalid_api_key_without_retry_for_401 PASSED

3 passed
```

Optional image override:

```bash
OTELCOL_IMAGE=otel/opentelemetry-collector-contrib:latest RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest -v tests.test_otlp_http_integration
```

Optional port-base override (tests use `14318`, `14319`, `14320` by default):

```bash
OTLP_IT_BASE_PORT=15318 RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest -v tests.test_otlp_http_integration
```

## Exporter Lifecycle (M3 Foundation)

Runtime delivery now follows a stable sequence:

1. Collect raw payloads from collectors.
2. Normalize payloads into canonical metrics.
3. Call exporter lifecycle methods:
   - `initialize()` at startup
   - `export(metrics)` every collection cycle
   - `shutdown()` during teardown

Responsibility split:

- collectors gather telemetry
- pipeline normalizes to canonical model
- formatter renders output
- exporter handles destination delivery

This separation allows new exporters to be added without collector changes.

See detailed docs:

- `docs/architecture.md` for full flow and boundaries
- `docs/configuration.md` for exporter validation behavior

## Adding A New Exporter (Current Rule)

1. Implement `Exporter` contract under `src/exporters/`.
2. Wire it in `src/exporters/factory.py`.
3. Ensure startup fails fast if required exporter config is invalid.
4. Keep collector modules unchanged.

### Run the application

Depending on your entrypoint setup:

```bash
python src/main.py
```

If the main entrypoint changes later, update this section accordingly.

---

## Initial Scope

The current foundation work focuses on:

* creating the basic code structure
* setting up local development
* installing required dependencies
* getting collectors working for CPU, memory, and disk I/O
* defining a standard logging format
* gathering basic performance statistics about the application

This provides the base needed for future output adapters, batching, senders, and executable packaging.

---

## Roadmap Direction

Planned areas of development include:

* additional Linux system collectors
* unified schema evolution
* sender/adaptor modules for backend platforms
* logging improvements
* compressed or batched delivery
* standards-aligned formatting
* standalone executable builds
* broader test coverage across Linux distributions
* deeper profiling and performance tuning
