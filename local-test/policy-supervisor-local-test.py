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
BACKEND_CONFIG = Path(os.getenv("BACKEND_CONFIG", "/etc/otelcol-contrib/backend-policy-defaults.yaml"))
TABLE = os.getenv("ARIZE_ALLOWLIST_TABLE", "otel-arize-enabled-agents")
REGION = os.getenv("AWS_REGION", "eu-west-1")
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT")
INTERVAL = int(os.getenv("ARIZE_ALLOWLIST_REFRESH_SECONDS", "15"))
ROUTING_ATTRIBUTE = os.getenv("ARIZE_ROUTING_RESOURCE_ATTRIBUTE", "service.name")
OTELCOL = os.getenv("OTELCOL_BINARY", "/usr/local/bin/otelcol-contrib")


@dataclass(frozen=True)
class BackendConfig:
    dynatrace: bool
    agent365: bool
    arize: bool


def load_backend_config() -> BackendConfig:
    raw = yaml.safe_load(BACKEND_CONFIG.read_text(encoding="utf-8")) or {}
    b = raw.get("backends", {})
    def enabled(name: str, default: bool) -> bool:
        value = b.get(name, default)
        if isinstance(value, dict):
            return bool(value.get("enabled", default))
        return bool(value)
    return BackendConfig(
        dynatrace=enabled("dynatrace", True),
        agent365=enabled("agent365", False),
        arize=enabled("arize", True),
    )


def dynamodb_client():
    kwargs = {
        "service_name": "dynamodb",
        "region_name": REGION,
        "config": BotoConfig(retries={"max_attempts": 4, "mode": "standard"}, connect_timeout=3, read_timeout=5),
    }
    if DYNAMODB_ENDPOINT:
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT
    return boto3.client(**kwargs)


def read_arize_allowlist(ddb) -> frozenset[str]:
    """Read agent IDs from DynamoDB. Presence means Arize ON for that agent."""
    agents: set[str] = set()
    args = {"TableName": TABLE, "ProjectionExpression": "agent_id", "ConsistentRead": True}
    while True:
        response = ddb.scan(**args)
        for item in response.get("Items", []):
            agent_id = item.get("agent_id", {}).get("S", "").strip()
            if agent_id:
                agents.add(agent_id)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        args["ExclusiveStartKey"] = last_key
    return frozenset(agents)


def arize_drop_condition(agent_ids: frozenset[str]) -> str:
    # filterprocessor drops ResourceSpans when true. Empty allow-list => drop all.
    if not agent_ids:
        return "true"
    key = json.dumps(ROUTING_ATTRIBUTE)
    return " and ".join(
        f"resource.attributes[{key}] != {json.dumps(agent_id)}"
        for agent_id in sorted(agent_ids)
    )


def remove_pipeline(config: dict, pipeline_name: str) -> None:
    config.get("service", {}).get("pipelines", {}).pop(pipeline_name, None)


def render_config(backends: BackendConfig, allowlist: frozenset[str], output: Path) -> None:
    config = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

    if not backends.dynatrace:
        for name in ("traces/dynatrace", "metrics/dynatrace", "logs/dynatrace"):
            remove_pipeline(config, name)
        config.get("exporters", {}).pop("otlphttp/dynatrace", None)

    if not backends.agent365:
        remove_pipeline(config, "traces/agent365")
        config.get("exporters", {}).pop("otlphttp/agent365", None)
        config.get("extensions", {}).pop("oauth2client/agent365", None)
        extensions = config.get("service", {}).get("extensions", [])
        config["service"]["extensions"] = [x for x in extensions if x != "oauth2client/agent365"]

    if not backends.arize:
        remove_pipeline(config, "traces/arize")
        config.get("exporters", {}).pop("otlphttp/arize", None)
    else:
        config["processors"]["filter/arize_allowlist"]["traces"]["resource"] = [arize_drop_condition(allowlist)]

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, output)


def validate_config(path: Path) -> None:
    proc = subprocess.run([OTELCOL, "validate", f"--config={path}"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "") + (proc.stderr or ""))


def apply_config(backends: BackendConfig, allowlist: frozenset[str]) -> None:
    fd, filename = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    candidate = Path(filename)
    try:
        render_config(backends, allowlist, candidate)
        validate_config(candidate)
        os.replace(candidate, ACTIVE)
    finally:
        candidate.unlink(missing_ok=True)


def refresh_loop(ddb, backends: BackendConfig, collector, current: frozenset[str], stop: threading.Event):
    while not stop.wait(INTERVAL):
        try:
            new = read_arize_allowlist(ddb)
        except Exception:
            LOG.exception("Arize allow-list refresh failed; keeping last known good configuration")
            continue
        if new == current:
            continue
        try:
            apply_config(backends, new)
            collector.send_signal(signal.SIGHUP)
            current = new
            LOG.info("Hot Arize allow-list applied: %s", sorted(new))
        except Exception:
            LOG.exception("New Arize allow-list was not applied")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    if INTERVAL < 5:
        raise ValueError("ARIZE_ALLOWLIST_REFRESH_SECONDS must be >= 5")

    backends = load_backend_config()
    ddb = dynamodb_client()
    allowlist: frozenset[str] = frozenset()
    if backends.arize:
        try:
            allowlist = read_arize_allowlist(ddb)
        except Exception:
            LOG.exception("Initial Arize allow-list read failed; failing closed (no agents exported to Arize)")

    apply_config(backends, allowlist)
    LOG.info("Starting Collector: dynatrace=%s agent365=%s arize=%s arize_allowlist=%s", backends.dynatrace, backends.agent365, backends.arize, sorted(allowlist))

    collector = subprocess.Popen([OTELCOL, f"--config={ACTIVE}"], stdout=sys.stdout, stderr=sys.stderr)
    stop = threading.Event()
    worker = threading.Thread(target=refresh_loop, args=(ddb, backends, collector, allowlist, stop), daemon=True)
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
