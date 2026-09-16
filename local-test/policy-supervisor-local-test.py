from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import boto3
import yaml
from botocore.config import Config as BotoConfig

LOG = logging.getLogger("otel-policy-supervisor")
TEMPLATE = Path(os.getenv("OTEL_CONFIG_TEMPLATE", "/etc/otelcol-contrib/config.template.yaml"))
ACTIVE = Path(os.getenv("OTEL_CONFIG_ACTIVE", "/var/lib/otel-policy/config.yaml"))
DEFAULTS_FILE = Path(os.getenv("BACKEND_POLICY_DEFAULTS", "/etc/otelcol-contrib/backend-policy-defaults.yaml"))
TABLE = os.getenv("BACKEND_POLICY_TABLE", "otel-observability-backend-policy")
REGION = os.getenv("AWS_REGION", "eu-west-1")
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT")  # local-test only
INTERVAL = int(os.getenv("BACKEND_POLICY_REFRESH_SECONDS", "15"))
ROUTING_ATTRIBUTE = os.getenv("ARIZE_ROUTING_RESOURCE_ATTRIBUTE", "service.name")
OTELCOL = os.getenv("OTELCOL_BINARY", "/usr/local/bin/otelcol-contrib")


@dataclass(frozen=True)
class Policy:
    dynatrace: bool
    agent365: bool
    arize: bool
    arize_services: frozenset[str]


def load_defaults() -> dict[str, bool]:
    raw = yaml.safe_load(DEFAULTS_FILE.read_text(encoding="utf-8")) or {}
    backends = raw.get("backends", {})
    return {
        "dynatrace": bool(backends.get("dynatrace", True)),
        "agent365": bool(backends.get("agent365", False)),
        "arize": bool(backends.get("arize", False)),
    }


def dynamodb_client():
    kwargs = {
        "service_name": "dynamodb",
        "region_name": REGION,
        "config": BotoConfig(
            retries={"max_attempts": 4, "mode": "standard"},
            connect_timeout=3,
            read_timeout=5,
        ),
    }
    if DYNAMODB_ENDPOINT:
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT
    return boto3.client(**kwargs)


def read_policy(ddb, defaults: dict[str, bool]) -> Policy:
    """Read the complete policy table. This runs periodically, never per span."""
    backend = dict(defaults)
    arize_services: set[str] = set()
    args = {"TableName": TABLE, "ConsistentRead": True}

    while True:
        response = ddb.scan(**args)
        for item in response.get("Items", []):
            key = item.get("policy_key", {}).get("S", "")
            enabled = item.get("enabled", {}).get("BOOL", True)

            if key.startswith("backend#"):
                name = key.split("#", 1)[1]
                if name in backend:
                    backend[name] = enabled
            elif key.startswith("arize_service#") and enabled:
                service = key.split("#", 1)[1].strip()
                if service:
                    arize_services.add(service)

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        args["ExclusiveStartKey"] = last_key

    return Policy(
        dynatrace=backend["dynatrace"],
        agent365=backend["agent365"],
        arize=backend["arize"],
        arize_services=frozenset(arize_services),
    )


def arize_drop_condition(services: frozenset[str]) -> str:
    # filterprocessor drops ResourceSpans when the condition evaluates to true.
    if not services:
        return "true"
    key = json.dumps(ROUTING_ATTRIBUTE)
    return " and ".join(
        f"resource.attributes[{key}] != {json.dumps(service)}"
        for service in sorted(services)
    )


def remove_pipeline(config: dict, pipeline_name: str) -> None:
    config.get("service", {}).get("pipelines", {}).pop(pipeline_name, None)


def render_config(policy: Policy, output: Path) -> None:
    config = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

    # Dynatrace carries traces + metrics + logs. Remove the whole backend if OFF.
    if not policy.dynatrace:
        for name in ("traces/dynatrace", "metrics/dynatrace", "logs/dynatrace"):
            remove_pipeline(config, name)
        config.get("exporters", {}).pop("otlphttp/dynatrace", None)

    # Agent 365 is prepared but currently OFF by default.
    if not policy.agent365:
        remove_pipeline(config, "traces/agent365")
        config.get("exporters", {}).pop("otlphttp/agent365", None)
        config.get("extensions", {}).pop("oauth2client/agent365", None)
        extensions = config.get("service", {}).get("extensions", [])
        config["service"]["extensions"] = [x for x in extensions if x != "oauth2client/agent365"]

    # Arize has a global master flag AND a per-service allow-list.
    if not policy.arize:
        remove_pipeline(config, "traces/arize")
        config.get("exporters", {}).pop("otlphttp/arize", None)
    else:
        config["processors"]["filter/arize_allowlist"]["traces"]["resource"] = [
            arize_drop_condition(policy.arize_services)
        ]

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, output)


def validate_config(path: Path) -> None:
    proc = subprocess.run(
        [OTELCOL, "validate", f"--config={path}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "") + (proc.stderr or ""))


def apply_policy(policy: Policy) -> None:
    fd, filename = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    candidate = Path(filename)
    try:
        render_config(policy, candidate)
        validate_config(candidate)
        os.replace(candidate, ACTIVE)
    finally:
        candidate.unlink(missing_ok=True)


def refresh_loop(ddb, defaults, collector, current: Policy, stop: threading.Event):
    while not stop.wait(INTERVAL):
        try:
            new = read_policy(ddb, defaults)
        except Exception:
            LOG.exception("Policy refresh failed; keeping last known good configuration")
            continue
        if new == current:
            continue
        try:
            apply_policy(new)
            collector.send_signal(signal.SIGHUP)
            current = new
            LOG.info(
                "Hot policy applied: dynatrace=%s agent365=%s arize=%s arize_services=%s",
                new.dynatrace, new.agent365, new.arize, sorted(new.arize_services),
            )
        except Exception:
            LOG.exception("New policy was not applied")


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    if INTERVAL < 5:
        raise ValueError("BACKEND_POLICY_REFRESH_SECONDS must be >= 5")

    defaults = load_defaults()
    default_policy = Policy(
        dynatrace=defaults["dynatrace"],
        agent365=defaults["agent365"],
        arize=defaults["arize"],
        arize_services=frozenset(),
    )
    ddb = dynamodb_client()

    # If DynamoDB is unavailable at startup, safe static defaults are used:
    # Dynatrace ON, Agent365 OFF, Arize OFF (as defined in defaults YAML).
    current = default_policy
    try:
        current = read_policy(ddb, defaults)
    except Exception:
        LOG.exception("Initial policy read failed; using collector defaults")

    apply_policy(current)
    LOG.info(
        "Starting Collector: dynatrace=%s agent365=%s arize=%s arize_services=%s",
        current.dynatrace, current.agent365, current.arize, sorted(current.arize_services),
    )

    collector = subprocess.Popen(
        [OTELCOL, f"--config={ACTIVE}"], stdout=sys.stdout, stderr=sys.stderr
    )
    stop = threading.Event()
    worker = threading.Thread(
        target=refresh_loop,
        args=(ddb, defaults, collector, current, stop),
        daemon=True,
    )
    worker.start()

    def shutdown(_signum, _frame):
        stop.set()
        if collector.poll() is None:
            collector.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    rc = collector.wait()
    stop.set()
    worker.join(timeout=5)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
