import argparse, os, boto3
endpoint=os.getenv('DYNAMODB_ENDPOINT','http://dynamodb-local-test:8000')
region=os.getenv('AWS_DEFAULT_REGION','eu-west-1')
table=os.getenv('BACKEND_POLICY_TABLE','otel-observability-backend-policy-local-test')
ddb=boto3.client('dynamodb',endpoint_url=endpoint,region_name=region)

p=argparse.ArgumentParser()
sub=p.add_subparsers(dest='cmd',required=True)
b=sub.add_parser('backend'); b.add_argument('name',choices=['dynatrace','agent365','arize']); b.add_argument('state',choices=['on','off'])
a=sub.add_parser('arize-service'); a.add_argument('service_name'); a.add_argument('state',choices=['on','off'])
sub.add_parser('list')
args=p.parse_args()

if args.cmd=='backend':
    ddb.put_item(TableName=table,Item={'policy_key':{'S':f'backend#{args.name}'},'enabled':{'BOOL':args.state=='on'}})
    print(f'{args.name}={args.state}')
elif args.cmd=='arize-service':
    key={'policy_key':{'S':f'arize_service#{args.service_name}'}}
    if args.state=='on': ddb.put_item(TableName=table,Item={**key,'enabled':{'BOOL':True}})
    else: ddb.delete_item(TableName=table,Key=key)
    print(f'Arize service {args.service_name}={args.state}')
else:
    for item in ddb.scan(TableName=table).get('Items',[]): print(item)
