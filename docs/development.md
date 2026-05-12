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

Run OTLP/HTTP tests with Docker Compose:

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test-runner
```

Run New Relic preset integration tests explicitly:

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

Run all tests including integration:

```bash
RUN_OTLP_INTEGRATION=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

By default, integration tests are skipped unless `RUN_OTLP_INTEGRATION=1`.

New Relic integration auth fixture requirement:

- collector must require header `api-key` with empty scheme
- fixture used by milestone-5 tests is `tests/fixtures/otlp/collector-auth-required-api-key.yaml`

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
