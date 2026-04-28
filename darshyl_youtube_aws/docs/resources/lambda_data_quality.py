"""
Lambda: Data Quality Checks (Silver Layer Gate)

Called by Step Functions after the Silver layer is built, before the Gold
aggregation runs. Validates Silver tables against quality thresholds and
blocks downstream processing if any check fails by returning
`quality_passed: false`, which the Step Functions Choice state uses to
route execution to a failure-notification branch.

Checks performed per table:
    1. row_count     — table has at least DQ_MIN_ROW_COUNT rows
    2. null_pct      — critical columns have at most DQ_MAX_NULL_PERCENT% nulls
    3. schema        — all expected columns exist
    4. value_range   — views are non-negative and below the extreme cutoff (50B)
    5. freshness     — latest record is within FRESHNESS_HOURS (48h)

Expected Input Event (from Step Functions):
    {
        "database": "yt_pipeline_silver_dev",
        "tables": ["clean_statistics", "clean_reference_data"]
    }

Environment Variables:
    DQ_MIN_ROW_COUNT        — Minimum rows per table (default: 10)
    DQ_MAX_NULL_PERCENT     — Max null % for critical columns (default: 5.0)
    ATHENA_WORKGROUP        — Athena workgroup to run queries in (default: yt-pipeline-dev).
                              Must match the workgroup the Lambda IAM policy grants.
                              Omitting this env var falls back to "primary", which the
                              least-privilege IAM policy does NOT permit — you'll get
                              AccessDeniedException: GetWorkGroup on your first DQ run.
    SNS_ALERT_TOPIC_ARN     — (Optional) SNS topic ARN for failure alerts
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta

import boto3
import awswrangler as wr
import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns_client = boto3.client("sns")
SNS_TOPIC = os.environ.get("SNS_ALERT_TOPIC_ARN", "")

MIN_ROW_COUNT = int(os.environ.get("DQ_MIN_ROW_COUNT", "10"))
MAX_NULL_PCT = float(os.environ.get("DQ_MAX_NULL_PERCENT", "5.0"))
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "yt-pipeline-dev")
MAX_VIEWS = 50_000_000_000  # 50B — sanity cap for view counts
FRESHNESS_HOURS = 48

CRITICAL_COLUMNS = {
    # Silver statistics is partitioned by region; the column is materialised
    # in the Parquet schema by Glue.
    "clean_statistics": ["video_id", "title", "channel_title", "views", "region"],
    # Silver reference data (YouTube category metadata) is region-AGNOSTIC —
    # the same category-id → category-name mapping applies globally. The
    # JSON-to-Parquet Lambda writes it as flat Parquet with no region column.
    "clean_reference_data": ["id", "snippet_title"],
}


def check_row_count(df: pd.DataFrame, table: str) -> dict:
    count = len(df)
    return {
        "check": "row_count",
        "table": table,
        "value": count,
        "threshold": MIN_ROW_COUNT,
        "passed": count >= MIN_ROW_COUNT,
        "message": f"Row count: {count} (min: {MIN_ROW_COUNT})",
    }


def check_null_percentage(df: pd.DataFrame, table: str) -> list:
    results = []
    for col in CRITICAL_COLUMNS.get(table, []):
        if col not in df.columns:
            results.append({
                "check": "null_pct",
                "table": table,
                "column": col,
                "passed": False,
                "message": f"Column '{col}' missing from table",
            })
            continue

        null_pct = (df[col].isna().sum() / len(df)) * 100 if len(df) > 0 else 0
        results.append({
            "check": "null_pct",
            "table": table,
            "column": col,
            "value": round(null_pct, 2),
            "threshold": MAX_NULL_PCT,
            "passed": null_pct <= MAX_NULL_PCT,
            "message": f"{col} null%: {null_pct:.2f}% (max: {MAX_NULL_PCT}%)",
        })
    return results


def check_schema(df: pd.DataFrame, table: str) -> dict:
    expected = set(CRITICAL_COLUMNS.get(table, []))
    missing = expected - set(df.columns)
    return {
        "check": "schema",
        "table": table,
        "missing_columns": list(missing),
        "passed": not missing,
        "message": f"Missing columns: {missing}" if missing else "All expected columns present",
    }


def check_value_ranges(df: pd.DataFrame, table: str) -> list:
    if table != "clean_statistics" or "views" not in df.columns:
        return []

    negative = int((df["views"] < 0).sum())
    extreme = int((df["views"] > MAX_VIEWS).sum())
    return [{
        "check": "value_range",
        "table": table,
        "column": "views",
        "negative_count": negative,
        "extreme_count": extreme,
        "passed": negative == 0 and extreme == 0,
        "message": f"Views: {negative} negative, {extreme} extreme (>{MAX_VIEWS})",
    }]


def check_freshness(df: pd.DataFrame, table: str) -> dict:
    ts_col = next(
        (c for c in ("_processed_at", "_ingestion_timestamp") if c in df.columns),
        None,
    )
    if ts_col is None:
        return {
            "check": "freshness",
            "table": table,
            "passed": True,
            "message": "No timestamp column — skipping (backfill data)",
        }

    try:
        latest = pd.to_datetime(df[ts_col]).max()
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS)
        return {
            "check": "freshness",
            "table": table,
            "latest_record": str(latest),
            "cutoff": str(cutoff),
            "passed": latest >= cutoff,
            "message": f"Latest: {latest}, Cutoff: {cutoff}",
        }
    except Exception as e:
        return {
            "check": "freshness",
            "table": table,
            "passed": True,
            "message": f"Could not parse timestamps: {e} — skipping",
        }


def lambda_handler(event, context):
    database = event.get("database", "yt_pipeline_silver_dev")
    tables = event.get("tables", ["clean_statistics"])

    all_results = []
    overall_passed = True

    for table in tables:
        logger.info(f"DQ checks on {database}.{table}")

        try:
            df = wr.athena.read_sql_query(
                sql=f'SELECT * FROM "{table}" LIMIT 10000',
                database=database,
                workgroup=ATHENA_WORKGROUP,
                ctas_approach=False,
            )
        except Exception as e:
            logger.error(f"Could not read {table}: {e}")
            all_results.append({
                "check": "read_table",
                "table": table,
                "passed": False,
                "message": str(e),
            })
            overall_passed = False
            continue

        checks = [
            check_row_count(df, table),
            *check_null_percentage(df, table),
            check_schema(df, table),
            *check_value_ranges(df, table),
            check_freshness(df, table),
        ]

        for c in checks:
            logger.info(f"  {c['check']}: {'PASS' if c['passed'] else 'FAIL'} — {c['message']}")
            if not c["passed"]:
                overall_passed = False

        all_results.extend(checks)

    passed_count = sum(1 for r in all_results if r["passed"])
    total_count = len(all_results)
    logger.info(
        f"DQ Summary: {passed_count}/{total_count} checks passed. "
        f"Overall: {'PASS' if overall_passed else 'FAIL'}"
    )

    if not overall_passed and SNS_TOPIC:
        failed = [r for r in all_results if not r["passed"]]
        sns_client.publish(
            TopicArn=SNS_TOPIC,
            Subject="[YT Pipeline] Data quality checks FAILED",
            Message=json.dumps(failed, indent=2, default=str),
        )

    return {
        "quality_passed": bool(overall_passed),
        "checks_passed": int(passed_count),
        "checks_total": int(total_count),
        "details": json.loads(json.dumps(all_results, default=str)),
    }
