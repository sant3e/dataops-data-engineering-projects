import json
import csv
import boto3
import io
import os
from datetime import datetime, timezone

# Bucket + prefixes read from env vars (set at deploy time by Terraform/CLI).
S3_BUCKET       = os.environ.get("S3_BUCKET",      "coingecko-etl-bucket")
RAW_TO_PROCESS  = os.environ.get("RAW_TO_PROCESS", "raw_data/to_process/")
RAW_PROCESSED   = os.environ.get("RAW_PROCESSED",  "raw_data/processed/")
TRANSFORMED     = os.environ.get("TRANSFORMED",    "transformed_data/")

s3 = boto3.client("s3")


def get_market_cap_tier(market_cap):
    if market_cap > 100_000_000_000:
        return "Mega"
    elif market_cap > 10_000_000_000:
        return "Large"
    elif market_cap > 1_000_000_000:
        return "Mid"
    return "Small"


def days_since(date_str):
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def transform(raw_data, extracted_at):
    coin_rows, market_rows, price_rows = [], [], []

    for coin in raw_data:
        cid          = coin.get("id")
        market_cap   = coin.get("market_cap") or 0
        total_volume = coin.get("total_volume") or 0
        current      = coin.get("current_price") or 0
        ath          = coin.get("ath") or 0
        high         = coin.get("high_24h") or 0
        low          = coin.get("low_24h") or 0

        coin_rows.append({
            "id":              cid,
            "symbol":          (coin.get("symbol") or "").upper(),
            "name":            (coin.get("name") or "").strip().title(),
            "market_cap_tier": get_market_cap_tier(market_cap),
            "extracted_at":    extracted_at,
        })

        market_rows.append({
            "id":                   cid,
            "market_cap":           market_cap,
            "total_volume":         total_volume,
            "circulating_supply":   coin.get("circulating_supply"),
            "volume_to_mcap_ratio": round(total_volume / market_cap, 6) if market_cap else None,
            "extracted_at":         extracted_at,
        })

        price_rows.append({
            "id":                          cid,
            "current_price":               current,
            "high_24h":                    high,
            "low_24h":                     low,
            "ath":                         ath,
            "ath_date":                    coin.get("ath_date"),
            "price_change_percentage_24h": coin.get("price_change_percentage_24h"),
            "price_to_ath_ratio":          round(current / ath, 4) if ath else None,
            "daily_price_range":           round(high - low, 2),
            "days_since_ath":              days_since(coin.get("ath_date", "")),
            "last_updated":                coin.get("last_updated"),
            "extracted_at":                extracted_at,
        })

    return coin_rows, market_rows, price_rows


def rows_to_csv(rows):
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def write_csv_to_s3(rows, prefix, name, ts):
    key = f"{TRANSFORMED}{prefix}/{name}_{ts}.csv"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=rows_to_csv(rows),
        ContentType="text/csv",
    )
    print(f"Written {len(rows)} rows to s3://{S3_BUCKET}/{key}")
    return key


def move_raw_file(source_key):
    filename = source_key.split("/")[-1]
    dest_key = f"{RAW_PROCESSED}{filename}"
    s3.copy_object(
        Bucket=S3_BUCKET,
        CopySource={"Bucket": S3_BUCKET, "Key": source_key},
        Key=dest_key,
    )
    s3.delete_object(Bucket=S3_BUCKET, Key=source_key)
    print(f"Moved {source_key} -> {dest_key}")


def lambda_handler(event, context):
    response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=RAW_TO_PROCESS)
    objects  = [o for o in response.get("Contents", []) if o["Key"].endswith(".json")]

    if not objects:
        print("No files to process.")
        return {"statusCode": 200, "body": "No files to process."}

    processed_files = []

    for obj in objects:
        source_key = obj["Key"]
        print(f"Processing: {source_key}")

        raw_obj  = s3.get_object(Bucket=S3_BUCKET, Key=source_key)
        raw_data = json.loads(raw_obj["Body"].read().decode("utf-8"))

        ts           = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        extracted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        coin_rows, market_rows, price_rows = transform(raw_data, extracted_at)

        write_csv_to_s3(coin_rows,   "coin_data",   "coin_data",   ts)
        write_csv_to_s3(market_rows, "market_data", "market_data", ts)
        write_csv_to_s3(price_rows,  "price_data",  "price_data",  ts)

        move_raw_file(source_key)
        processed_files.append(source_key)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "files_processed": len(processed_files),
            "files": processed_files,
        }),
    }
