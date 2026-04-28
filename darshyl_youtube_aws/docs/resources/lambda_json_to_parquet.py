"""
Lambda: JSON-to-Parquet (Bronze → Silver Reference Data)

Triggered by an S3 object-created event on the Bronze bucket whenever a new
reference-data JSON lands. Reads the JSON, flattens the nested `items` array
into a tabular DataFrame, writes it as Parquet to the Silver bucket, and
registers/updates the target table in the Silver Glue Catalog in a single
call via awswrangler.

Trigger: s3:ObjectCreated:* on prefix `youtube/raw_statistics_reference_data/`

Paths:
    Input:   s3://<bronze_bucket>/youtube/raw_statistics_reference_data/region=xx/.../*.json
    Output:  configured via the `s3_cleansed_layer` env var, e.g.
             s3://<silver_bucket>/youtube/reference_data/

Environment Variables:
    s3_cleansed_layer             — Target S3 path for the Parquet output (Silver)
    glue_catalog_db_name          — Silver Glue database to register the table in
    glue_catalog_table_name       — Table name to create/update in the catalog
    write_data_operation          — awswrangler write mode (append | overwrite | overwrite_partitions)

Note on JSON parsing:
    The YouTube Data API v3 `videoCategories.list` response is a nested JSON
    object with top-level scalar fields (`kind`, `etag`) alongside an `items`
    array and a `pageInfo` dict. Using `wr.s3.read_json()` or `pd.read_json()`
    directly on this shape raises:
        ValueError: Mixing dicts with non-Series may lead to ambiguous ordering.
    Pandas's JSON parser tries to coerce the mixed-type top level into
    DataFrame columns and fails.

    The fix is to fetch the raw bytes with boto3 and parse them with the
    stdlib `json` module first, then hand the `items` list to
    `pd.json_normalize()` — which is what actually produces the tabular
    DataFrame we want in Silver. This also skirts `ujson` quirks in
    awswrangler's read path.
"""

import json
import os
import urllib.parse

import awswrangler as wr
import boto3
import pandas as pd

os_input_s3_cleansed_layer = os.environ['s3_cleansed_layer']
os_input_glue_catalog_db_name = os.environ['glue_catalog_db_name']
os_input_glue_catalog_table_name = os.environ['glue_catalog_table_name']
os_input_write_data_operation = os.environ['write_data_operation']
# Bronze bucket to scan when invoked directly (e.g. from Step Functions) with no S3 event.
os_input_bronze_bucket = os.environ.get('bronze_bucket', '')

s3_client = boto3.client('s3')


def _process_one(bucket, key):
    """Read one JSON file from Bronze, flatten items[], write Parquet to Silver,
    register in Glue Catalog. Returns the awswrangler response dict, or a
    {'status': 'skipped', ...} dict if the file has no items."""
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    payload = json.loads(resp['Body'].read())

    # `items` is the list of video-category records; everything else at the
    # top level (kind, etag, pageInfo) is API envelope metadata we don't
    # want in the Silver table.
    items = payload.get('items', [])
    if not items:
        print('No items in {}/{} — skipping'.format(bucket, key))
        return {'status': 'skipped', 'reason': 'empty items array', 'key': key}

    df = pd.json_normalize(items)

    # Write Parquet to Silver + register/update in the Glue Catalog in
    # one awswrangler call.
    return wr.s3.to_parquet(
        df=df,
        path=os_input_s3_cleansed_layer,
        dataset=True,
        database=os_input_glue_catalog_db_name,
        table=os_input_glue_catalog_table_name,
        mode=os_input_write_data_operation,
    )


def _list_reference_data_keys(bucket):
    """Step Functions invokes this Lambda directly without an S3 event payload.
    In that case, fan out across every reference-data JSON that currently
    exists under the Bronze prefix, so the orchestrated pipeline processes
    whatever the YouTube API Lambda just wrote upstream."""
    paginator = s3_client.get_paginator('list_objects_v2')
    keys = []
    for page in paginator.paginate(
        Bucket=bucket,
        Prefix='youtube/raw_statistics_reference_data/',
    ):
        for obj in page.get('Contents', []) or []:
            if obj['Key'].endswith('.json'):
                keys.append(obj['Key'])
    return keys


def lambda_handler(event, context):
    # Detect invocation source.
    # Case 1: S3 event notification — event has a Records array with s3 metadata.
    # Case 2: Direct invocation (Step Functions, manual test) — no Records array;
    #         fan out across all reference-data JSONs in the Bronze bucket.
    if isinstance(event, dict) and 'Records' in event:
        # S3 event — single file, triggered by ObjectCreated on the Bronze bucket
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = urllib.parse.unquote_plus(
            event['Records'][0]['s3']['object']['key'], encoding='utf-8'
        )
        print(f'S3-event invocation: processing {bucket}/{key}')
        try:
            return _process_one(bucket, key)
        except Exception as e:
            print(f'Error processing {bucket}/{key}: {e}')
            raise

    # Direct invocation (Step Functions or manual test).
    # Requires `bronze_bucket` env var to know where to scan.
    bucket = os_input_bronze_bucket
    if not bucket:
        raise RuntimeError(
            'Direct invocation requires the `bronze_bucket` environment '
            'variable to be set (so the Lambda knows where to scan for '
            'reference-data JSONs). Set it to your Bronze bucket name, e.g. '
            'yt-data-pipeline-bronze-<ACCOUNT_ID>-dev.'
        )

    keys = _list_reference_data_keys(bucket)
    print(f'Direct invocation: found {len(keys)} reference-data JSONs in s3://{bucket}/youtube/raw_statistics_reference_data/')

    processed = 0
    skipped = 0
    failed = []
    for key in keys:
        try:
            result = _process_one(bucket, key)
            if isinstance(result, dict) and result.get('status') == 'skipped':
                skipped += 1
            else:
                processed += 1
        except Exception as e:
            print(f'FAILED on {key}: {e}')
            failed.append({'key': key, 'error': str(e)})

    summary = {
        'invocation_mode': 'direct',
        'processed': processed,
        'skipped': skipped,
        'failed_count': len(failed),
        'total_keys': len(keys),
    }
    if failed:
        summary['failed'] = failed[:10]  # cap to avoid bloating SFN state payload
        # Raise so Step Functions treats this as a failure (and routes to NotifyTransformFailure)
        raise RuntimeError(f'JSON-to-Parquet: {len(failed)} of {len(keys)} reference JSONs failed. First: {failed[0]}')

    print(f'Done: {summary}')
    return summary


