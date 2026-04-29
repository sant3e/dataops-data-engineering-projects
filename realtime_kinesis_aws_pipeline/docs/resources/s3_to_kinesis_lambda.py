import boto3
import json
import csv
import os
from datetime import datetime
from botocore.exceptions import ClientError
from io import StringIO

# ──────────────────────────────────────────────
# Configuration — overridable via Lambda env vars
# (AWS_REGION is a reserved Lambda env var; we read it but don't set it ourselves)
# ──────────────────────────────────────────────
S3_BUCKET      = os.environ.get('S3_BUCKET',      'aqi-pipeline-bucket')
S3_KEY_PREFIX  = os.environ.get('S3_KEY_PREFIX',  'aqi_pipeline/source_data/openaq_location_')
KINESIS_STREAM = os.environ.get('KINESIS_STREAM', 'AQI_Stream')
AWS_REGION     = os.environ.get('AWS_REGION',     'eu-north-1')

s3 = boto3.client('s3', region_name=AWS_REGION)
kinesis = boto3.client('kinesis', region_name=AWS_REGION)


def list_matching_files(bucket, prefix):
    """List all S3 objects whose key starts with the given prefix."""
    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        if 'Contents' not in response:
            print(f"No files found matching pattern: {prefix}* in bucket {bucket}")
            return []
        matching_files = sorted([obj['Key'] for obj in response['Contents']])
        print(f"Found {len(matching_files)} matching files in S3")
        return matching_files
    except ClientError as e:
        print(f"Error listing S3 objects: {e}")
        return []


def read_csv_from_s3(bucket, key):
    """Read a CSV file from S3 and return rows as a list of dictionaries."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        csv_content = response['Body'].read().decode('utf-8')
        reader = csv.DictReader(StringIO(csv_content))

        records = []
        for row in reader:
            records.append({
                'location_id':      row.get('location_id', ''),
                'location_name':    row.get('location_name', ''),
                'parameter_of_AQI': row.get('parameter_of_AQI', ''),
                'value_of_AQI':     row.get('value_of_AQI', ''),
                'unit':             row.get('unit', ''),
                'datetimeUtc':      row.get('datetimeUtc', ''),
                'datetimeLocal':    row.get('datetimeLocal', ''),
                'timezone':         row.get('timezone', ''),
                'latitude':         row.get('latitude', ''),
                'longitude':        row.get('longitude', ''),
                'country_iso':      row.get('country_iso', ''),
                'isMobile':         row.get('isMobile', ''),
                'isMonitor':        row.get('isMonitor', ''),
                'owner_name':       row.get('owner_name', ''),
                'provider':         row.get('provider', '')
            })
        print(f"Read {len(records)} records from {key}")
        return records
    except ClientError as e:
        print(f"Error reading {key}: {e}")
        return []


def send_to_kinesis(records):
    """Send records one by one to Kinesis."""
    success_count = 0
    sequence_number = None

    for i, record in enumerate(records, 1):
        try:
            # Append '\n' so Firehose output becomes NDJSON, which Athena's
            # JsonSerDe parses correctly. Without it, records are concatenated
            # JSON in each S3 file and Athena only sees the first.
            put_args = {
                'StreamName': KINESIS_STREAM,
                'Data': json.dumps(record) + '\n',
                'PartitionKey': record['location_id']
            }
            if sequence_number:
                put_args['SequenceNumberForOrdering'] = sequence_number

            response = kinesis.put_record(**put_args)
            sequence_number = response['SequenceNumber']
            success_count += 1

            if i % 100 == 0 or i == len(records):
                print(f"Sent {i}/{len(records)} records")

        except ClientError as e:
            print(f"Kinesis error on record {i}: {e}")
        except Exception as e:
            print(f"Failed to send record {i}: {e}")

    return success_count


def lambda_handler(event, context):
    """Lambda entry point. Reads all matching CSVs from S3 and pushes to Kinesis."""
    print(f"Starting at {datetime.now().isoformat()}")
    print(f"Reading from s3://{S3_BUCKET}/{S3_KEY_PREFIX}*")

    files = list_matching_files(S3_BUCKET, S3_KEY_PREFIX)
    if not files:
        return {'statusCode': 200, 'body': 'No files found'}

    total_records = 0
    total_success = 0

    for file_key in files:
        print(f"Processing: {file_key}")
        records = read_csv_from_s3(S3_BUCKET, file_key)
        if not records:
            continue

        success_count = send_to_kinesis(records)
        total_records += len(records)
        total_success += success_count

    result = {
        'statusCode': 200,
        'body': {
            'files_processed': len(files),
            'total_records': total_records,
            'successfully_sent': total_success,
            'failed': total_records - total_success
        }
    }
    print(f"Done: {result['body']}")
    return result
