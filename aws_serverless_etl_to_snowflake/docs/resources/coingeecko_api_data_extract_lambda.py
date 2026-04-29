import json
import boto3
import os
import urllib.request
from datetime import datetime, timezone

# Bucket + prefix read from env vars (set at deploy time by Terraform/CLI).
S3_BUCKET = os.environ.get("S3_BUCKET", "coingecko-etl-bucket")
S3_PREFIX = os.environ.get("S3_PREFIX", "raw_data/to_process/")


def lambda_handler(event, context):
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"
    )

    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{S3_PREFIX}coingecko_raw_{ts}.json"

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=filename,
        Body=json.dumps(data, indent=2),
        ContentType="application/json",
    )

    print(f"Written {len(data)} records to s3://{S3_BUCKET}/{filename}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "records_written": len(data),
            "s3_path": f"s3://{S3_BUCKET}/{filename}",
        }),
    }
