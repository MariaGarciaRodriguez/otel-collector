# Local test quick start

1. `docker compose -f docker-compose-local-test.yaml up --build`
2. Set archetype: `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
3. Enable Phoenix/Arize logical backend:
   `docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test backend arize on`
4. Allow service:
   `docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test arize-service react-pattern-archetype-mgr on`
5. Wait ~5s and invoke the agent.
6. Open Phoenix at `http://localhost:6006`.
7. Disable without agent restart:
   `docker compose -f docker-compose-local-test.yaml run --rm policy-cli-local-test arize-service react-pattern-archetype-mgr off`

Local defaults are Dynatrace OFF, Agent365 OFF, Arize OFF so no external credentials are required.
