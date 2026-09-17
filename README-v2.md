# Central OpenTelemetry Collector Contrib — backend flags + hot Arize allow-list

## Final policy model

Backend startup flags live in `backend-policy-defaults.yaml`:

```yaml
backends:
  dynatrace:
    enabled: true
  agent365:
    enabled: false
  arize:
    enabled: true
```

DynamoDB is **only** the dynamic Arize allow-list. The table is created at infrastructure startup with PK `agent_id`. An empty table means no agent is exported to Arize. Add an `agent_id` to enable Arize for that agent; delete it to disable Arize again. Dynatrace is unaffected.

The current routing attribute is `service.name`, so until a dedicated resource-level agent ID is standardized, the `agent_id` value stored in DynamoDB must equal the archetype's `OTEL_SERVICE_NAME`.

## Local test

Set real Dynatrace values in `local-test/.env-local-test`, then:

```powershell
cd local-test
docker compose -f docker-compose-local-test.yaml up --build
```

Initial state: Dynatrace ON, Agent365 OFF, Arize pipeline ON but allow-list empty, so Phoenix receives nothing.

List allow-list:

```powershell
docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test list
```

Enable Phoenix/Arize for `react-pattern-archetype-mgr` dynamically:

```powershell
docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test add react-pattern-archetype-mgr
```

Wait up to `ARIZE_ALLOWLIST_REFRESH_SECONDS` (5 s locally), generate a new trace, and it should reach both Dynatrace and Phoenix.

Disable again:

```powershell
docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test remove react-pattern-archetype-mgr
```

No archetype restart or configuration change is required.

## Archetype observability variables

```dotenv
OTEL_SERVICE_NAME=react-pattern-archetype-mgr
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

In AWS, only the Collector endpoint changes. Backend endpoints, tokens, DynamoDB and routing policy stay in the central observability account.
