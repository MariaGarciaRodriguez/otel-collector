# Minimal archetype integration

Replace `src/observability/instrumentation.py` with the supplied version (or apply the same small fallback).
It derives `TRACELOOP_BASE_URL` internally from `OTEL_EXPORTER_OTLP_ENDPOINT`, so the user does not need
a second Collector endpoint variable.

Keep application identity (`OTEL_SERVICE_NAME`, `AGENT_NAME`) because it identifies telemetry; it is not
a backend credential/configuration. Remove Collector/backend variables from the archetype `.env.sample`:

- `DT_TENANT`, `DT_CONNECTION_POINT`, `DT_TENANT_TOKEN`, `DT_OTLP_ENDPOINT`, `DT_API_TOKEN`, `DT_TAGS`
- `PHOENIX_OTLP_ENDPOINT`, `PHOENIX_PROJECT_NAME`
- Arize endpoint/API key/space/project variables
- Agent365 tenant/client secret/exporter endpoint variables while Agent365 is centrally disabled

The user-facing destination is only `OTEL_EXPORTER_OTLP_ENDPOINT` (plus protocol if you do not hard-code it).
