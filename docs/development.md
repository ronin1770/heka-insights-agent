## Development Test Playbook

### OTLP Integration Test Scope

Docker-backed OTLP integration tests live in:

- `tests/test_otlp_http_integration.py`

Collector fixture configurations live in:

- `tests/fixtures/otlp/collector-auth-required.yaml`
- `tests/fixtures/otlp/collector-no-auth.yaml`

### How Containers Are Managed

Integration tests manage collector lifecycle automatically:

1. Start a dedicated collector container per test case.
2. Wait until collector logs report readiness.
3. Run a single OTLP export flow.
4. Stop container in test teardown.

### Running OTLP Integration Tests

Run only integration tests:

```bash
RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest -v tests.test_otlp_http_integration
```

Run all tests including integration:

```bash
RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

By default, integration tests are skipped unless `RUN_OTLP_INTEGRATION=1`.

### Collector Image Override

Default image:

- `otel/opentelemetry-collector-contrib:latest`

Override with:

```bash
OTELCOL_IMAGE=<your-image> RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest -v tests.test_otlp_http_integration
```

Optional integration test base port override:

```bash
OTLP_IT_BASE_PORT=15318 RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest -v tests.test_otlp_http_integration
```

### Failure Troubleshooting

- `docker` missing in `PATH`: tests are skipped.
- port conflicts: set `OTLP_IT_BASE_PORT` to a free range.
- collector image pull issues: pre-pull image manually with `docker pull`.
