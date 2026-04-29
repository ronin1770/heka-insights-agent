# Heka Insights Agent Architecture

## Purpose

Heka Insights Agent collects host telemetry and routes it through a delivery pipeline designed for future backend integrations.

The Milestone 3 foundation keeps collection separate from delivery so new exporters can be added without changing collectors.

## Runtime Delivery Topology

```text
┌─────────────────────────────────────────────────────────────┐
│                         src/main.py                         │
│   startup + validation + lifecycle orchestration            │
└───────────────┬─────────────────────────────────────────────┘
                │
                │ collect raw payloads (cpu/memory/disk)
                ▼
┌─────────────────────────────────────────────────────────────┐
│                    collectors/*                             │
│ CPUCollector | MemoryCollector | DiskCollector              │
└───────────────┬─────────────────────────────────────────────┘
                │
                │ normalize
                ▼
┌─────────────────────────────────────────────────────────────┐
│            pipeline/canonical_metrics.py                    │
│          build_canonical_metrics(payloads, ts)              │
└───────────────┬─────────────────────────────────────────────┘
                │
                │ canonical metric collection
                ▼
┌─────────────────────────────────────────────────────────────┐
│                   exporters/base.py                         │
│       Exporter.initialize -> export -> shutdown             │
└───────────────┬─────────────────────────────────────────────┘
                │
                │ selected exporter instance
                ▼
┌─────────────────────────────────────────────────────────────┐
│                exporters/console.py                         │
│       PrometheusFormatter.format_canonical(metrics)         │
│                    writes to stdout                         │
└─────────────────────────────────────────────────────────────┘
```

## Exporter Lifecycle

Every exporter follows the same lifecycle contract:

1. `initialize()`
2. `export(metrics)` on each polling cycle
3. `shutdown()` on process shutdown (`finally`)

Lifecycle intent:

- `initialize()` prepares exporter resources and validates exporter-owned runtime assumptions.
- `export(metrics)` receives canonical metrics only.
- `shutdown()` releases owned resources and flushes pending work if needed.

## Responsibility Boundaries

| Layer | Responsibility | Must Not Do |
|---|---|---|
| Collectors (`src/collectors`) | Read system telemetry from `psutil` and return raw payload dictionaries | Know exporter type or backend transport details |
| Pipeline (`src/pipeline/canonical_metrics.py`) | Convert raw collector payloads into canonical metric records | Perform transport or backend-specific delivery |
| Formatter (`src/formatters/prometheus.py`) | Render canonical metrics into a reusable output format | Collect metrics directly from the OS |
| Exporter (`src/exporters`) | Own destination delivery behavior and lifecycle | Reach into collector internals or collector-specific payload shape |
| Runtime orchestration (`src/main.py`) | Wire lifecycle and sequence calls deterministically | Hardcode output transport behavior inside loop |

## Startup Validation Rules

Exporter startup is validated in two stages:

1. `get_exporter_type()` validates `EXPORTER_TYPE` against supported enum values.
2. `create_exporter()` validates implementation availability for selected type.

Current startup behavior:

- Missing `EXPORTER_TYPE` -> defaults to `console`
- Invalid `EXPORTER_TYPE` value -> fail fast with explicit `RuntimeError`
- `EXPORTER_TYPE=otlp_http` -> exporter initializes when OTLP endpoint/config is valid
- Configured but unimplemented exporter (`datadog_native`, `newrelic_otlp`) -> fail fast with explicit `RuntimeError`

This prevents silent fallback behavior and makes runtime intent explicit.

## Runtime Sequence

Per process start:

1. logger initializes
2. exporter type resolves from config
3. exporter instance is created
4. exporter `initialize()` runs

Per collection cycle:

1. CPU, memory, and disk collectors gather raw payloads
2. payloads convert to canonical metrics
3. exporter `export(canonical_metrics)` runs
4. monotonic ticker sleeps to next fixed cadence

On shutdown:

1. `KeyboardInterrupt` is handled in `main`
2. exporter `shutdown()` always runs in `finally`

## Canonical Metric Model

Canonical metrics include:

- `name`
- `description`
- `type`
- `unit`
- `value`
- `labels`
- optional `timestamp_unix_ms`

Exporters consume this model, not collector-specific payloads.

## Current Exporter Availability

Implemented:

- `console`
- `otlp_http`

Declared but not yet implemented:

- `datadog_native`
- `newrelic_otlp`

The factory fails fast for unimplemented exporters.

## How To Add A New Exporter

1. Create a new exporter class under `src/exporters/` implementing `Exporter`.
2. Implement `initialize()`, `export()`, and `shutdown()`.
3. Ensure `export()` accepts canonical metrics (no collector payload assumptions).
4. Wire the exporter into `create_exporter()` in `src/exporters/factory.py`.
5. Validate required configuration during startup path and fail fast on invalid config.
6. Keep collectors unchanged.

## File Map

- `src/main.py`: startup orchestration and lifecycle execution
- `src/config/runtime.py`: runtime configuration loading and exporter selector validation
- `src/pipeline/canonical_metrics.py`: raw payload to canonical metric normalization
- `src/exporters/base.py`: exporter contract and canonical metric types
- `src/exporters/factory.py`: exporter selection and implementation availability checks
- `src/exporters/console.py`: console exporter adapter
- `src/formatters/prometheus.py`: Prometheus rendering from canonical metrics
