"""
Glue ETL: Silver → Gold (Analytics Aggregations)

Reads cleansed statistics from Silver, joins them with the cleansed category
reference data for human-readable category names, then produces three
business-level aggregate tables in the Gold layer. All outputs are written
as Snappy-compressed Parquet, partitioned by `region`.

The job is **idempotent**: running it N times with unchanged Silver input
produces the same Gold state. See the "Write mode" section below for why this
matters and how it's implemented.

Paths:
    Input:   <silver_database>.clean_statistics
             <silver_database>.clean_reference_data  (optional; filled with "Unknown" if missing)
    Outputs: s3://<gold_bucket>/youtube/trending_analytics/   → trending_analytics
             s3://<gold_bucket>/youtube/channel_analytics/    → channel_analytics
             s3://<gold_bucket>/youtube/category_analytics/   → category_analytics

Gold Tables Produced:
    1. trending_analytics   — Daily trending summaries per region
    2. channel_analytics    — Channel performance metrics with rank_in_region
    3. category_analytics   — Category-level trends over time with view_share_pct

Write mode (idempotency):
    This job uses Spark's DataFrameWriter with `mode("overwrite")` plus the
    `spark.sql.sources.partitionOverwriteMode = dynamic` config. That means:
      - Every Gold partition emitted by this run REPLACES the corresponding
        partition on S3 atomically (Spark writes to a staging dir then commits).
      - Partitions not emitted by this run are LEFT ALONE (dynamic semantics),
        so a run that only processes `region=us` doesn't wipe `region=ca`.
      - Partial failures leave the previous Gold state intact — the driver only
        commits when all workers succeed.
    Contrast with `glueContext.getSink()` (the Glue DynamicFrame sink), which
    has no mode parameter and defaults to APPEND — every run would add new
    Parquet files alongside existing ones, and Athena would double-count every
    run. That default made this job non-idempotent in the previous version.

Catalog registration:
    This script NO LONGER registers tables in the Glue Catalog directly —
    Spark writes Parquet to S3, then the Step Functions workflow runs a
    dedicated Gold crawler as the next state. See Step 13.4 / Step 14 in
    aws_pipeline.md. Running the crawler as a separate state keeps the ETL
    job's responsibilities narrow and lets the catalog refresh fail (or be
    retried) independently of the compute.

Job Parameters (set in Glue console → "Job details → Job parameters"):
    --JOB_NAME              — automatic, supplied by Glue
    --silver_database        — e.g. yt_pipeline_silver_dev
    --gold_bucket            — e.g. yt-data-pipeline-gold-<ACCOUNT_ID>-dev
"""

import sys

from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# ── Job Setup ─────────────────────────────────────────────────────────────
args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "silver_database",
    "gold_bucket",
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)
logger = glueContext.get_logger()

# Dynamic partition overwrite — per-partition atomic replace, not whole-table wipe.
# Required for the idempotency guarantee described in the module docstring.
spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")

SILVER_DB = args["silver_database"]
GOLD_BUCKET = args["gold_bucket"]

# ── Read Silver Statistics ────────────────────────────────────────────────
logger.info("Reading Silver: clean_statistics")
stats_df = (
    glueContext
    .create_dynamic_frame.from_catalog(
        database=SILVER_DB,
        table_name="clean_statistics",
        transformation_ctx="stats",
    )
    .toDF()
)
logger.info(f"Statistics records: {stats_df.count()}")

# ── Read Silver Reference Data (optional join for category names) ─────────
try:
    ref_df = (
        glueContext
        .create_dynamic_frame.from_catalog(
            database=SILVER_DB,
            table_name="clean_reference_data",
            transformation_ctx="ref",
        )
        .toDF()
    )

    # Different crawlers flatten nested fields differently; handle common cases.
    title_col = None
    if "snippet.title" in ref_df.columns:
        title_col = F.col("`snippet.title`")
    elif "snippet_title" in ref_df.columns:
        title_col = F.col("snippet_title")

    if "id" in ref_df.columns and title_col is not None:
        category_lookup = (
            ref_df
            .select(F.col("id").cast("long").alias("category_id"),
                    title_col.alias("category_name"))
            .dropDuplicates(["category_id"])
        )
        logger.info(f"Category lookup entries: {category_lookup.count()}")

        if "category_id" in stats_df.columns:
            stats_df = stats_df.withColumn(
                "category_id", F.col("category_id").cast("long")
            )

        stats_df = stats_df.join(
            F.broadcast(category_lookup), on="category_id", how="left",
        )
    else:
        logger.warn(
            f"Reference data missing expected columns. Columns: {ref_df.columns}"
        )

except Exception as e:
    logger.warn(f"Could not load reference data: {e}. Proceeding without category names.")

# Guarantee category_name exists so aggregations don't fail.
if "category_name" not in stats_df.columns:
    stats_df = stats_df.withColumn("category_name", F.lit("Unknown"))
else:
    stats_df = stats_df.fillna("Unknown", subset=["category_name"])

