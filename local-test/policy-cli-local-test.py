import argparse
import os
import boto3

endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://dynamodb-local-test:8000")
region = os.getenv("AWS_DEFAULT_REGION", "eu-west-1")
table = os.getenv("ARIZE_ALLOWLIST_TABLE", "otel-arize-enabled-agents-local-test")
ddb = boto3.client("dynamodb", endpoint_url=endpoint, region_name=region)

p = argparse.ArgumentParser(description="Manage the hot Arize/Phoenix agent allow-list")
sub = p.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("add"); a.add_argument("agent_id")
r = sub.add_parser("remove"); r.add_argument("agent_id")
sub.add_parser("list")
args = p.parse_args()

if args.cmd == "add":
    ddb.put_item(TableName=table, Item={"agent_id": {"S": args.agent_id}})
    print(f"Added to Arize allow-list: {args.agent_id}")
elif args.cmd == "remove":
    ddb.delete_item(TableName=table, Key={"agent_id": {"S": args.agent_id}})
    print(f"Removed from Arize allow-list: {args.agent_id}")
else:
    items = ddb.scan(TableName=table, ProjectionExpression="agent_id").get("Items", [])
    ids = sorted(i["agent_id"]["S"] for i in items if "agent_id" in i)
    print("Arize allow-list:")
    for agent_id in ids:
        print(f"- {agent_id}")
    if not ids:
        print("(empty)")
