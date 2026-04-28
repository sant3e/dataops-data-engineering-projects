"""
Glue ETL: Bronze → Silver (Statistics Data)

Mirrors the trainer's original PySpark job at
https://github.com/darshilparmar/dataengineering-youtube-analysis-project/blob/main/pyspark_code.py
with minor adaptations:

  * Parameterized (via --bronze_database / --bronze_table / --silver_bucket
    / --silver_database / --silver_table) instead of hardcoded paths/names
    so the script is reusable across environments.
  * No sys.exit(0) anywhere — Glue 5.0's exception analyser treats any
    SystemExit (even code 0) as a job failure, routing Step Functions to
    NotifyTransformFailure even when the job is conceptually a no-op.

Design — why DynamicFrames, not DataFrames:
    The Bronze `raw_statistics` table sits on a prefix that contains BOTH
    Kaggle CSVs (region=xx/*.csv) AND YouTube API JSONs nested deeper
    (region=xx/date=YYYY-MM-DD/hour=HH/*.json). The Bronze crawler was run
    once on the Kaggle-only state (see Step 8's ordering warning), so the
    catalog schema only advertises CSV columns — but when Glue reads the
    table it serves both file shapes against that schema.

    Trying to do this with Spark DataFrames breaks: `F.col("video_id")`
    throws `UNRESOLVED_COLUMN` when JSON rows are in scope because the
    JSON top level has no `video_id`. Glue's DynamicFrame API handles this
    gracefully via ChoiceType — when a column exists in some rows but not
    others, it's stored as a Choice, and `ResolveChoice(make_struct)` /
    `DropNullFields` collapse those into a consistent schema.

Job Parameters (set in Glue console → Job details → Job parameters):
    --JOB_NAME           — automatic, supplied by Glue
    --bronze_database    — e.g. yt_pipeline_bronze_dev
    --bronze_table       — e.g. raw_statistics
    --silver_bucket      — e.g. yt-data-pipeline-silver-<ACCOUNT_ID>-dev
    --silver_database    — e.g. yt_pipeline_silver_dev
    --silver_table       — e.g. clean_statistics
"""

import sys

from awsglue.transforms import ApplyMapping, ResolveChoice, DropNullFields
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame


# ── Job Setup ─────────────────────────────────────────────────────────────
args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "bronze_database",
    "bronze_table",
    "silver_bucket",
    "silver_database",
    "silver_table",
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)
logger = glueContext.get_logger()

BRONZE_DB = args["bronze_database"]
BRONZE_TABLE = args["bronze_table"]
SILVER_BUCKET = args["silver_bucket"]
SILVER_DB = args["silver_database"]
SILVER_TABLE = args["silver_table"]
SILVER_PATH = f"s3://{SILVER_BUCKET}/youtube/statistics/"

logger.info(f"Bronze: {BRONZE_DB}.{BRONZE_TABLE}")
logger.info(f"Silver: {SILVER_DB}.{SILVER_TABLE} → {SILVER_PATH}")

# ── Step 1: Read from Bronze ──────────────────────────────────────────────
# Predicate pushdown — only process the regions we care about.
predicate_pushdown = "region in ('ca', 'gb', 'us', 'in')"

datasource0 = glueContext.create_dynamic_frame.from_catalog(
    database=BRONZE_DB,
    table_name=BRONZE_TABLE,
    transformation_ctx="datasource0",
    push_down_predicate=predicate_pushdown,
)

# ── Step 2: Schema mapping ────────────────────────────────────────────────
# ApplyMapping casts columns to their Silver types. Missing columns on a
# given row (from the mixed CSV+JSON prefix) are tolerated — the output has
# NULL for them, which DropNullFields will handle later.
applymapping1 = ApplyMapping.apply(
    frame=datasource0,
    mappings=[
        ("video_id", "string", "video_id", "string"),
        ("trending_date", "string", "trending_date", "string"),
        ("title", "string", "title", "string"),
        ("channel_title", "string", "channel_title", "string"),
        ("category_id", "long", "category_id", "long"),
        ("publish_time", "string", "publish_time", "string"),
        ("tags", "string", "tags", "string"),
        ("views", "long", "views", "long"),
        ("likes", "long", "likes", "long"),
        ("dislikes", "long", "dislikes", "long"),
        ("comment_count", "long", "comment_count", "long"),
        ("thumbnail_link", "string", "thumbnail_link", "string"),
        ("comments_disabled", "boolean", "comments_disabled", "boolean"),
        ("ratings_disabled", "boolean", "ratings_disabled", "boolean"),
        ("video_error_or_removed", "boolean", "video_error_or_removed", "boolean"),
        ("description", "string", "description", "string"),
        ("region", "string", "region", "string"),
    ],
    transformation_ctx="applymapping1",
)

# ── Step 3: Resolve ambiguous types ───────────────────────────────────────
# When a column has mixed types across rows (e.g. `views` parsed as both
# string and long across CSV vs. JSON rows), ApplyMapping surfaces that as
# a Choice type. `make_struct` packs both interpretations into a struct so
# downstream stages can still process the row without erroring.
resolvechoice2 = ResolveChoice.apply(
    frame=applymapping1,
    choice="make_struct",
    transformation_ctx="resolvechoice2",
)

# ── Step 4: Drop all-null columns ─────────────────────────────────────────
# Columns that end up entirely null (e.g., a CSV-only column when the batch
# is all JSON rows) get stripped here so they don't pollute the Silver schema.
dropnullfields3 = DropNullFields.apply(
    frame=resolvechoice2,
    transformation_ctx="dropnullfields3",
)

# ── Step 5: Write partitioned Parquet to Silver ───────────────────────────
# Coalesce to 1 partition per region before writing so Silver has a tidy
# file-per-region layout (not hundreds of shards).
df = dropnullfields3.toDF().coalesce(1)
df_final = DynamicFrame.fromDF(df, glueContext, "df_final")

datasink4 = glueContext.write_dynamic_frame.from_options(
    frame=df_final,
    connection_type="s3",
    connection_options={
        "path": SILVER_PATH,
        "partitionKeys": ["region"],
    },
    format="parquet",
    transformation_ctx="datasink4",
)

# Register the Silver table in the Glue Catalog.
# `write_dynamic_frame.from_options` above doesn't auto-register tables, so
# we issue a separate catalog update. (Alternative: `getSink(enableUpdateCatalog=True)`,
# but that pattern has append-only semantics which cause issues for re-runs
# — see Step 13 write-mode discussion.)
spark.sql(f"CREATE DATABASE IF NOT EXISTS {SILVER_DB}")
spark.sql(f"DROP TABLE IF EXISTS {SILVER_DB}.{SILVER_TABLE}")
spark.sql(f"""
    CREATE TABLE {SILVER_DB}.{SILVER_TABLE}
    USING PARQUET
    LOCATION '{SILVER_PATH}'
""")
# Refresh partitions so Athena sees all region=xx/ folders
spark.sql(f"MSCK REPAIR TABLE {SILVER_DB}.{SILVER_TABLE}")

logger.info(f"Silver write complete: {SILVER_DB}.{SILVER_TABLE} at {SILVER_PATH}")

job.commit()