# ── Derived columns ───────────────────────────────────────────────────────
# The trainer-style Bronze→Silver script (ApplyMapping/ResolveChoice/DropNullFields)
# passes `trending_date`, `views`, `likes`, `dislikes`, `comment_count` through
# unchanged. The Gold aggregations below reference `trending_date_parsed`,
# `like_ratio`, and `engagement_rate` — derive them here so Silver stays
# minimal and this job remains self-contained.
#
# Kaggle `trending_date` format is `YY.DD.MM` (e.g. `17.14.11` = 2017-11-14).
# Spark's to_date with pattern 'yy.dd.MM' handles that correctly.
stats_df = (
    stats_df
    .withColumn("trending_date_parsed", F.to_date(F.col("trending_date"), "yy.dd.MM"))
    .withColumn(
        "like_ratio",
        F.when(
            (F.col("likes") + F.col("dislikes")) > 0,
            F.col("likes") / (F.col("likes") + F.col("dislikes")),
        ).otherwise(F.lit(None).cast("double")),
    )
    .withColumn(
        "engagement_rate",
        F.when(
            F.col("views") > 0,
            (F.col("likes") + F.col("dislikes") + F.col("comment_count")) / F.col("views"),
        ).otherwise(F.lit(None).cast("double")),
    )
)


# ── Helper: write a Spark DataFrame as a Gold table ───────────────────────
def write_gold(df, table_name, partition_keys=("region",)):
    """
    Write a Gold aggregate table as partitioned Parquet with atomic per-partition
    overwrite semantics. Does NOT register the table in the Glue Catalog —
    that's the Gold crawler's job (next state in the Step Functions workflow).

    Why DataFrameWriter (not glueContext.getSink):
        getSink() / write_dynamic_frame.from_options() default to APPEND mode
        with no option to override. Running this job twice with the same Silver
        input would write a second set of Parquet files alongside the first,
        and Athena's SELECT SUM(...) would double-count every metric on re-run.
        DataFrameWriter.mode("overwrite") + partitionOverwriteMode=dynamic
        gives us "running twice = running once" as a hard guarantee.
    """
    path = f"s3://{GOLD_BUCKET}/youtube/{table_name}/"
    (
        df.write
        .mode("overwrite")
        .partitionBy(*partition_keys)
        .parquet(path, compression="snappy")
    )
    logger.info(f"  Wrote {df.count()} rows → {path} (overwrite, partitioned by {partition_keys})")


# ── Gold 1: trending_analytics ────────────────────────────────────────────
logger.info("Building Gold: trending_analytics")
trending = (
    stats_df.groupBy("region", "trending_date_parsed")
    .agg(
        F.count("video_id").alias("total_videos"),
        F.sum("views").alias("total_views"),
        F.sum("likes").alias("total_likes"),
        F.sum("dislikes").alias("total_dislikes"),
        F.sum("comment_count").alias("total_comments"),
        F.avg("views").alias("avg_views_per_video"),
        F.avg("like_ratio").alias("avg_like_ratio"),
        F.avg("engagement_rate").alias("avg_engagement_rate"),
        F.max("views").alias("max_views"),
        F.countDistinct("channel_title").alias("unique_channels"),
        F.countDistinct("category_id").alias("unique_categories"),
    )
    .withColumn("_aggregated_at", F.current_timestamp())
)
write_gold(trending, "trending_analytics")

# ── Gold 2: channel_analytics ─────────────────────────────────────────────
logger.info("Building Gold: channel_analytics")
channel = (
    stats_df.groupBy("channel_title", "region")
    .agg(
        F.countDistinct("video_id").alias("total_videos"),
        F.sum("views").alias("total_views"),
        F.sum("likes").alias("total_likes"),
        F.sum("comment_count").alias("total_comments"),
        F.avg("views").alias("avg_views_per_video"),
        F.avg("engagement_rate").alias("avg_engagement_rate"),
        F.max("views").alias("peak_views"),
        F.count("trending_date_parsed").alias("times_trending"),
        F.min("trending_date_parsed").alias("first_trending"),
        F.max("trending_date_parsed").alias("last_trending"),
        F.collect_set("category_name").alias("categories"),
    )
)
# Rank channels by total_views within each region.
rank_window = Window.partitionBy("region").orderBy(F.col("total_views").desc())
channel = (
    channel.withColumn("rank_in_region", F.row_number().over(rank_window))
    .withColumn("_aggregated_at", F.current_timestamp())
)
write_gold(channel, "channel_analytics")

# ── Gold 3: category_analytics ────────────────────────────────────────────
logger.info("Building Gold: category_analytics")
category = (
    stats_df.groupBy("category_name", "category_id", "region", "trending_date_parsed")
    .agg(
        F.count("video_id").alias("video_count"),
        F.sum("views").alias("total_views"),
        F.sum("likes").alias("total_likes"),
        F.sum("comment_count").alias("total_comments"),
        F.avg("engagement_rate").alias("avg_engagement_rate"),
        F.countDistinct("channel_title").alias("unique_channels"),
    )
)
# Category share of views per region per day.
total_window = Window.partitionBy("region", "trending_date_parsed")
category = (
    category.withColumn(
        "view_share_pct",
        F.round(F.col("total_views") / F.sum("total_views").over(total_window) * 100, 2),
    )
    .withColumn("_aggregated_at", F.current_timestamp())
)
write_gold(category, "category_analytics")

logger.info("Gold layer build complete. Gold crawler (next state) will refresh the catalog.")
job.commit()
