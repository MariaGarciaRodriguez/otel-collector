FROM otel/opentelemetry-collector-contrib:0.132.0 AS otel
FROM python:3.12-slim

RUN useradd --system --uid 10001 --create-home otel \
    && mkdir -p /etc/otelcol-contrib /var/lib/otel-policy \
    && chown -R otel:otel /etc/otelcol-contrib /var/lib/otel-policy

COPY --from=otel /otelcol-contrib /usr/local/bin/otelcol-contrib
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY policy_supervisor.py /app/policy_supervisor.py
COPY collector-config.template.yaml /etc/otelcol-contrib/config.template.yaml
COPY backend-policy-defaults.yaml /etc/otelcol-contrib/backend-policy-defaults.yaml
USER otel
EXPOSE 4317 4318 13133
ENTRYPOINT ["python", "/app/policy_supervisor.py"]
