import os
import time
import boto3

endpoint = os.getenv("DYNAMODB_ENDPOINT", "http://dynamodb-local-test:8000")
region = os.getenv("AWS_DEFAULT_REGION", "eu-west-1")
table = os.getenv("ARIZE_ALLOWLIST_TABLE", "otel-arize-enabled-agents-local-test")
ddb = boto3.client("dynamodb", endpoint_url=endpoint, region_name=region)

for _ in range(60):
    try:
        ddb.list_tables()
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError("DynamoDB Local did not become ready")

if table not in ddb.list_tables().get("TableNames", []):
    ddb.create_table(
        TableName=table,
        AttributeDefinitions=[{"AttributeName": "agent_id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "agent_id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    print(f"Created Arize allow-list table: {table}")
else:
    print(f"Arize allow-list table already exists: {table}")
print("Initial allow-list is empty: no agent is exported to Arize/Phoenix until its agent_id is inserted.")
