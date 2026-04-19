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

The project uses a `.env` file for runtime configuration.

Example:

```env
CPU_POLL_INTERVAL_SECONDS=10
````

### Current Environment Variable

#### `CPU_POLL_INTERVAL_SECONDS`

Defines how often the CPU collector should poll and emit CPU usage data.

Example:

```env
CPU_POLL_INTERVAL_SECONDS=10
```

This means the agent will collect CPU metrics every **10 seconds**.

You should keep this value:

* low enough for useful monitoring resolution
* high enough to avoid unnecessary system overhead

For local development, copy the example file if needed:

```bash
cp .env.example .env
```

Then update the value inside `.env` as required.

```
```


### Run the application

Depending on your entrypoint setup:

```bash
python main.py
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