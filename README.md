# Central Observability Collector — production + local test

## Target architecture

Department/account archetypes send OTLP to one central endpoint. They do not know Dynatrace, Arize,
Phoenix or Microsoft Agent 365 credentials/endpoints. The Collector runs in the separate observability
AWS account.

Backend policy is owned centrally and refreshed from DynamoDB. No DynamoDB query occurs on the telemetry
hot path.

## Backend defaults

Production defaults are in `backend-policy-defaults.yaml`:

- Dynatrace = ON
- Microsoft Agent 365 = OFF (configuration is prepared, but access/integration is not available yet)
- Arize = OFF

DynamoDB overrides these defaults at runtime. Arize additionally requires the sending `service.name` to
be in the Arize allow-list.

Policy table rows:

- `backend#dynatrace` + `enabled BOOL`
- `backend#agent365` + `enabled BOOL`
- `backend#arize` + `enabled BOOL`
- `arize_service#<service.name>` + `enabled BOOL=true`

## Production hot changes

Enable Arize globally:

    aws dynamodb put-item --table-name otel-observability-backend-policy \
      --item '{"policy_key":{"S":"backend#arize"},"enabled":{"BOOL":true}}'

Allow one archetype/service:

    aws dynamodb put-item --table-name otel-observability-backend-policy \
      --item '{"policy_key":{"S":"arize_service#react-pattern-archetype-mgr"},"enabled":{"BOOL":true}}'

Disable that service:

    aws dynamodb delete-item --table-name otel-observability-backend-policy \
      --key '{"policy_key":{"S":"arize_service#react-pattern-archetype-mgr"}}'

Disable Arize globally:

    aws dynamodb put-item --table-name otel-observability-backend-policy \
      --item '{"policy_key":{"S":"backend#arize"},"enabled":{"BOOL":false}}'

The same `backend#...` mechanism can hot-toggle Dynatrace and Agent365. The supervisor polls every 15s,
regenerates/validates the Collector config and sends SIGHUP only when policy changes.

IMPORTANT: this is a Collector configuration reload, not an in-memory dynamic processor update. Use
multiple Collector replicas behind the internal load balancer for production availability.

## Archetype variables

Based on the supplied `react-pattern` `.env.sample`, backend-owned variables must move out of the archetype.
The archetype should retain application identity/instrumentation settings and know only the central OTLP
endpoint.

The supplied `archetype-integration/instrumentation.py` makes `TRACELOOP_BASE_URL` fall back internally to
`OTEL_EXPORTER_OTLP_ENDPOINT`. Therefore the user-facing Collector destination can be a single variable:

    OTEL_EXPORTER_OTLP_ENDPOINT=https://<central-collector>:4318

`OTEL_SERVICE_NAME` remains because it is application identity and is also the Arize allow-list key.
It is not a backend secret or backend endpoint.

Move to the Collector/observability account:

- Dynatrace tenant/connection/token/OTLP variables
- Arize/Phoenix endpoint/API key/space/project variables
- Microsoft Agent365 exporter/authentication variables

## Production build

    docker build -t central-otel-collector .

Use ECS Task Role for DynamoDB access and the approved central secret store for backend secrets.
Do not place AWS static credentials in the image.

## Local test

Everything needed is under `local-test/`. It starts:

- DynamoDB Local
- Phoenix Local (stands in for Arize AX)
- official OTel Collector Contrib + Python supervisor

Local defaults are OFF/OFF/OFF so the test is self-contained and does not contact a real backend.

Start:

    cd local-test
    docker compose -f docker-compose-local-test.yaml up --build

Phoenix UI:

    http://localhost:6006

Collector OTLP/HTTP:

    http://localhost:4318

Point the archetype to:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

Enable the logical Arize backend (which targets Phoenix locally):

    docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test backend arize on

Allow the current service:

    docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test arize-service react-pattern-archetype-mgr on

Wait ~5 seconds, send a new agent request, and the trace should appear in Phoenix.

Disable the service without restarting the archetype:

    docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test arize-service react-pattern-archetype-mgr off

Inspect policy:

    docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test list

Watch Collector/supervisor logs:

    docker logs -f otel-collector-local-test

To test real Dynatrace locally, fill `DT_OTLP_ENDPOINT` and `DT_API_TOKEN` in `.env-local-test`, then run:

    docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test backend dynatrace on

## Microsoft Agent 365 caveat

Agent365 is deliberately OFF. The previous PoC enriched spans in the application and its ingestion endpoint
contains an Agent ID. A single central Collector serving many independent agents therefore needs a final
central identity/routing design before Agent365 can be safely enabled for all departments. This package
keeps the existing exporter/projection prepared but does not move Agent365 credentials back into the
archetype. Do not turn `backend#agent365` ON until that contract is resolved and central credentials are set.
