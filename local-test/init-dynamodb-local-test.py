import os, time, boto3
endpoint=os.getenv('DYNAMODB_ENDPOINT','http://dynamodb-local-test:8000')
region=os.getenv('AWS_DEFAULT_REGION','eu-west-1')
table=os.getenv('BACKEND_POLICY_TABLE','otel-observability-backend-policy-local-test')
ddb=boto3.client('dynamodb',endpoint_url=endpoint,region_name=region)
for _ in range(60):
    try:
        ddb.list_tables(); break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError('DynamoDB Local did not become ready')
if table not in ddb.list_tables().get('TableNames',[]):
    ddb.create_table(
        TableName=table,
        AttributeDefinitions=[{'AttributeName':'policy_key','AttributeType':'S'}],
        KeySchema=[{'AttributeName':'policy_key','KeyType':'HASH'}],
        BillingMode='PAY_PER_REQUEST',
    )
print(f'Ready: {table}. No overrides inserted; local defaults remain OFF/OFF/OFF.')
