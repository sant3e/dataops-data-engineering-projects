"""
Lambda: YouTube Data API Ingestion (Bronze Layer)

Triggered by EventBridge on a schedule. Pulls trending videos and category
reference data from the YouTube Data API v3 for each configured region,
then writes raw JSON to the Bronze S3 bucket.

Paths (Hive-style partitioning):
    Trending:    youtube/raw_statistics/region={region}/date={YYYY-MM-DD}/hour={HH}/{ingestion_id}.json
    Categories:  youtube/raw_statistics_reference_data/region={region}/date={YYYY-MM-DD}/{region}_category_id.json

These live in the same folders as the Kaggle historical upload but nested under
date=/hour= sub-partitions, so Kaggle and API outputs never overwrite each other.

Environment Variables:
    youtube_api_key_secret_arn  — ARN of the Secrets Manager secret holding the Google API key
    s3_bucket_bronze            — Target Bronze S3 bucket name
    youtube_regions             — Comma-separated region codes (e.g., us,gb,ca)
    max_results                 — Number of trending videos per region (default: 50)
    sns_alert_topic_arn         — (Optional) SNS topic ARN for failure alerts
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
sns = boto3.client("sns")
secretsmanager = boto3.client("secretsmanager")

# Read the API key from Secrets Manager at module load time. Lambda container reuse means
# warm invocations skip this network call — the key lives in memory for the lifetime of the
# execution environment. On a rotation, the Lambda needs to be updated/restarted to pick up
# the new value (acceptable for a manually-rotated key; use cache TTL if automatic rotation matters).
API_KEY = secretsmanager.get_secret_value(
    SecretId=os.environ["youtube_api_key_secret_arn"]
)["SecretString"]

BUCKET = os.environ["s3_bucket_bronze"]
REGIONS = [r.strip().lower() for r in os.environ["youtube_regions"].split(",")]
MAX_RESULTS = int(os.environ.get("max_results", "50"))
SNS_TOPIC = os.environ.get("sns_alert_topic_arn", "")

API_BASE = "https://www.googleapis.com/youtube/v3"

# Retry config — YouTube Data API occasionally returns transient 4xx/5xx
# for individual regions. A short retry with backoff recovers most cases.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.5


def _get_json(url):
    """GET a URL with retries on transient HTTP/URL errors."""
    last_error: Exception = RuntimeError("no attempts made")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError) as e:
            last_error = e
            if attempt < MAX_ATTEMPTS:
                sleep_for = BACKOFF_SECONDS * attempt
                logger.warning(
                    f"  Transient error (attempt {attempt}/{MAX_ATTEMPTS}): {e}. "
                    f"Retrying in {sleep_for:.1f}s..."
                )
                time.sleep(sleep_for)
    raise last_error


def fetch_trending(region_code):
    """Fetch current trending videos for a region."""
    params = urlencode({
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "maxResults": MAX_RESULTS,
        "key": API_KEY,
    })
    return _get_json(f"{API_BASE}/videos?{params}")


def fetch_categories(region_code):
    """Fetch video category reference data for a region."""
    params = urlencode({
        "part": "snippet",
        "regionCode": region_code,
        "key": API_KEY,
    })
    return _get_json(f"{API_BASE}/videoCategories?{params}")


def write_json(data, key):
    """Write a JSON payload to the Bronze bucket with ingestion metadata."""
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json",
        Metadata={
            "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "youtube_data_api_v3",
        },
    )


def lambda_handler(event, context):
    now = datetime.now(timezone.utc)
    date_partition = now.strftime("%Y-%m-%d")
    hour_partition = now.strftime("%H")
    ingestion_id = now.strftime("%Y%m%d_%H%M%S")

    results = {"success": [], "failed": []}

    for region in REGIONS:
        logger.info(f"Processing region: {region}")

        # ── Trending videos ──────────────────────────────────────────────
        try:
            trending = fetch_trending(region)
            trending["_pipeline_metadata"] = {
                "ingestion_id": ingestion_id,
                "region": region,
                "ingestion_timestamp": now.isoformat(),
                "video_count": len(trending.get("items", [])),
                "source": "youtube_data_api_v3",
            }

            trending_key = (
                f"youtube/raw_statistics/"
                f"region={region}/"
                f"date={date_partition}/"
                f"hour={hour_partition}/"
                f"{ingestion_id}.json"
            )
            write_json(trending, trending_key)
            logger.info(f"  Wrote {len(trending.get('items', []))} videos → {trending_key}")

        except (HTTPError, URLError) as e:
            logger.error(f"  API error for {region} trending: {e}")
            results["failed"].append({"region": region, "type": "trending", "error": str(e)})
            continue
        except Exception as e:
            logger.error(f"  Unexpected error for {region} trending: {e}")
            results["failed"].append({"region": region, "type": "trending", "error": str(e)})
            continue

        # ── Category reference data ──────────────────────────────────────
        try:
            categories = fetch_categories(region)
            categories["_pipeline_metadata"] = {
                "ingestion_id": ingestion_id,
                "region": region,
                "ingestion_timestamp": now.isoformat(),
                "source": "youtube_data_api_v3",
            }

            categories_key = (
                f"youtube/raw_statistics_reference_data/"
                f"region={region}/"
                f"date={date_partition}/"
                f"{region}_category_id.json"
            )
            write_json(categories, categories_key)
            logger.info(f"  Wrote categories → {categories_key}")

        except (HTTPError, URLError) as e:
            logger.error(f"  API error for {region} categories: {e}")
            results["failed"].append({"region": region, "type": "categories", "error": str(e)})
            continue

        results["success"].append(region)

    summary = (
        f"Ingestion {ingestion_id} complete. "
        f"Success: {len(results['success'])}/{len(REGIONS)} regions. "
        f"Failed: {len(results['failed'])}."
    )
    logger.info(summary)

    if results["failed"] and SNS_TOPIC:
        sns.publish(
            TopicArn=SNS_TOPIC,
            Subject=f"[YT Pipeline] Ingestion partial failure — {ingestion_id}",
            Message=json.dumps(results, indent=2),
        )

    return {"statusCode": 200, "ingestion_id": ingestion_id, "results": results}
