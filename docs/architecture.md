# Heka Insights Agent Architecture

## Purpose and Current Scope

Heka Insights Agent is a host telemetry collector focused on Linux environments.
The current implementation provides:

- CPU usage collection (`CPUCollector`)
- Memory usage collection (`MemoryCollector`)
- Disk I/O counter collection (`DiskCollector`)
- Structured logging to both file and stdout
- A fixed-cadence polling loop

There is currently no network transport, batching, persistence, or external backend sender in the codebase.

## Runtime Topology

```text
┌───────────────────────────┐
│        src/main.py        │
│  - startup / main loop    │
│  - env interval parsing   │
└──────────────┬────────────┘
               │
       every polling cycle
               │
   ┌───────────┼───────────┐
   │           │           │
┌──▼───┐   ┌───▼────┐   ┌──▼────┐
│ CPU  │   │ Memory │   │ Disk  │
│collector│ │collector│  │collector│
└──┬───┘   └───┬────┘   └──┬────┘
   │           │           │
   └───────┬───┴───────┬───┘
           │           │
     payload dicts  payload dicts
           │
     ┌─────▼──────────────────────┐
     │ logger/config.py           │
     │ - file handler (required)  │
     │ - colored stdout handler   │
     └────────────────────────────┘
```

## Main Control Loop

The entrypoint is `src/main.py`.

Execution model:

1. Initialize logger via `get_logger(__name__)`
2. Load `src/.env` (for poll interval)
3. Create collectors:
   - `CPUCollector(per_cpu=False, detail="detailed")`
   - `MemoryCollector(detail="detailed")`
   - `DiskCollector(detail="detailed")`
4. Create `MonotonicTicker(interval_seconds=<configured>)`
5. Enter infinite `while True` loop:
   - Collect CPU, memory, disk payloads
   - Emit each payload as a log line
   - Sleep until next monotonic deadline

Shutdown behavior:

- `KeyboardInterrupt` is caught in `main()` and logged as a controlled shutdown.

## Component Design

### CPU Collector

Implementation: `src/collectors/cpu.py`

Design highlights:

- Uses `psutil.cpu_times(...)` snapshots and delta math (not `cpu_percent`)
- First `collect()` call returns a warm-up payload (`warming_up=True`)
- Supports:
  - aggregate or per-core mode (`per_cpu`)
  - `basic` or `detailed` payload detail
  - configurable rounding precision
- Resets to warm-up if CPU entry count changes between polls
- Includes `MonotonicTicker` utility for drift-resistant scheduling

Warm-up behavior is intentional because utilization is derived from differences between consecutive samples.

### Memory Collector

Implementation: `src/collectors/memory.py`

Design highlights:

- Reads:
  - `psutil.virtual_memory()`
  - `psutil.swap_memory()`
- `basic` mode returns a curated field subset
- `detailed` mode returns all discovered psutil fields
- Float values are rounded when configured
- Uses field-name caching to reduce repeated introspection cost

### Disk Collector

Implementation: `src/collectors/disk.py`

Design highlights:

- Uses cumulative counters from `psutil.disk_io_counters(perdisk=True)`
- Filters device names to physical devices only
- Excludes loop/ram/fd and partition-like names
- Produces:
  - `disk_io` (aggregate counters)
  - `disk_io_perdisk` (when `detail="detailed"`)
- Caches filtered device names and refreshes every 12 collects

This collector emits counters, not rates. Rate/derivative calculations are expected downstream.

### Logging Subsystem

Implementation: `src/logger/config.py`

Design highlights:

- Requires `LOG_LOCATION` from:
  - process environment, or
  - repo-root `.env` file
- Fails fast with `RuntimeError` if log path is unavailable/unwritable
- Configures two handlers:
  - file handler (`LOG_FORMAT`, `LOG_DATE_FORMAT`)
  - colored stdout stream handler
- Sets logger level to `DEBUG`
- Disables propagation (`logger.propagate = False`)

## Configuration Resolution

Runtime configuration is handled by `src/config/runtime.py` with one consistent order:

1. process environment
2. repository root `.env`
3. per-setting default (if any)

Current primary settings:

- `LOG_LOCATION` (required)
- `CPU_POLL_INTERVAL_SECONDS` (default `5.0`)
- `EXPORTER_TYPE` (default `console`)

The runtime uses root `.env` as the single dotenv source.

## Data Contracts (Current Output Shape)

CPU (`per_cpu=False`, `detail="detailed"`):

```python
{
  "warming_up": False,
  "percent": 27.31,
  "times_percent": {
    "user": 8.11,
    "system": 4.27,
    "idle": 86.02,
    "iowait": 0.32
  }
}
```

Memory (`detail="detailed"`):

```python
{
  "virtual_memory": {...},
  "swap_memory": {...}
}
```

Disk (`detail="detailed"`):

```python
{
  "disk_io": {
    "read_bytes": ...,
    "write_bytes": ...,
    "read_count": ...,
    "write_count": ...
  },
  "disk_io_perdisk": {
    "sda": {...},
    "nvme0n1": {...}
  }
}
```

## Operational Characteristics

- Scheduling cadence defaults to `5.0` seconds if poll interval is invalid/missing
- Collector loop is single-process, single-threaded
- Runtime overhead is low by design, with most wall-clock time spent sleeping
- Logs are the only output channel today

## Known Gaps and Risks

- No test coverage in `tests/` yet
- No transport/output adapter layer
- No retry/backoff/circuit-breaker behavior (not needed yet because no network sender exists)
- No schema versioning for emitted payloads
- `pyproject.toml` and `Makefile` are placeholders (empty)

## Extension Points

The current architecture is ready for the following incremental additions:

1. Introduce a `sender/` module with backend adapters (Datadog/New Relic/custom)
2. Add in-process normalization/schema module between collectors and sender
3. Add bounded queue + batching/compression before send
4. Add health metrics (loop latency, send success/failure, queue depth)
5. Add automated tests for collector correctness and edge cases

## File Map

- `src/main.py`: startup, configuration parsing, polling loop
- `src/collectors/cpu.py`: CPU collector + monotonic ticker
- `src/collectors/memory.py`: memory collector
- `src/collectors/disk.py`: disk collector
- `src/config/runtime.py`: unified runtime config loading and accessors
- `src/logger/config.py`: logger setup and env-backed log path resolution
