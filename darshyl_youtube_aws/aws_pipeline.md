# YouTube Trending Data — AWS Serverless Analytics Pipeline

**Topic:** Building a serverless data engineering pipeline on AWS that ingests YouTube Trending data (Kaggle + YouTube Data API), transforms it through a medallion data lake (Bronze, Silver, Gold), orchestrates with Step Functions, and visualizes insights in QuickSight

![YouTube trending data pipeline — S3 medallion architecture, Lambda, Glue, Step Functions, Athena, QuickSight](docs/diagrams/pipeline_architecture.svg)

**Source:** [Darshil Parmar — AWS Masterclass for Data Engineers](https://www.youtube.com/watch?v=yvAWbbQa8eE) | [GitHub Repository](https://github.com/darshilparmar/dataengineering-youtube-analysis-project)

This pipeline processes YouTube trending video statistics from multiple regions (US, GB, CA, DE, FR, IN, JP, KR, MX, RU), transforms raw CSVs and JSON category files through a three-layer data lake, and produces analytics-ready datasets queryable via Athena and visualized in QuickSight. The entire pipeline is orchestrated by AWS Step Functions with SNS alerts for success/failure.

> **Note on source data:** A hypothetical client is launching a data-driven marketing campaign on YouTube and needs to understand video categorization and factors affecting video popularity across regions. The pipeline uses the Kaggle YouTube Trending Dataset as its static source and the YouTube Data API v3 for real-time ingestion.

&nbsp;

## Data Flow — How the Pipeline Works in Production

```
1. INGEST      Static: Upload Kaggle CSV + JSON dataset to S3 Bronze bucket via AWS CLI
               Live:   Lambda fetches real-time trending data from YouTube Data API
                 → raw CSVs partitioned by region: <bronze>/youtube/raw_statistics/region=<code>/
                 → raw JSON category files: <bronze>/youtube/raw_statistics_reference_data/

2. CATALOG     Glue Crawler scans Bronze bucket
                 → infers schemas from CSV and JSON files
                 → registers tables in the Glue Data Catalog (yt_pipeline_bronze_dev)

3. CLEAN       Lambda (triggered by S3 event on new JSON in Bronze)
                 → reads JSON, normalizes nested "items" array using pandas
                 → writes cleansed Parquet to Silver bucket
                 → registers in Glue Catalog (yt_pipeline_silver_dev)

4. ETL         Glue ETL job (PySpark) — Bronze to Silver
                 → reads raw CSV statistics via Glue DynamicFrame (ApplyMapping)
                 → resolves ambiguous types (make_struct), drops null columns
                 → writes partitioned Parquet to Silver bucket

5. QUALITY     Lambda data quality gate
                 → validates row counts, null percentages, schema consistency, value ranges
                 → blocks progression to Gold if checks fail

6. AGGREGATE   Glue ETL job (PySpark) — Silver to Gold
                 → joins cleaned statistics with category reference data
                 → produces 3 analytics tables: trending_analytics, channel_analytics, category_analytics
                 → writes to Gold bucket

7. ORCHESTRATE Step Functions state machine runs the full pipeline
                 → Ingest → Wait (10s) → Parallel(Lambda + Glue) → Quality Check → Gold ETL
                 → SNS notifications on success or failure

8. QUERY       Athena queries the Gold layer via SQL (Glue Catalog as metastore)

9. VISUALIZE   QuickSight connects to Athena for dashboards
```

&nbsp;

## S3 Bucket Layout

The project uses five S3 buckets: four following the medallion architecture (Bronze/Silver/Gold/Scripts) plus a dedicated Athena query-results bucket:

```
yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/                     ← BRONZE — raw data, untouched
└── youtube/
    ├── raw_statistics/                                   ← CSV files (Kaggle) + JSON files (YouTube API) partitioned by region
    │   ├── region=ca/CAvideos.csv                        ← Kaggle static
    │   ├── region=ca/date=YYYY-MM-DD/hour=HH/*.json      ← YouTube API live
    │   ├── region=de/DEvideos.csv
    │   ├── region=de/date=YYYY-MM-DD/hour=HH/*.json
    │   ├── region=fr/FRvideos.csv
    │   ├── region=gb/GBvideos.csv
    │   ├── region=in/INvideos.csv
    │   ├── region=jp/JPvideos.csv
    │   ├── region=kr/KRvideos.csv
    │   ├── region=mx/MXvideos.csv
    │   ├── region=ru/RUvideos.csv
    │   └── region=us/USvideos.csv
    └── raw_statistics_reference_data/                    ← JSON category mapping files (one per region)
        ├── region=ca/CA_category_id.json                 ← Kaggle static
        ├── region=ca/date=YYYY-MM-DD/CA_category_id.json ← YouTube API live (overwritten daily)
        ├── region=de/DE_category_id.json
        ├── region=fr/FR_category_id.json
        ├── region=gb/GB_category_id.json
        ├── region=in/IN_category_id.json
        ├── region=jp/JP_category_id.json
        ├── region=kr/KR_category_id.json
        ├── region=mx/MX_category_id.json
        ├── region=ru/RU_category_id.json
        └── region=us/US_category_id.json

yt-data-pipeline-silver-<ACCOUNT_ID>-dev/                     ← SILVER — cleaned, typed Parquet
└── youtube/
    ├── clean_statistics/region=xx/                       ← Written by Bronze→Silver Glue ETL (CSV + JSON unified)
    └── raw_statistics_reference_data/region=xx/          ← Written by JSON-to-Parquet Lambda
                                                             (registered in the catalog as clean_reference_data)

yt-data-pipeline-gold-<ACCOUNT_ID>-dev/                       ← GOLD — aggregated, analytics-ready
└── youtube/
    ├── trending_analytics/region=xx/                     ← Video-level trending data enriched with category names
    ├── channel_analytics/region=xx/                      ← Channel performance metrics per region
    └── category_analytics/region=xx/                     ← Category-level aggregated trends over time

yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/                    ← SCRIPTS — PySpark and Lambda code files
└── glue/
    ├── glue_bronze_to_silver.py
    └── glue_silver_to_gold.py

yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/             ← ATHENA RESULTS — transient query output + CSV metadata
```

> **Note:** The medallion architecture is a standard practice: **Bronze** is immutable raw data (rollback-safe), **Silver** is cleaned and validated, **Gold** is aggregated for business use. The scripts bucket stores Glue job code separately. The Athena results bucket holds transient query output — kept separate from Gold so query artifacts never pollute the curated analytics layer.

> **Note:** S3 bucket names are globally unique across all AWS accounts. Replace `<region>` with your AWS region (e.g., `ap-south-1`) and append a unique suffix if the name is already taken.

> **Note:** A lifecycle rule on the Bronze bucket auto-transitions data under `youtube/` to **Glacier Flexible Retrieval** after **90 days** to reduce storage costs for old raw data.

&nbsp;

## AWS Services Used

| Service | Role in Pipeline |
|---------|-----------------|
| **S3** (`5 buckets: bronze, silver, gold, scripts, athena-results`) | Data lake storage organized in the medallion architecture — holds raw CSVs/JSONs, cleaned Parquet, aggregated analytics, Glue job scripts, and Athena query output |
| **IAM** (`yt-data-pipeline-*-role-dev`) | Access management following the principle of least privilege — scoped roles for Lambda, Glue, Step Functions, and the CLI user |
| **Secrets Manager** (`yt-data-pipeline/youtube-api-key-dev`) | Stores the Google YouTube Data API v3 key. The ingestion Lambda reads it at runtime via `secretsmanager:GetSecretValue` — never stored as a Lambda plaintext env var |
| **Glue Crawlers** (`yt-data-pipeline-bronze-crawler-dev`, `yt-data-pipeline-gold-crawler-dev`) | Schema inference — Bronze crawler scans Kaggle data once at setup; Gold crawler runs as a Step Functions state after every Silver→Gold ETL to refresh the Gold catalog |
| **Glue Data Catalog** (`yt_pipeline_bronze_dev`, `silver`, `gold`) | Central metadata repository with three databases mapping to the three medallion layers |
| **Glue ETL** (`2 PySpark jobs`) | Two transformation jobs: Bronze-to-Silver (clean/transform) and Silver-to-Gold (join/aggregate, idempotent overwrite) |
| **Lambda** (`3 functions`) | Serverless compute for JSON-to-Parquet cleaning, YouTube API ingestion, and data quality validation |
| **Step Functions** (`yt-data-pipeline-orchestration-dev`, Standard workflow) | End-to-end pipeline orchestration with parallel execution, quality gates, retry/catch error handling, Gold catalog refresh, and SNS notifications |
| **SNS** (`yt-data-pipeline-alerts-dev`) | Email notifications for pipeline success/failure alerts via topic subscription |
| **Athena** (`yt-pipeline-dev` workgroup) | Serverless SQL on S3 — dedicated workgroup pins all pipeline queries to a single result bucket and lets IAM policies scope the DQ Gate Lambda to just this workgroup |
| **QuickSight** | BI dashboards for trending categories, channel performance, and regional engagement analysis |
| **CloudWatch Logs** | Automatic logging for Lambda and Glue job executions (retention bounded to 14 days via Terraform; unbounded by default if created via the console) |

&nbsp;

## Component-by-Component Walkthrough

Here's what each service does in the pipeline, in the order data touches it.

**S3 (Simple Storage Service)** — The backbone of the data lake. Five buckets: four implement the medallion architecture (Bronze/Silver/Gold/Scripts), plus one dedicated Athena query-results bucket. Raw data lands as CSVs and JSONs from Kaggle and the YouTube API. Silver data is converted to Parquet for columnar performance. Gold contains joined, aggregated datasets. Hive-style partitioning (`region=xx/`) enables partition pruning in Athena. A lifecycle rule archives Bronze data to Glacier after 90 days.

**IAM (Identity and Access Management)** — Every service gets least-privilege roles. The Lambda execution role needs S3 read/write on the concrete bucket ARNs, Glue Catalog writes on the three medallion databases, Athena queries scoped to the `yt-pipeline-dev` workgroup, `secretsmanager:GetSecretValue` on the single API-key secret, and SNS publish on the single alert topic. The Glue role splits read-only access (Bronze, Scripts — both immutable) from read-write (Silver, Gold, Athena results). The Step Functions role needs `lambda:InvokeFunction`, `glue:StartJobRun`/`StartCrawler`/`GetCrawler` on pipeline resources, `iam:PassRole` on the Glue role, and SNS publish. A dedicated CLI IAM user with MFA enables local uploads via `aws s3 cp` — root access keys are never used.

**Secrets Manager** — Stores the Google YouTube Data API v3 key under the name `yt-data-pipeline/youtube-api-key-dev`. The ingestion Lambda reads it at module load via `boto3.client('secretsmanager').get_secret_value(...)` so the key lives in memory for the lifetime of the execution environment. Warm invocations skip the network call. Keeping the key out of Lambda environment variables means it's not visible to anyone with `lambda:GetFunctionConfiguration`.

**SNS (Simple Notification Service)** — A standard topic (`yt-data-pipeline-alerts-dev`) with email subscription. The developer subscribes their email and confirms via verification link. Step Functions triggers SNS for pipeline success, task failures, data quality issues, and catalog-refresh failures — the catalog failure has its own subject line because "Gold data is fine, catalog is stale" triages differently from "data is bad."

**Glue Crawlers** — The pipeline runs two: a **Bronze crawler** (`yt-data-pipeline-bronze-crawler-dev`) that scans the Bronze S3 bucket once at setup time and registers `raw_statistics` + `raw_statistics_reference_data` in `yt_pipeline_bronze_dev` — this crawler is a one-time setup and should never re-run after the YouTube API Lambda starts writing (mixing formats causes table-per-file explosion); and a **Gold crawler** (`yt-data-pipeline-gold-crawler-dev`) that runs as a Step Functions state after every Silver→Gold ETL, re-catalogging the three Gold tables. All crawlers auto-detect `region` as a partition from the Hive-style paths.

The Glue Data Catalog holds three databases, one per medallion layer:

| Database | Layer | Tables |
|----------|-------|--------|
| `yt_pipeline_bronze_dev` | Bronze (raw) | `raw_statistics`, `raw_statistics_reference_data` |
| `yt_pipeline_silver_dev` | Silver (clean) | `clean_statistics`, `clean_reference_data` |
| `yt_pipeline_gold_dev` | Gold (analytics) | `trending_analytics`, `channel_analytics`, `category_analytics` |

**Lambda — JSON to Parquet** (`yt-data-pipeline-json-to-parquet-dev`) — Triggered by S3 events when new JSON files land in `raw_statistics_reference_data/`. Reads nested JSON, flattens the `items` array using `pandas.json_normalize()`, and writes Parquet to Silver using AWS Data Wrangler (`awswrangler`). The `to_parquet(dataset=True, database=..., table=...)` call registers the output as `clean_reference_data` in the Silver catalog in the same call. Requires the `AWSSDKPandas-Python312` Lambda Layer.

**Lambda — YouTube API Ingestion** (`yt-data-pipeline-youtube-ingestion-dev`) — Reads the Google Developer API key from Secrets Manager at module load, then loops through region codes (US, GB, IN, etc.) to pull trending video statistics and category reference data from the YouTube Data API v3. Writes JSON to partitioned folders in the Bronze bucket under `date=/hour=/` sub-partitions that keep the live API output from overlapping with the Kaggle static upload.

**Lambda — Data Quality Gate** (`yt-data-pipeline-data-quality-dev`) — Validates Silver data before it moves to Gold. Checks: row counts (minimum threshold), null percentages in key columns, schema consistency, value ranges (e.g., views not negative), and data freshness. Uses `awswrangler.athena.read_sql_query` within the `yt-pipeline-dev` workgroup. Returns `{quality_passed: bool, ...}` that the Step Functions Choice state evaluates.

> **Why Lambda for quality gates instead of Glue?** Lambda is faster to start (no Spark overhead), cheaper for lightweight validation, and returns a simple pass/fail status that integrates cleanly with Step Functions Choice states. Glue is overkill for row-count checks.

**Glue ETL — Bronze to Silver** (PySpark) — Reads the `raw_statistics` Bronze table with predicate pushdown (`ca, gb, us, in` regions only), uses Glue's `DynamicFrame` API to pipe the rows through `ApplyMapping` → `ResolveChoice("make_struct")` → `DropNullFields`, and writes Snappy-compressed Parquet partitioned by `region` via `glueContext.write_dynamic_frame.from_options`. DynamicFrame + ChoiceType gracefully handle mixed file shapes in the Bronze prefix where a strict DataFrame cast would error out on missing columns. The job explicitly `CREATE TABLE ... USING PARQUET LOCATION ...` + `MSCK REPAIR TABLE` at the end — `getSink(enableUpdateCatalog=True)` was avoided because its append-only semantics double-count on re-run.

**Glue ETL — Silver to Gold** (PySpark) — Joins cleaned statistics with category reference data on `category_id` (broadcast join, falls back to `"Unknown"` if reference data is missing). Produces three analytics tables: `trending_analytics` (per region × trending date), `channel_analytics` (per channel × region, with `rank_in_region`), and `category_analytics` (per category × region × date, with `view_share_pct`). **Writes with `DataFrameWriter.mode("overwrite")` + dynamic partition overwrite** — running the job twice produces the same Gold state as running it once (strict idempotency). Does **not** touch the Glue Catalog; the Step Functions Gold crawler state handles that separately.

**Step Functions** (Standard workflow — required because Glue `.sync` states exceed Express's 5-minute cap) — Orchestrates the entire pipeline as a state machine:

1. **IngestFromYouTubeAPI** (Lambda task) — pulls live data into Bronze
2. **WaitForS3Consistency** (10-second Wait state)
3. **ProcessInParallel** — two branches: JSON-to-Parquet Lambda (reference data) + Bronze-to-Silver Glue job (statistics)
4. **RunDataQualityChecks** (Lambda task) — Silver validation
5. **EvaluateDataQuality** (Choice state — pass continues, fail routes to NotifyDQFailure)
6. **RunSilverToGoldGlueJob** (Glue `.sync` task) — builds Gold Parquet
7. **CatalogGoldTables → WaitForCrawlerToFinish → CheckCrawlerState → IsCrawlerDone** — kicks off the Gold crawler and polls until `READY` (emulates `.sync` for crawlers, which don't support it natively)
8. **NotifySuccess** (SNS) — or one of five terminal failure notifications targeted at the step that failed (ingestion, transform, DQ, Gold ETL, catalog refresh)

Every major task includes **Retry** and **Catch** blocks. Retries handle transient failures; Catches route to targeted SNS notifications after retry exhaustion. The catalog-refresh failure has a dedicated subject line because Gold data is already safely written — only the metadata refresh failed, which is manually recoverable.

**Athena** (`yt-pipeline-dev` workgroup) — Serverless SQL engine that reads from S3 using the Glue Catalog as metastore. All pipeline queries run inside the dedicated workgroup, which pins results to a single bucket and lets IAM scope queries at the workgroup level. Partition pruning on `region` keeps costs low. Used for ad-hoc analysis like top trending channels, engagement rates by region, and category performance.

**QuickSight** — Connects to Athena (or S3 Gold directly) for dashboards. Can use SPICE for in-memory acceleration. Visualizes trending analytics, channel performance (e.g., T-Series in India vs. SpaceX in US), and category comparisons across regions.

&nbsp;

## Step 1: S3 Buckets + Folder Structure

### 1.1 — Create the S3 Buckets

Create five buckets (one per medallion layer, plus scripts and Athena query results):

| Bucket | Purpose |
|--------|---------|
| `yt-data-pipeline-bronze-<ACCOUNT_ID>-dev` | Bronze — raw CSVs and JSONs as-is from Kaggle and YouTube API |
| `yt-data-pipeline-silver-<ACCOUNT_ID>-dev` | Silver — cleaned, typed Parquet |
| `yt-data-pipeline-gold-<ACCOUNT_ID>-dev` | Gold — aggregated analytics-ready datasets |
| `yt-data-pipeline-scripts-<ACCOUNT_ID>-dev` | Scripts — PySpark and Lambda code files |
| `yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev` | Athena query result output (used in [Step 9](#step-9-athena--explore-bronze-data) and [Step 15](#step-15-athena--query-the-gold-layer)) |

> **⚠ Naming convention — read this before creating anything.** S3 bucket names are a **global namespace**: the literal string `yt-data-pipeline-bronze-dev` is almost certainly already taken by someone else. This guide uses your **12-digit AWS account ID** as the uniqueness token. To get it:
>
> ```bash
> aws sts get-caller-identity --query Account --output text
> # → 123456789012   (your number — copy this for use everywhere <ACCOUNT_ID> appears)
> ```
>
> Then substitute your account ID into every `<ACCOUNT_ID>` placeholder you see in this guide — bucket names, IAM policy ARNs, Glue job parameters, Lambda env vars, and the Terraform section. Using your account ID guarantees the bucket names are globally unique (12 digits, AWS-assigned, never collides with another project) without you having to invent anything, and it matches the pattern every IAM ARN in the guide already uses. For the rest of Step 1, imagine you're substituting `123456789012` (or whatever your 12 digits are) into each command below.

**Console:**

1. Go to **S3 → Create bucket**
2. Bucket name: `yt-data-pipeline-bronze-<ACCOUNT_ID>-dev` (substitute your 12-digit account ID)
3. Region: choose the region nearest to your location (video uses `ap-south-1` Mumbai)
4. Leave remaining settings as default → Click **Create bucket**
5. Repeat for Silver, Gold, Scripts, and Athena-results buckets — use the **same account ID** for all five

**CLI alternative:**

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=<YOUR_REGION>   # e.g. eu-north-1

aws s3 mb s3://yt-data-pipeline-bronze-${ACCOUNT_ID}-dev         --region $REGION
aws s3 mb s3://yt-data-pipeline-silver-${ACCOUNT_ID}-dev         --region $REGION
aws s3 mb s3://yt-data-pipeline-gold-${ACCOUNT_ID}-dev           --region $REGION
aws s3 mb s3://yt-data-pipeline-scripts-${ACCOUNT_ID}-dev        --region $REGION
aws s3 mb s3://yt-data-pipeline-athena-results-${ACCOUNT_ID}-dev --region $REGION
```

> **Why the account ID?** It's already exposed in every IAM ARN the guide has you write, so it's not a new piece of leaked info. It's 12 digits, AWS-assigned, never collides across accounts. And it's instantly recoverable — if you ever forget what suffix you used, `aws sts get-caller-identity` gives it back. Previous revisions of this guide asked you to pick your own prefix like initials or a random string, which led to frequent "I forgot what I picked" and "the plain name was taken but the placeholder in the guide still said the generic one" errors. Using the account ID removes the entire class of mistakes.
>
> **Why a dedicated Athena results bucket?** Athena needs an S3 location to store query output and CSV metadata files. Keeping it separate from the Gold data bucket prevents transient query output from polluting the curated analytics layer and avoids conflicts with Glue crawlers scanning the Gold prefix.

### 1.2 — S3 Lifecycle Rule (Bronze Bucket)

1. Go to **S3 → Bronze bucket → Management → Create lifecycle rule**
2. Rule name: `Archive old raw data`
3. Scope: prefix `youtube/`
4. Under **Lifecycle rule actions**, check **"Transition current versions of objects between storage classes"**
5. In the dropdown that appears, select **Glacier Flexible Retrieval** as the storage class and enter **90** days
6. Check **"I acknowledge that this lifecycle rule will apply to all objects in the bucket"** (since Sept 2024 this confirms you understand the **128 KB default minimum object size** — objects smaller than 128 KB will NOT transition to Glacier/IA unless you explicitly override the minimum. This is AWS's way of preventing tiny files from being moved to storage classes whose per-object overhead would cost more than the savings.)
7. Click **Create rule**

> **⚠️ Production note — Athena results bucket also needs a lifecycle rule.** This guide only configures a lifecycle on the Bronze bucket. In production you should add one on the `yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev` bucket as well: expire all objects after ~30 days and abort incomplete multipart uploads after 7 days. Every Athena query (including every DQ Gate Lambda invocation and every QuickSight dashboard refresh) drops a results file + metadata sidecar into that bucket; without a lifecycle rule, they accumulate indefinitely. `awswrangler`'s `ctas_approach=True` default amplifies this — a single DQ query can produce tens of MB of CTAS artifacts. Query results are fully recomputable, so there's no reason to keep paying S3 Standard rates for them long-term. We skip this in the learning guide because query output here is too small to matter, but it's one of the top AWS cost-optimization recommendations for any real pipeline.

> Terraform: [1. S3 Buckets](#1-s3-buckets) · [2. S3 Lifecycle Rule (Bronze Bucket)](#2-s3-lifecycle-rule-bronze-bucket)

&nbsp;

### What Is a Lifecycle Rule and How Should You Use It in Production?

A lifecycle rule automates moving objects between S3 storage classes over time, and optionally deleting them after a set period. This matters because S3 storage classes vary dramatically in cost — and most pipeline data is only actively accessed for a short window before becoming archival.

In this pipeline, we set up a simple rule in Step 1.2: transition Bronze data to Glacier Flexible Retrieval after 90 days. That's fine for a learning project, but production pipelines — especially those under **SOX compliance** — need a more deliberate retention strategy.

**A common misconception: Glacier is not a separate bucket.** Glacier (Instant Retrieval, Flexible Retrieval, Deep Archive) is a storage class within the same bucket. When a lifecycle rule transitions an object to Glacier, the file stays at the exact same path — only the underlying storage tier changes. From the S3 console it looks identical, just with a different "Storage class" label. No new bucket, no new folder, no copying.

Here's what happens to a single file over its lifetime in one bucket:

```
Day 1:    stakeholder uploads file.parquet          → stored as S3 Standard
Day 91:   lifecycle rule fires                      → same file, same path, now Glacier Instant Retrieval
Day 366:  lifecycle rule fires again                → same file, same path, now Glacier Deep Archive
Day 2557: lifecycle rule fires again                → file deleted
```

Now, what happens if a stakeholder needs to rewrite that file? The answer depends on when the correction happens and which storage class the original is in. In all cases, the new upload always lands as **S3 Standard** — uploads never go directly into Glacier. With **versioning enabled**, the old version is preserved and the new version becomes current with its own lifecycle clock.

**Scenario A — Rewrite during S3 Standard (Day 1–90):**

```
Day 1:    stakeholder uploads file.parquet          → v1 stored as S3 Standard
Day 45:   stakeholder re-uploads corrected file     → v2 stored as S3 Standard (v1 becomes previous version)
                                                       v2's lifecycle clock starts from Day 45
Day 91:   lifecycle transitions v1                  → v1 moves to Glacier Instant Retrieval
Day 135:  lifecycle transitions v2 (45 + 90)        → v2 moves to Glacier Instant Retrieval
```

This is the most common case — a mistake caught within the operational window. Both versions follow the normal lifecycle independently. No special handling needed, no retrieval fees.

**Scenario B — Rewrite during Glacier Instant Retrieval (Day 91–365):**

```
Day 1:    stakeholder uploads file.parquet          → v1 stored as S3 Standard
Day 91:   lifecycle transitions v1                  → v1 moves to Glacier Instant Retrieval
Day 150:  stakeholder re-uploads corrected file     → v2 stored as S3 Standard (instant, no retrieval needed)
                                                       v1 stays in Glacier IR as a previous version
Day 240:  lifecycle transitions v2 (150 + 90)       → v2 moves to Glacier Instant Retrieval
```

The stakeholder does NOT need to "retrieve" the old file first — they simply upload the corrected version. S3 handles versioning automatically. Since Glacier Instant Retrieval supports millisecond reads, if they need to download the old version to check it before correcting, they can do so without waiting. No restore request required.

**Scenario C — Rewrite during Glacier Deep Archive (Day 366+):**

```
Day 1:    stakeholder uploads file.parquet          → v1 stored as S3 Standard
Day 366:  lifecycle transitions v1                  → v1 moves to Glacier Deep Archive
Day 500:  stakeholder re-uploads corrected file     → v2 stored as S3 Standard (instant, no retrieval needed)
                                                       v1 stays in Deep Archive as a previous version
Day 590:  lifecycle transitions v2 (500 + 90)       → v2 moves to Glacier Instant Retrieval
```

Uploading the corrected file is still instant — the stakeholder doesn't interact with the archived version at all. However, if they need to read the old Deep Archive version first (to understand what was wrong), they must initiate a **restore request** and wait 12–48 hours before the file becomes downloadable. This is the trade-off for the cheapest storage tier, but at this point (1+ year old data) it should be extremely rare.

**A real-world scenario:** Multiple stakeholders dump daily Parquet snapshots into S3. A Dagster sensor (or Snowpipe with SQS) ingests each file into Snowflake once per day. After ingestion, the raw S3 files are needed for corrections and backfills — but only for a limited window. At the same time, SOX compliance requires that financial data remains available for **7 years**, even if it's almost never queried after the first few months.

The right approach is a **multi-tier lifecycle** that matches access patterns to storage costs:

| Period | Storage Class | Why | Cost (approx/GB/month) |
|--------|--------------|-----|----------------------|
| 0–90 days | **S3 Standard** | Active corrections, backfills, re-ingestion if Snowflake load fails | $0.023 |
| 90 days – 1 year | **Glacier Instant Retrieval** | Past the operational window but recent enough that a late correction or audit question might need quick access (millisecond retrieval) | $0.004 |
| 1 – 7 years | **Glacier Deep Archive** | Pure SOX retention — data exists only for regulatory audit. 12–48 hour retrieval is fine for a few-times-per-year event | $0.00099 |
| After 7 years | **Expire (auto-delete)** | SOX obligation met — no reason to keep paying |

**Why three tiers instead of one jump to Glacier?** The 90-day to 1-year window is the gray zone. A stakeholder says "the December files had a bug, we need to re-ingest" — that's month 4, not day 30. Glacier Instant Retrieval gives millisecond access, so late corrections don't require waiting hours for a restore. After 1 year, the chance of needing the raw files drops to near-zero (Snowflake has the data, transformations have been applied), so Deep Archive's 12–48 hour retrieval time is an acceptable trade-off for dramatically lower storage costs over the remaining 6 years.

**SOX-specific considerations:**

SOX compliance requires that financial data remains available and provably unaltered for 7 years. Two S3 features make this possible:

**S3 Versioning** — when enabled on a bucket, overwrites don't replace data. Instead, each upload creates a new version under the same key. If a stakeholder uploads `file.parquet` on Day 1 (v1) and then overwrites it with a corrected file on Day 45 (v2), both versions exist. The S3 console shows one file by default; toggling **"Show versions"** reveals both v1 and v2 with their timestamps and version IDs. A normal download returns the latest version (v2). To get a specific older version, you use the version ID in the request.

**S3 Object Lock (Compliance mode)** — enforces WORM (Write Once, Read Many), meaning nobody can delete any version of an object before the retention period expires — not even an admin, not even the root account. Without it, a lifecycle rule alone doesn't prove data couldn't have been tampered with. This is what auditors actually care about.

**The problem: these two needs conflict in a single bucket.** Stakeholders need to overwrite files in the Bronze bucket (corrections, re-uploads). Object Lock prevents any deletion or modification. You can't allow operational flexibility AND guarantee immutability in the same bucket. Here's what happens when you use two buckets instead:

```
Bronze bucket:                                  Compliance archive bucket:
                                                (via S3 Replication)

Day 1: stakeholder uploads file.parquet
  → v1 created (version ID: abc123)        →   v1 replicated (version ID: abc123)
                                                Object Lock: locked for 7 years

Day 45: stakeholder overwrites file.parquet
  → v2 created (version ID: def456)        →   v2 replicated (version ID: def456)
     v1 still exists as previous version        v1 still exists, Object Lock prevents deletion
                                                Both versions are immutable

Day 90: admin accidentally deletes v1
  → v1 deleted from Bronze (possible)           v1 still exists in compliance bucket (Object Lock blocks deletion)
```

This is not two physical files at different paths — it's one S3 key (`youtube/.../file.parquet`) with a version history underneath. The critical difference: in the Bronze bucket, an admin *could* delete v1 or v2. In the compliance bucket, Object Lock makes that physically impossible until the 7-year retention expires. This is what "tamper-proof" means — not that the file can't be overwritten (it can, creating a new version), but that no version can ever be deleted or modified once it exists.

**How to retrieve data from the compliance bucket during an audit:**

| What you need | How to get it |
|---------------|---------------|
| Latest version of a file | Normal `GET` request — S3 returns the current version by default |
| A specific older version | Include the version ID: `aws s3api get-object --bucket compliance-bucket --key youtube/.../file.parquet --version-id abc123 output.parquet` |
| List all versions of a file | `aws s3api list-object-versions --bucket compliance-bucket --prefix youtube/.../file.parquet` |
| Full audit trail | List versions across the entire bucket — each version has a timestamp showing exactly when it was uploaded |

> **Note:** Since the compliance bucket uses Glacier Deep Archive, you must first initiate a **restore request** before downloading. The restore takes 12–48 hours. Once restored, the object is temporarily available in S3 Standard for the duration you specify (e.g., 7 days), then returns to Deep Archive.

**Setting up the two-bucket architecture:**

Now that the concepts are clear, here's the comparison and how to configure it:

| | Bronze bucket (operational) | Compliance archive bucket (SOX audit trail) |
|---|---|---|
| **Purpose** | Where stakeholders upload and correct files, where Dagster/Snowpipe reads from | Immutable copy of every version ever ingested — proves to auditors that data was not altered |
| **Object Lock** | No — stakeholders need to overwrite files | Yes — Compliance mode, 7-year retention, nobody can delete or modify |
| **Versioning** | Enabled (preserves correction history) | Enabled (required by Object Lock) |
| **Who writes to it** | Stakeholders upload directly | Nobody uploads directly — data arrives automatically via **S3 Replication Rule** from the Bronze bucket |
| **Storage class** | Multi-tier lifecycle (Standard → Glacier IR → Deep Archive) | **Glacier Deep Archive only** — this bucket is never used for operational access, only for regulatory audit. Transition to Deep Archive after 90 days (or immediately, depending on policy) |
| **Expiration** | Auto-delete after 7 years | Auto-delete after 7 years (Object Lock prevents early deletion) |

**How data gets into the compliance bucket** — you configure an **S3 Replication Rule** on the Bronze bucket. Every time a stakeholder uploads or overwrites a file, S3 automatically copies it (including the new version) to the compliance archive bucket. This happens asynchronously (typically within seconds) and requires no Lambda or manual intervention. To set this up:

1. Go to **S3 → Bronze bucket → Management → Replication rules → Create replication rule**
2. Rule name: `Replicate to compliance archive`
3. Source: entire bucket (or scope to prefix `youtube/`)
4. Destination: the compliance archive bucket
5. IAM role: create or select a role with `s3:ReplicateObject` permissions on both buckets
6. Check **"Replicate objects encrypted with AWS KMS"** if using KMS encryption

> **Important:** S3 Replication copies new objects going forward — it does not retroactively copy existing objects. If you enable replication after data is already in the Bronze bucket, use **S3 Batch Replication** to copy the existing objects to the compliance bucket.

**Auto-deleting data after 7 years:**

S3 lifecycle rules support an **Expiration** action that automatically deletes objects after a specified number of days. To set this up in the console:

1. Go to **S3 → Bucket → Management → Create lifecycle rule**
2. Under **Lifecycle rule actions**, check both:
   - **"Transition current versions of objects between storage classes"** (for the Glacier transitions)
   - **"Expire current versions of objects"** (for the auto-delete)
3. Configure transitions: Glacier Instant Retrieval at **90** days, Glacier Deep Archive at **365** days
4. Configure expiration: **2,557** days (7 years)
5. Check the acknowledgment checkbox and click **Create rule**

If S3 Object Lock is enabled with a 7-year retention period, the lifecycle expiration and Object Lock work together: the lifecycle rule queues the delete at 2,557 days, but the object won't actually be removed until the lock retention expires. They're complementary — the lifecycle automates the cleanup, the lock prevents premature deletion.

The full lifecycle configuration for a SOX-compliant production setup:

```
Bronze bucket (operational):
  ├── Versioning: Enabled
  └── Lifecycle rule:
      ├── Transition to Glacier Instant Retrieval after 90 days
      ├── Transition to Glacier Deep Archive after 365 days
      └── Expire (auto-delete) after 2,557 days (7 years)
  └── Replication rule → copies every upload to compliance archive bucket

Compliance archive bucket (SOX audit trail):
  ├── Object Lock: Compliance mode, 7-year retention
  ├── Versioning: Enabled (required by Object Lock)
  ├── Data arrives automatically via S3 Replication (no direct uploads)
  └── Lifecycle rule:
      ├── Transition to Glacier Deep Archive after 90 days
      └── Expire (auto-delete) after 2,557 days (7 years)
```

&nbsp;

## Step 2: IAM — Service Roles

Create IAM roles for each service following the **principle of least privilege** — only grant the permissions each service actually needs.

### 2.1 — AWS Access

#### 2.1.1 — Console: Create an IAM User for CLI Access

**⚠ Do not use root access keys.** AWS blocks root access key creation by default on new accounts (since 2024) and enforces root MFA organization-wide (since June 2025). Every AWS best-practice doc now says the same thing: root is for account management only; never use it for day-to-day work, and never generate access keys for it. Always create a dedicated IAM user with the permissions you need.

1. Go to **IAM → Users → Create user**
2. Username: `aws-cli-local`
3. Click **Next** → Attach policy: **AdministratorAccess** (fine for a personal learning account; see [Step 2.1.3](#213--in-a-corporate-environment) for production patterns)
4. Click **Create user**
5. **Enable MFA on the user:**
   - Go to **IAM → Users → `aws-cli-local` → Security credentials → Assign MFA device**
   - Choose **Authenticator app** (Google Authenticator, Authy, 1Password, etc.) and follow the pairing flow
6. **Create the access key:**
   - On the same Security credentials tab, click **Create access key**
   - Use case: **Command Line Interface (CLI)**
   - Check the acknowledgement → Click **Next** → Click **Create access key**
   - Download the CSV (contains your Access Key ID and Secret Access Key)

> **Why MFA on the IAM user?** An IAM user without MFA is only as secure as the access key sitting in `~/.aws/credentials`. If that key is ever exposed (committed to a repo, copied to a shared machine, captured by malware), an attacker has full access to your AWS account. MFA means even a leaked key can't be used without the one-time code from your authenticator app — at least for actions that require MFA. For admin-grade keys on a learning account, enable MFA on the user itself so console access is also protected.

#### 2.1.2 — CLI: Configure AWS Credentials

```bash
aws configure
# → Access Key ID: (paste from the downloaded CSV)
# → Secret Access Key: (paste from the downloaded CSV)
# → Default region: eu-north-1 (or your chosen region)
# → Default output format: (leave blank, press Enter)

# Verify the connection:
aws s3 ls
```

If `aws s3 ls` returns your bucket list (or an empty list for a new account), the CLI is configured correctly.

#### 2.1.3 — In a Corporate Environment

In production, **nobody uses root or long-lived access keys.** The approach changes entirely:

**Authentication — AWS IAM Identity Center (SSO):**

Instead of creating IAM users with permanent access keys, you configure **AWS SSO** integrated with your corporate identity provider (Okta, Azure AD, etc.). Developers authenticate via:

```bash
aws sso login --profile my-corp-profile
```

This opens a browser for SSO authentication and provisions **temporary credentials** (expire after 1–12 hours). No access keys stored on disk, no CSV files to manage or leak.

**Authorization — Assumed Roles with Permission Boundaries:**

Rather than attaching `AdministratorAccess` to a user, you create **scoped roles** that developers assume for specific tasks:

| Role | Who Assumes It | What It Can Do |
|------|---------------|----------------|
| `DataEngineer-Dev` | Developer via SSO | Read/write to dev S3 buckets, run Glue jobs, view Lambda logs — but NOT create IAM roles or modify billing |
| `PipelineDeployer` | CI/CD pipeline (GitLab/GitHub Actions) | Create/update Lambda functions, Glue jobs, Step Functions — scoped to `yt-data-pipeline-*` resources |
| `DevOps-Admin` | DevOps team via SSO | Create IAM roles, manage infrastructure — the only humans who can create the service roles in Steps 2.2–2.4 |

**Service Control Policies (SCPs):**

At the AWS Organization level, SCPs restrict what anyone can do — even accounts with `AdministratorAccess`. Common restrictions:

- Block `iam:CreateUser` (force SSO instead of IAM users)
- Block `iam:CreateAccessKey` (no permanent credentials)
- Restrict regions (only allow `eu-north-1` and `eu-west-1`)
- Require MFA for destructive operations

**What you'd provision as DevOps for this pipeline:**

As the DevOps engineer, you would create everything in Steps 2.2–2.4 (the service roles) via Terraform in a CI/CD pipeline — not through the console. Developers would never touch IAM. The workflow:

1. Developer opens a merge request adding a new Lambda function
2. Terraform plan runs automatically, showing the IAM changes needed
3. You (DevOps) review and approve the IAM changes
4. CI/CD runs `terraform apply` with the `DevOps-Admin` role
5. The Lambda execution role is created with least-privilege permissions
6. Developer can now deploy their function using the `PipelineDeployer` role

> **Key difference from the tutorial:** In the tutorial, one person creates everything through the console. In production, IAM creation is separated from resource creation — DevOps owns IAM, developers own application code. The Terraform Reference section at the end of this guide shows exactly what you'd commit to your infra repo.

### 2.2 — Lambda Execution Role

Shared execution role for all three Lambda functions in the pipeline (JSON-to-Parquet, YouTube API ingestion, data quality gate). This section sets up the role **with its final, complete inline policy in one pass** — S3, Glue Catalog, Athena, and SNS — so you don't have to return here as later steps add new use cases.

> **Note on the tutorial's order:** The source YouTube tutorial builds this policy incrementally (S3 only first, then adds Glue/SNS when Lambda code that needs them is introduced, then adds Athena when the DQ Gate Lambda is introduced). We collapse all of that into a single authoritative policy here — it keeps the role in one place and avoids the "edit the same inline policy three times" confusion. All four Sids are always valid for the shared role because each Lambda that uses the role needs a subset of these permissions.

#### 2.2.1 — Create the Role

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **AWS service**
3. Use case: **Lambda**
4. Click **Next**
5. Search for and select the managed policy: **AWSLambdaBasicExecutionRole** (provides CloudWatch Logs — `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`)
6. Click **Next**
7. Role name: `yt-data-pipeline-lambda-role-dev`
8. Click **Create role**

> **Heads-up on the post-create view:** After clicking Create, open the role detail page and you'll see **two** managed policies attached:
> - `AWSLambdaBasicExecutionRole` — the one you picked
> - `AWSLambdaBasicDurableExecutionRolePolicy` — **auto-attached by the IAM console**, added after AWS introduced Lambda durable execution support
>
> The second policy grants a small set of `lambda:*` permissions on the Lambda's own function for durable-execution state handling. This pipeline's Lambdas don't use durable execution, so the extra grants are unused — but also harmless. **Leave both attached.** Detaching `AWSLambdaBasicDurableExecutionRolePolicy` does nothing useful, and AWS will re-attach it next time anyone edits the role's managed-policy list through the console. If you care about strict minimality (and are willing to re-detach every time the role is edited), you can remove it with `aws iam detach-role-policy --role-name yt-data-pipeline-lambda-role-dev --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicDurableExecutionRolePolicy`. For this guide we accept it as part of the standard console experience.

#### 2.2.2 — Add the Inline Policy

1. Go to **IAM → Roles → `yt-data-pipeline-lambda-role-dev`**
2. Click **Add permissions → Create inline policy**
3. Switch to the **JSON** editor
4. Paste the JSON below
5. Policy name: `yt-pipeline-lambda-access`
6. Click **Create policy**

**Inline policy** (`yt-pipeline-lambda-access`) — S3 data access + Glue Catalog writes + Athena query execution + SNS publish, covering every Lambda that shares this role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/*"
      ]
    },
    {
      "Sid": "GlueCatalogAccess",
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetDatabases",
        "glue:GetTable",
        "glue:GetTables",
        "glue:CreateTable",
        "glue:UpdateTable",
        "glue:GetPartitions",
        "glue:GetPartition",
        "glue:BatchCreatePartition",
        "glue:BatchGetPartition"
      ],
      "Resource": [
        "arn:aws:glue:*:*:catalog",
        "arn:aws:glue:*:*:database/yt_pipeline_bronze_dev",
        "arn:aws:glue:*:*:database/yt_pipeline_silver_dev",
        "arn:aws:glue:*:*:database/yt_pipeline_gold_dev",
        "arn:aws:glue:*:*:table/yt_pipeline_bronze_dev/*",
        "arn:aws:glue:*:*:table/yt_pipeline_silver_dev/*",
        "arn:aws:glue:*:*:table/yt_pipeline_gold_dev/*"
      ]
    },
    {
      "Sid": "AthenaQueryAccess",
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup",
        "athena:GetDataCatalog",
        "athena:ListDataCatalogs",
        "athena:GetDatabase",
        "athena:GetTableMetadata"
      ],
      "Resource": [
        "arn:aws:athena:*:*:workgroup/yt-pipeline-dev",
        "arn:aws:athena:*:*:datacatalog/AwsDataCatalog"
      ]
    },
    {
      "Sid": "SNSPublish",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:*:*:yt-data-pipeline-alerts-dev"
    }
  ]
}
```

> **Bucket name substitution** — replace `<ACCOUNT_ID>` in every S3 ARN above with your 12-digit AWS account ID from [Step 1.1](#11--create-the-s3-buckets). Do **not** leave `*` as a wildcard in place of the account ID — S3 bucket names are a global namespace, and `arn:aws:s3:::yt-data-pipeline-bronze-*` would match any bucket in any account starting with that prefix.
>
> IAM inline-policy JSON does not allow inline comments. The table below explains what each `Sid` block grants and which Lambda relies on it — annotate your local copy if you want, but strip the comments before pasting into the AWS console.

**What each Sid does:**

| Sid | What it allows | Which Lambda needs it |
|-----|---------------|-----------------------|
| `S3Access` | Read/write/list on the Bronze, Silver, and Athena-results buckets (scoped to your exact bucket names — see the warning above) | **JSON-to-Parquet** reads Bronze JSON, writes Silver Parquet. **YouTube API Ingestion** writes Bronze JSON. **DQ Gate** writes Athena query output to the results bucket. |
| `GlueCatalogAccess` | Get/create/update tables and partitions in the three specific medallion databases `yt_pipeline_bronze_dev`, `yt_pipeline_silver_dev`, `yt_pipeline_gold_dev` (created in [Step 5](#step-5-glue--create-databases)) | **JSON-to-Parquet** — `awswrangler.s3.to_parquet()` registers the output as a Glue table and adds partitions automatically. |
| `AthenaQueryAccess` | Start/monitor/stop Athena queries **within the dedicated `yt-pipeline-dev` workgroup only** (created in [Step 9.1](#91--configure-query-results)), plus workgroup/catalog/metadata introspection calls (`GetWorkGroup`, `GetDataCatalog`, `GetDatabase`, `GetTableMetadata`) that `awswrangler.athena.read_sql_query` makes before submitting a query. The introspection actions are scoped to this workgroup + the default `AwsDataCatalog`, so the Lambda can't peek at workgroups or catalogs belonging to other projects. | **DQ Gate** ([Step 12](#step-12-lambda--data-quality-gate)) uses `awswrangler.athena.read_sql_query` to scan Silver tables for quality checks. |
| `SNSPublish` | Publish messages to the pipeline's notification topic `yt-data-pipeline-alerts-dev` (created in [Step 4](#step-4-sns--pipeline-alerts)) | **YouTube API Ingestion** and **DQ Gate** send failure/summary alerts via SNS. |

#### 2.2.3 — CLI Alternative

Self-contained script — no intermediate files to manage. The `<<'EOF'` (quoted) prevents the shell from interpolating anything inside the JSON, and `$(cat <<...EOF)` captures the document as a single argument to `--policy-document`.

```bash
# 1. Create the role with inline trust policy
aws iam create-role \
  --role-name yt-data-pipeline-lambda-role-dev \
  --assume-role-policy-document "$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)"

# 2. Attach the managed CloudWatch Logs policy
aws iam attach-role-policy \
  --role-name yt-data-pipeline-lambda-role-dev \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# 3. Attach the inline permissions policy (matches the JSON shown in Section 2.2.2).
#    NOTE: replace <region> below with the region you picked in Step 1.1 (e.g. eu-north-1)
#    — bucket ARNs must be exact to avoid wildcard matches against other accounts' buckets.
aws iam put-role-policy \
  --role-name yt-data-pipeline-lambda-role-dev \
  --policy-name yt-pipeline-lambda-access \
  --policy-document "$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3Access",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/*"
      ]
    },
    {
      "Sid": "GlueCatalogAccess",
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetDatabases",
        "glue:GetTable",
        "glue:GetTables",
        "glue:CreateTable",
        "glue:UpdateTable",
        "glue:GetPartitions",
        "glue:GetPartition",
        "glue:BatchCreatePartition",
        "glue:BatchGetPartition"
      ],
      "Resource": [
        "arn:aws:glue:*:*:catalog",
        "arn:aws:glue:*:*:database/yt_pipeline_bronze_dev",
        "arn:aws:glue:*:*:database/yt_pipeline_silver_dev",
        "arn:aws:glue:*:*:database/yt_pipeline_gold_dev",
        "arn:aws:glue:*:*:table/yt_pipeline_bronze_dev/*",
        "arn:aws:glue:*:*:table/yt_pipeline_silver_dev/*",
        "arn:aws:glue:*:*:table/yt_pipeline_gold_dev/*"
      ]
    },
    {
      "Sid": "AthenaQueryAccess",
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup",
        "athena:GetDataCatalog",
        "athena:ListDataCatalogs",
        "athena:GetDatabase",
        "athena:GetTableMetadata"
      ],
      "Resource": [
        "arn:aws:athena:*:*:workgroup/yt-pipeline-dev",
        "arn:aws:athena:*:*:datacatalog/AwsDataCatalog"
      ]
    },
    {
      "Sid": "SNSPublish",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:*:*:yt-data-pipeline-alerts-dev"
    }
  ]
}
EOF
)"
```

> Terraform: [3. IAM — Lambda Execution Role](#3-iam--lambda-execution-role)

&nbsp;

## Step 3: IAM — Glue Service Role

Shared execution role for Glue crawlers and ETL jobs. Needs read access on the immutable buckets (Bronze raw data, Scripts code) and read/write access on the buckets Glue mutates (Silver, Gold, Athena results). Glue Catalog management and CloudWatch Logs are provided by the `AWSGlueServiceRole` managed policy — so the inline policy below only adds the S3 scoping.

### 3.1 — Create the Role

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **AWS service**
3. Use case: **Glue**
4. Click **Next**
5. Search for and select the managed policy: **AWSGlueServiceRole** (provides Glue Catalog access, CloudWatch Logs, and EC2 permissions Glue needs to launch Spark workers)
6. Click **Next**
7. Role name: `yt-data-pipeline-glue-role-dev`
8. Click **Create role**

### 3.2 — Add the Inline Policy

1. Go to **IAM → Roles → `yt-data-pipeline-glue-role-dev`**
2. Click **Add permissions → Create inline policy**
3. Switch to the **JSON** editor
4. Paste the JSON below
5. Policy name: `yt-pipeline-glue-access`
6. Click **Create policy**

**Inline policy** (`yt-pipeline-glue-access`) — S3 read-only on immutable buckets (Bronze, Scripts) + S3 read/write on mutable buckets (Silver, Gold, Athena results). Naming parallels `yt-pipeline-lambda-access` from [Step 2.2](#222--add-the-inline-policy):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOnlyOnImmutableBuckets",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-scripts-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/*"
      ]
    },
    {
      "Sid": "ReadWriteOnMutableBuckets",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-gold-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-gold-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/*"
      ]
    }
  ]
}
```

> **Bucket name substitution** — replace `<ACCOUNT_ID>` in every S3 ARN above with your 12-digit AWS account ID from [Step 1.1](#11--create-the-s3-buckets). Same reasoning as [Step 2.2.2](#222--add-the-inline-policy): leaving a `*` wildcard would match buckets in other accounts that happen to share the prefix.

**What each Sid does:**

| Sid | What it allows | Why this split |
|-----|----------------|----------------|
| `ReadOnlyOnImmutableBuckets` | `s3:GetObject` + `s3:ListBucket` on **Bronze** and **Scripts** | **Bronze** holds raw ingested data — the audit trail and replay source if Silver/Gold ever get corrupted. An ETL job has no legitimate reason to delete or overwrite raw files; removing write permissions means a buggy Glue script can't accidentally destroy the source of truth. **Scripts** holds the PySpark code itself. Glue reads scripts to run them, never writes back. Write permissions here would be a footgun — a job with a compromised role could modify its own code for subsequent runs. |
| `ReadWriteOnMutableBuckets` | `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`, `s3:DeleteObject` on **Silver**, **Gold**, and **Athena-results** | These are the buckets Glue legitimately mutates: Bronze→Silver writes cleansed Parquet, Silver→Gold writes aggregates (with `DeleteObject` needed for the dynamic-partition-overwrite pattern from [Step 13](#step-13-glue-etl--silver-to-gold)), and Athena-results gets CTAS / query-output artifacts during Glue-orchestrated Athena calls. |

> **Why each bucket appears twice** (bare ARN + `/*` ARN): S3 treats buckets and objects as separate resource types. `s3:ListBucket` acts on the **bucket** (bare ARN); `s3:GetObject`/`s3:PutObject`/`s3:DeleteObject` act on **objects inside** (`/*` ARN). Both forms are needed — without the bare ARN you can't list contents; without the `/*` ARN you can't read or write files.
>
> **The `AWSGlueServiceRole` managed policy** already grants `glue:*` (full Catalog access), `logs:*` (CloudWatch Logs), and the EC2 and networking permissions Glue needs to launch Spark workers inside a VPC. This inline policy adds only the missing piece — S3 access scoped to the pipeline's five buckets.

### 3.3 — CLI Alternative

Self-contained script — no intermediate files to manage. Same `<<'EOF'` heredoc pattern as [Step 2.2.3](#223--cli-alternative). The script auto-detects your account ID via `aws sts get-caller-identity` and substitutes it into every bucket ARN below.

```bash
# 1. Create the role with inline trust policy (Glue is the trusted service)
aws iam create-role \
  --role-name yt-data-pipeline-glue-role-dev \
  --assume-role-policy-document "$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "glue.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)"

# 2. Attach the managed Glue service role policy
aws iam attach-role-policy \
  --role-name yt-data-pipeline-glue-role-dev \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole

# 3. Attach the inline permissions policy (matches the JSON shown in Section 3.2).
#    NOTE: replace <region> below with the region you picked in Step 1.1 (e.g. eu-north-1)
#    — bucket ARNs must be exact to avoid wildcard matches against other accounts' buckets.
aws iam put-role-policy \
  --role-name yt-data-pipeline-glue-role-dev \
  --policy-name yt-pipeline-glue-access \
  --policy-document "$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOnlyOnImmutableBuckets",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-scripts-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/*"
      ]
    },
    {
      "Sid": "ReadWriteOnMutableBuckets",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-silver-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-gold-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-gold-<ACCOUNT_ID>-dev/*",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev",
        "arn:aws:s3:::yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/*"
      ]
    }
  ]
}
EOF
)"
```

> Terraform: [4. IAM — Glue Service Role](#4-iam--glue-service-role)

&nbsp;

## Step 4: SNS — Pipeline Alerts

### 4.1 — Create the Topic and Subscription

#### Console

1. Go to **SNS → Topics → Create topic**
2. Type: **Standard**
3. Name: `yt-data-pipeline-alerts-dev`
4. Click **Create topic**
5. Click **Create subscription**
6. Protocol: **Email**
7. Endpoint: `diaconescutiberiu@gmail.com`
8. Click **Create subscription** → confirm via the verification email you receive

#### CLI

```bash
# Create the topic
aws sns create-topic --name yt-data-pipeline-alerts-dev --region <YOUR_REGION>

# Subscribe your email (replace <TOPIC_ARN> with the ARN output from above)
aws sns subscribe \
  --topic-arn <TOPIC_ARN> \
  --protocol email \
  --notification-endpoint diaconescutiberiu@gmail.com
```

> This topic is used by Step Functions and Lambda to send pipeline success, failure, and data quality alerts.

> Terraform: [6. SNS Topic + Subscription](#6-sns-topic--subscription)

&nbsp;

## Step 5: Glue — Create Databases

One Glue database per medallion layer. These are the catalogs that crawlers, ETL jobs, and Athena all reference.

### 5.1 — Create the Three Medallion Databases

#### Console

1. Go to **Glue → Data Catalog → Databases → Add database**
2. Create each database one at a time:

| Database | Layer | Description |
|----------|-------|---------|
| `yt_pipeline_bronze_dev` | Bronze | Raw data — CSVs and JSON as ingested |
| `yt_pipeline_silver_dev` | Silver | Cleansed Parquet — mapped, typed, ambiguities resolved |
| `yt_pipeline_gold_dev` | Gold | Analytics-ready — joined, aggregated, enriched |

#### CLI

```bash
aws glue create-database --database-input '{"Name": "yt_pipeline_bronze_dev"}' --region <YOUR_REGION>
aws glue create-database --database-input '{"Name": "yt_pipeline_silver_dev"}' --region <YOUR_REGION>
aws glue create-database --database-input '{"Name": "yt_pipeline_gold_dev"}' --region <YOUR_REGION>
```

> Terraform: [7. Glue Databases](#7-glue-databases)

&nbsp;

## Step 6: Ingest — Upload the Kaggle Dataset

This is the first half of Data Flow **#1 INGEST** — the static, one-time load of the Kaggle YouTube Trending Dataset into the Bronze bucket. It populates `raw_statistics/` (CSVs of trending video metadata) and `raw_statistics_reference_data/` (JSON files mapping `category_id` to human-readable names), both Hive-style partitioned by region.

### 6.1 — Download the Dataset

Download the [Kaggle YouTube Trending Dataset](https://www.kaggle.com/datasets/datasnaek/youtube-new) (requires a free Kaggle account). The archive contains:
- 10 CSV files (`CAvideos.csv`, `DEvideos.csv`, `FRvideos.csv`, `GBvideos.csv`, `INvideos.csv`, `JPvideos.csv`, `KRvideos.csv`, `MXvideos.csv`, `RUvideos.csv`, `USvideos.csv`) — one per region, ~50–64 MB each
- 10 JSON files (`CA_category_id.json`, …) — category reference data per region

Unzip everything into a single local folder.

### 6.2 — Upload to Bronze

Use the helper script at [`docs/resources/s3_upload_commands.sh`](docs/resources/s3_upload_commands.sh). It auto-detects your AWS account ID and uploads each file under its Hive-style `region=xx/` prefix in `s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/`:

```
s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/raw_statistics/region=ca/CAvideos.csv
s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/raw_statistics_reference_data/region=ca/CA_category_id.json
…
```

Run the script (from the same directory where you unzipped the Kaggle files):

```bash
bash /path/to/docs/resources/s3_upload_commands.sh
```

No edits required — the script derives `BRONZE_BUCKET` from `aws sts get-caller-identity` at runtime, so as long as your AWS CLI is configured (from [Step 2.1.2](#212--cli-configure-aws-credentials)), it'll upload to your correct bucket.

Expect the CSV uploads to take a few minutes depending on your bandwidth (600+ MB total).

### 6.3 — Verify

```bash
aws s3 ls s3://<bronze-bucket>/youtube/raw_statistics/ --recursive | wc -l
# Should print 10 (one CSV per region)

aws s3 ls s3://<bronze-bucket>/youtube/raw_statistics_reference_data/ --recursive | wc -l
# Should print 10 (one JSON per region)
```

> **Why Hive-style partitioning?** Prefixing with `region=xx/` lets the Glue Crawler (next step) auto-detect `region` as a partition column. Athena can then prune partitions — dramatically reducing scan cost and query time.

&nbsp;

## Step 7: Lambda — YouTube API Ingestion

This Lambda fetches live trending video data and category reference data from the YouTube Data API v3, writing raw JSON files to the Bronze S3 bucket. It uses the shared Lambda execution role created in [Step 2.2](#22--lambda-execution-role).

### 7.1 — Create the Lambda Function

#### Console

1. Go to **Lambda → Create function**
2. **Author from scratch**
3. Function name: `yt-data-pipeline-youtube-ingestion-dev`
4. Runtime: **Python 3.12**
5. Scroll down and expand the **Custom settings** accordion (collapsed by default — without expanding it, you can't see the toggle in step 6). Inside, toggle on **Custom execution role**
6. In the **Configure custom execution role** panel, select `yt-data-pipeline-lambda-role-dev` from the **Execution role** dropdown
7. Click **Save** — the panel closes and shows your role under **IAM permissions**
8. Click **Create function**

### 7.2 — Set Up the YouTube Data API Key

You need a Google API key to call the YouTube Data API v3.

#### Enable the API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Go to **APIs & Services → Library**
4. Search for **YouTube Data API v3** → click **Enable**

> If you already have a project with the API enabled, you'll land on the API's page showing **API Enabled** with a **Manage** button. Skip straight to the credentials step below.

#### Create the API Key

1. In the left sidebar, click **APIs & Services → Credentials**
2. Click **+ Create credentials → API key**
3. Fill in the creation dialog:

| Field | Value | Why |
|-------|-------|-----|
| **Name** | `yt-data-pipeline-youtube-api-key-dev` | Descriptive name for the key |
| **Select API restrictions** (dropdown) | `YouTube Data API v3` | Limits the key to YouTube endpoints only — if leaked, it can't be used for other Google APIs |
| **Authenticate API calls through service account** (checkbox) | Leave **unchecked** | Service accounts are for OAuth server-to-server auth; we're using a plain API key for public read-only data |
| **Restrict your key** (radio buttons — application restrictions) | **None** | Lambda egress IPs are dynamic, and HTTP referrer / mobile app restrictions don't apply here. The API restriction above already limits blast radius. |

4. Click **Create** → **copy the key immediately**; you'll store it in Secrets Manager in Step 7.3 below

> **Security note:** "None" for application restrictions is acceptable for a dev/learning setup because the API restriction to YouTube Data API v3 already limits blast radius. Even so, **don't paste the key into a Lambda environment variable** — anyone with `lambda:GetFunctionConfiguration` (which includes any read-only console user) can see plaintext env vars. Use Secrets Manager (below) even in dev.

### 7.3 — Store the API Key in Secrets Manager

1. Go to **Secrets Manager → Store a new secret**
2. Secret type: **Other type of secret**
3. In the **Key/value pairs** panel click **Plaintext** and paste only the raw API key (no JSON wrapper needed)
4. Click **Next**
5. Secret name: `yt-data-pipeline/youtube-api-key-dev`
6. Description: `Google YouTube Data API v3 key used by the ingestion Lambda`
7. Leave rotation disabled (manual rotation in Google Cloud Console is simpler for a tutorial)
8. Click **Next → Next → Store**
9. Open the secret and copy its ARN — you'll need it in Step 7.4

**Grant the Lambda role permission to read only this one secret:**

1. Go to **IAM → Roles → `yt-data-pipeline-lambda-role-dev` → Add permissions → Create inline policy**
2. Policy name: `yt-pipeline-youtube-secret-read`
3. JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "<SECRET_ARN_FROM_7.3_STEP_9>"
  }]
}
```

Scoping the `Resource` to this one secret's ARN — rather than `Resource: "*"` — means a compromised Lambda can't enumerate or read any other secrets in the account.

### 7.4 — Configure Environment Variables

Go to **Lambda → `yt-data-pipeline-youtube-ingestion-dev` → Configuration → Environment variables → Edit**:

| Key | Value | How to get it |
|-----|-------|---------------|
| `youtube_api_key_secret_arn` | Your Secrets Manager secret ARN from Step 7.3 | Full ARN, e.g. `arn:aws:secretsmanager:<region>:<account-id>:secret:yt-data-pipeline/youtube-api-key-dev-ABCD12` |
| `s3_bucket_bronze` | `yt-data-pipeline-bronze-<ACCOUNT_ID>-dev` | Your Bronze bucket name from [Step 1.1](#11--create-the-s3-buckets) |
| `youtube_regions` | `us,gb,ca,de,fr,in,jp,kr,mx,ru` | Comma-separated region codes — **lowercase** (see [7.7](#77--fix-region-case-sensitivity)) |
| `max_results` | `50` | Number of trending videos per API call per region (max 50) |
| `sns_alert_topic_arn` | `arn:aws:sns:<region>:<account-id>:yt-data-pipeline-alerts-dev` | From [Step 4.1](#41--create-the-topic-and-subscription) — find it in **SNS → Topics** |

> **Lambda code change:** the handler now reads the key via `boto3.client('secretsmanager').get_secret_value(SecretId=os.environ['youtube_api_key_secret_arn'])['SecretString']` instead of `os.environ['youtube_api_key']`. Cache the result at module scope — warm invocations reuse the same value and avoid extra Secrets Manager calls.

> **Note on transient API failures:** The YouTube Data API's `mostPopular` chart occasionally returns HTTP 400 for individual regions — the failing subset changes between runs (not a permanent regional restriction). The Lambda catches these per-region, records them as failed in the SNS summary, and continues. Expect 1–4 regions to fail on any given invocation; re-running usually fills the gaps. The Silver-layer ETL ([Step 11](#step-11-glue-etl--bronze-to-silver-statistics)) only reads `ca,gb,us` via predicate pushdown, so partial failures in the other 7 regions have no downstream impact.

### 7.5 — Add the Lambda Code

> **⚠ STOP — do not click the Test button after Deploy.** The Lambda console's default post-deploy flow is to pair Deploy with Test, and reviewers who blindly paste code and hit the two buttons in sequence will **break the Bronze pipeline**. Here's why: this Lambda writes live JSONs into the same `raw_statistics/` and `raw_statistics_reference_data/` prefixes the Bronze Crawler catalogs in [Step 8](#step-8-glue-crawler--catalog-bronze-data). If the Lambda runs first, the prefix mixes CSV (Kaggle) and JSON (API), and the crawler falls back to producing one table per file — tens of micro-tables instead of the two unified tables we need. Recovery is painful (see [Troubleshooting — Crawler creates wrong schema](#crawler-creates-wrong-schema--too-many-tables)).
>
> **Do this instead:**
>
> 1. Paste the code (below).
> 2. Click **Deploy**. **Stop there** — no Test click.
> 3. Finish [Step 7.6](#76--configure-resources) and [Step 7.7](#77--deploy-do-not-test-invoke-yet) — the latter just reiterates this warning once you're at the Deploy button.
> 4. Move on to [Step 8](#step-8-glue-crawler--catalog-bronze-data) and run the Bronze crawler first. The crawler needs to see a clean Kaggle-only Bronze bucket to produce the correct unified tables.
> 5. Come back to this Lambda only after Step 8 succeeds. Test-invoke is safe from that point forward — or you can skip it entirely and wait until [Step 14 Step Functions](#step-14-step-functions--pipeline-orchestration) orchestrates the first legitimate run end-to-end.

Paste the contents of [`docs/resources/lambda_youtube_api_ingestion.py`](docs/resources/lambda_youtube_api_ingestion.py) into the Lambda code editor.

The script:
1. Reads all environment variables at module level
2. Loops through each region in `youtube_regions`
3. Calls the YouTube Data API twice per region — once for trending videos, once for category reference data
4. Writes raw JSON to the Bronze bucket using Hive-style partitioning:
    - Trending videos → `youtube/raw_statistics/region=xx/date=YYYY-MM-DD/hour=HH/{ingestion_id}.json`
    - Category reference → `youtube/raw_statistics_reference_data/region=xx/date=YYYY-MM-DD/{region}_category_id.json`
5. On any failures, publishes a summary to the SNS alert topic

> **Why the nested `date=/hour=/` partitions:** The Lambda writes into the **same two top-level folders** as the Kaggle upload from [Step 6](#step-6-ingest--upload-the-kaggle-dataset) — but deeper, under sub-partitions. Kaggle's files sit at `region=ca/CAvideos.csv`; the Lambda's land at `region=ca/date=.../hour=.../ingestion_id.json`. They never overwrite each other. The deeper partitioning is future-proofing for partition pruning in Athena on the Silver tables, where the API data becomes queryable after the Silver ETL normalizes it to Parquet.

### 7.6 — Configure Resources

Go to **Lambda → function → Configuration → General configuration → Edit**:

| Setting | Value | Why |
|---------|-------|-----|
| Memory | **512 MB** | Handles JSON parsing for large API responses |
| Ephemeral storage | **1024 MB** | Buffer for writing multiple region files |
| Timeout | **5 minutes** | API calls for 10 regions can take a few minutes |

Click **Save**.

### 7.7 — Deploy (Do Not Test-Invoke Yet)

Click **Deploy** to save the function. **Do not click Test** at this stage — see the ordering warning at the top of [Step 7.5](#75--add-the-lambda-code). The Lambda's first legitimate invocation happens in one of two ways:

- Manually, **after** [Step 8](#step-8-glue-crawler--catalog-bronze-data) finishes cataloging the Kaggle data, or
- Automatically, when the Step Functions pipeline ([Step 14](#step-14-step-functions--pipeline-orchestration)) runs.

When you do invoke it, use an empty JSON `{}` test event (this Lambda doesn't read the event payload) and verify in CloudWatch Logs that all regions processed successfully, and in the Bronze S3 bucket that new JSON files appear under `youtube/raw_statistics/region=xx/date=.../hour=.../`.

### 7.8 — Fix: Region Case Sensitivity

> **Tutorial note:** The trainer initially had regions in uppercase in the environment variable (`US,GB,CA,...`), which caused the Lambda to create uppercase folders (`region=US/`) that didn't match the lowercase Kaggle data (`region=us/`). The fix is applied in the script itself — the line:
> ```python
> REGIONS = [r.strip().lower() for r in os.environ["youtube_regions"].split(",")]
> ```
> ensures all region codes are lowercased regardless of how they're entered in the environment variable. If you set your `youtube_regions` as lowercase from the start (as shown in Step 7.4), this is a non-issue — but the `.lower()` is there as a safety net.

> Terraform: [13. Lambda — YouTube API Ingestion](#13-lambda--youtube-api-ingestion)

&nbsp;

## Step 8: Glue Crawler — Catalog Bronze Data

The crawler scans the Bronze S3 bucket, infers schemas from the raw files, and registers tables in the Glue Data Catalog so they can be queried by Athena and read by ETL jobs.

> **⚠ Run this step BEFORE the YouTube API Lambda from [Step 7](#step-7-lambda--youtube-api-ingestion) is invoked.** The Bronze bucket at this point should contain only Kaggle CSVs under `raw_statistics/region=xx/` and Kaggle JSON category files under `raw_statistics_reference_data/region=xx/`. Once the API Lambda writes its own JSONs into these same prefixes, the crawler can no longer merge the mixed formats into the two unified tables below — it creates one micro-table per file instead. This Bronze crawler is a **one-time setup**; the downstream Silver ETL reads Bronze directly from S3 with Spark and never needs it again.

### 8.1 — Create the Crawler

#### Console

1. Go to **Glue → Data Catalog → Crawlers → Create crawler**
2. Name: `yt-data-pipeline-bronze-crawler-dev`
3. **Add a data source:**
   - Source: **S3**
   - Path: `s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/raw_statistics/`
4. **Add a second data source** (click **Add another data source**):
   - Source: **S3**
   - Path: `s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/raw_statistics_reference_data/`
5. IAM role: `yt-data-pipeline-glue-role-dev`
6. Target database: `yt_pipeline_bronze_dev`
7. Click **Create crawler**

#### CLI

```bash
aws glue create-crawler \
  --name yt-data-pipeline-bronze-crawler-dev \
  --role yt-data-pipeline-glue-role-dev \
  --database-name yt_pipeline_bronze_dev \
  --targets '{
    "S3Targets": [
      {"Path": "s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/raw_statistics/"},
      {"Path": "s3://yt-data-pipeline-bronze-<ACCOUNT_ID>-dev/youtube/raw_statistics_reference_data/"}
    ]
  }' \
  --region <YOUR_REGION>
```

### 8.2 — Run the Crawler

#### Console

1. Go to **Glue → Data Catalog → Crawlers → `yt-data-pipeline-bronze-crawler-dev`**
2. Click **Run crawler**
3. Wait for status to show **Ready** (takes 1-2 minutes)

#### CLI

```bash
aws glue start-crawler --name yt-data-pipeline-bronze-crawler-dev --region <YOUR_REGION>
```

**What the crawler produces** — two tables in `yt_pipeline_bronze_dev`:

| Table | Source | Format | Partition |
|-------|--------|--------|-----------|
| `raw_statistics` | `youtube/raw_statistics/region=xx/` | CSV (Kaggle) | `region` (from Hive-style paths) |
| `raw_statistics_reference_data` | `youtube/raw_statistics_reference_data/region=xx/` | JSON (Kaggle static category files) | `region` |

### 8.3 — Dataset Schema

The Kaggle dataset contains ~200 daily trending videos per region. The crawler discovers these columns for `raw_statistics`:

| Column | Type | Description |
|--------|------|-------------|
| `video_id` | STRING | YouTube video identifier |
| `trending_date` | STRING | Date the video was trending (YY.DD.MM format — cleaned to YYYY-MM-DD in Silver) |
| `title` | STRING | Video title |
| `channel_title` | STRING | Channel name |
| `category_id` | LONG | Numeric category ID (maps to JSON reference file) |
| `publish_time` | STRING | Video publish timestamp |
| `tags` | STRING | Pipe-separated tag list |
| `views` | LONG | View count |
| `likes` | LONG | Like count |
| `dislikes` | LONG | Dislike count |
| `comment_count` | LONG | Number of comments |
| `thumbnail_link` | STRING | Thumbnail URL |
| `comments_disabled` | BOOLEAN | Whether comments are disabled |
| `ratings_disabled` | BOOLEAN | Whether ratings are disabled |
| `video_error_or_removed` | BOOLEAN | Whether the video was removed |
| `description` | STRING | Video description text |
| `region` | STRING | Two-letter country code (partition key) |

The JSON `raw_statistics_reference_data` table maps `category_id` to human-readable category names (Music, Entertainment, Film & Animation, Sports, etc.).

> Terraform: [8. Glue Crawler (Bronze)](#8-glue-crawler-bronze)

&nbsp;

## Step 9: Athena — Explore Bronze Data

After the crawler runs, use Athena to verify the cataloged data. This is also where you'll notice the data quality issues (messy date formats, nulls, etc.) that the Silver layer will fix.

### 9.1 — Configure Query Results

Athena needs a dedicated workgroup plus an S3 location to store query output. Creating a workgroup (rather than using the default `primary` workgroup) lets you apply least-privilege IAM — the DQ Gate Lambda in [Step 12](#step-12-lambda--data-quality-gate) will be scoped to this one workgroup, so it can't run queries in other workgroups (which might have different scan limits, result buckets, or billing tags).

> **Why not reuse `primary`?** The `primary` workgroup is auto-created per region by AWS (similar to the `default` Glue database). You can't delete it — AWS will recreate it. It's usually pre-pointed at a result bucket from whatever project first touched Athena in your account, with `Override client-side settings` turned off. Reusing it would mix this pipeline's query output with unrelated projects and defeat the IAM scoping we set up in [Step 2.2.2](#222--add-the-inline-policy). Create a dedicated workgroup instead.

#### Console

1. Go to **Athena → Workgroups → Create workgroup**
2. Workgroup name: `yt-pipeline-dev`
3. Description: `YouTube pipeline workgroup — Bronze exploration, DQ checks, Gold queries`
4. Under **Query result configuration**, switch the radio from the default **Athena managed** to **Customer managed**. This is the critical step — `Athena managed` creates a new AWS-owned bucket and ignores the one you built in Step 1.1. `Customer managed` expands the panel to reveal a **Location of query result** textbox:
    - Click **Browse S3** and select `yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev`, or paste `s3://yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/` into the textbox
    - AWS may suggest a "Lifecycle configuration" — skip it for this learning guide (see the Athena-results production note in [Step 1.2](#12--s3-lifecycle-rule-bronze-bucket))
5. Below the S3 location field, **check "Override client-side settings"**. This forces every query submitted to this workgroup to use the result location above — without it, clients (Query Editor, DQ Gate Lambda, QuickSight) can override the location and defeat the IAM scoping we set up in [Step 2.2](#22--lambda-execution-role)
6. Click **Create workgroup**

Everything else on the form (Authentication, the other Customer-managed checkboxes, Settings, Workgroup data usage alerts, Tags) can stay at its default — none of them affect this pipeline.

**Switch Athena to use the new workgroup** — in the top-right of the Athena query editor there's a workgroup dropdown (defaults to `primary`). Click it and pick `yt-pipeline-dev`. Every query you run from now on (Bronze exploration here, Gold queries in [Step 15](#step-15-athena--query-the-gold-layer), DQ checks from the Lambda) should use this workgroup.

#### CLI

```bash
aws athena create-work-group \
  --name yt-pipeline-dev \
  --description "YouTube pipeline workgroup" \
  --configuration "ResultConfiguration={OutputLocation=s3://yt-data-pipeline-athena-results-<ACCOUNT_ID>-dev/},EnforceWorkGroupConfiguration=true" \
  --region <YOUR_REGION>
```

You only need to do this once per AWS account per region — the workgroup persists across sessions and applies to both Bronze ([Step 9](#step-9-athena--explore-bronze-data)) and Gold ([Step 15](#step-15-athena--query-the-gold-layer)) queries.

### 9.2 — Query the Bronze Tables

Select `yt_pipeline_bronze_dev` as the database in the Athena query editor and run:

```sql
-- Preview the raw CSV statistics
SELECT * FROM raw_statistics LIMIT 10;

-- Check partitions
SELECT region, COUNT(*) FROM raw_statistics GROUP BY region;
```

> **JSON table limitation:** Athena cannot directly query the `raw_statistics_reference_data` table in its raw JSON form — the nested `items` array needs to be flattened first. This is exactly what the JSON-to-Parquet Lambda does in [Step 10](#step-10-lambda--json-to-parquet).

&nbsp;

## Step 10: Lambda — JSON-to-Parquet

Second half of Data Flow **#3 CLEAN**. This Lambda flattens the nested JSON category-reference files that land in Bronze (both Kaggle static and YouTube API live) and writes cleansed Parquet to Silver. It's S3-event-triggered: every time a new reference JSON lands in `raw_statistics_reference_data/`, this function fires.

The execution role from [Step 2.2](#22--lambda-execution-role) already carries every permission this function needs (S3 read/write, Glue Catalog writes).

### 10.1 — Create the Lambda Function

1. Go to **Lambda → Create function**
2. **Author from scratch**
3. Function name: `yt-data-pipeline-json-to-parquet-dev`
4. Runtime: **Python 3.12**
5. Scroll down and expand the **Custom settings** accordion (collapsed by default — without expanding it, you can't see the toggle in step 6). Inside, toggle on **Custom execution role**
6. In the **Configure custom execution role** panel that opens, select `yt-data-pipeline-lambda-role-dev` from the **Execution role** dropdown
7. Click **Save** — the panel closes and shows your role under **IAM permissions**
8. Click **Create function**

### 10.2 — Configure Resources (Memory + Timeout)

Go to **Lambda → `yt-data-pipeline-json-to-parquet-dev` → Configuration → General configuration → Edit**:

| Setting | Value | Why |
|---------|-------|-----|
| Timeout | **60 seconds** | Reading, flattening, and writing a single JSON reference file is fast, but `awswrangler`'s Glue Catalog sync can take a few seconds |
| Memory | **512 MB** | pandas + awswrangler need more than the 128 MB default to import cleanly |

Click **Save**.

### 10.3 — Attach the AWS Data Wrangler Layer

The function imports `awswrangler` (AWS SDK for pandas), which is not in the stock Python runtime.

1. Go to **Lambda → `yt-data-pipeline-json-to-parquet-dev`** and **scroll down past the Code source and Runtime settings panels** until you see the **Layers** panel (it's near the bottom of the function detail page — easy to miss on your first scroll). Click **Edit** in its top-right corner, then **Add a layer**.
2. Choose **AWS layers** → search for `AWSSDKPandas-Python312`
3. Select the **latest version** → **Add**

> **Why a layer?** `awswrangler` bundles pandas, pyarrow, numpy, and boto3 extras — bundling them directly into the function's zip would blow past Lambda's 50 MB upload limit. AWS publishes the layer officially; you can also pin a specific ARN in Terraform (shown in the Terraform section). This same layer is also used by the Data Quality Gate Lambda in [Step 12](#step-12-lambda--data-quality-gate).

### 10.4 — Configure Environment Variables

Go to **Lambda → function → Configuration → Environment variables → Edit** and add:

| Key | Value | Purpose |
|-----|-------|---------|
| `s3_cleansed_layer` | `s3://yt-data-pipeline-silver-<ACCOUNT_ID>-dev/youtube/raw_statistics_reference_data/` | Target S3 path where the Parquet output is written |
| `glue_catalog_db_name` | `yt_pipeline_silver_dev` | Silver Glue database the output table is registered under (created in [Step 5.1](#51--create-the-three-medallion-databases)) |
| `glue_catalog_table_name` | `clean_reference_data` | Name the output table receives in the Glue Catalog |
| `write_data_operation` | `append` | `awswrangler` write mode — `append` adds new partitions without rewriting existing ones (`overwrite` / `overwrite_partitions` also available) |

> **⚠ Two copy-paste traps to double-check before you deploy:**
>
> 1. **Key names must match the code exactly.** The Lambda reads `os.environ['glue_catalog_table_name']`, etc. The console's **Environment variables** UI lets you save any key name you want — it won't warn you if you typo `glue_catalog_tab` or `glue_catalog_table`. Mistyped keys surface as a `KeyError` crash at function init (not during testing — before the handler even runs), with a log line like `[ERROR] KeyError: 'glue_catalog_table_name'`.
>
> 2. **`<region>` must be your actual bucket name.** If your Step 1.1 buckets include a unique prefix (e.g. `yourname-yt-data-pipeline-silver-eu-north-1-dev`), substitute the full exact bucket name into the `s3_cleansed_layer` value — don't just replace `<region>` and leave the generic `yt-data-pipeline-` prefix. The Lambda hits `NoSuchBucket` at write time if the name doesn't match your real bucket.

### 10.5 — Add the Lambda Code

Paste the contents of [`docs/resources/lambda_json_to_parquet.py`](docs/resources/lambda_json_to_parquet.py) into the code editor, then click **Deploy**.

**Source file:** [`lambda_function.py`](https://github.com/darshilparmar/dataengineering-youtube-analysis-project/blob/main/lambda_function.py) — note the reference implementation in this guide differs from the trainer's original: the trainer used `wr.s3.read_json()` directly, which fails on the YouTube Data API v3 response shape with `ValueError: Mixing dicts with non-Series may lead to ambiguous ordering`. The guide's version in [`docs/resources/lambda_json_to_parquet.py`](docs/resources/lambda_json_to_parquet.py) fetches the raw bytes with boto3 and parses them with stdlib `json` first, then flattens `items` — which sidesteps pandas's mixed-type-top-level parser entirely.

What the script does:
1. Reads the S3 event to get the bucket and key of the new JSON file.
2. Uses `boto3.s3.get_object()` + stdlib `json.loads()` to fetch and parse the raw JSON. (Not `awswrangler.s3.read_json()` — that uses pandas's top-level JSON parser which fails on the API's mixed scalar+array response shape; see note in Step 10.5 above.)
3. Pulls the `items` array out of the response and flattens it with `pandas.json_normalize()` into a flat tabular shape (one row per video category, columns like `id`, `snippet.title`, `snippet.assignable`).
4. Writes cleansed Parquet to the Silver bucket with `awswrangler.s3.to_parquet(dataset=True, database=..., table=...)` — the same call registers (or updates) the output as a Glue table in the Silver catalog, so no separate crawler is needed.

### 10.6 — Add the S3 Trigger

Configures the Bronze bucket to invoke this Lambda every time a new JSON category-reference file lands.

#### Console

1. Go to **Lambda → `yt-data-pipeline-json-to-parquet-dev` → Add trigger**
2. Source: **S3**
3. Bucket: `yt-data-pipeline-bronze-<ACCOUNT_ID>-dev`
4. Event type: **All object create events**
5. Prefix: `youtube/raw_statistics_reference_data/`
6. Suffix: `.json`
7. Check the **recursive invocation** acknowledgement checkbox and click **Add**

> **Why a prefix + suffix filter?** Without them, this Lambda would fire on every object that lands in Bronze — including the Glue Crawler's temp files, CSV statistics uploads, and Lambda-produced JSONs under `raw_statistics/` (which are the **statistics** data, not reference data — those get processed by the Silver Glue ETL job, not by this Lambda).

### 10.7 — Validate End-to-End

Unlike the original tutorial, at this point you have everything needed to validate the full trigger chain. Invoke the YouTube API Lambda ([Step 7](#step-7-lambda--youtube-api-ingestion)) with an empty test event `{}` — it will write JSONs into `raw_statistics_reference_data/` which causes this Lambda to fire automatically.

Verify:

1. **CloudWatch** — Go to **Lambda → `yt-data-pipeline-json-to-parquet-dev` → Monitor → View CloudWatch logs**. You should see one invocation per region-reference JSON (10 invocations).
2. **Silver bucket** — `youtube/raw_statistics_reference_data/` should contain `.parquet` files under the Hive-style partitions.
3. **Glue Catalog** — the `yt_pipeline_silver_dev` database should now have a `clean_reference_data` table with partitions.

### 10.8 — CLI Alternative

Self-contained script that creates the function (with layer + env vars in one go), uploads the code zip, and wires up the S3 trigger:

```bash
# 1. Zip the handler
zip /tmp/lambda_json_to_parquet.zip docs/resources/lambda_json_to_parquet.py

# 2. Resolve the latest AWSSDKPandas layer ARN for your region.
#    Replace <YOUR_REGION>. The `:27` version is current as of late 2025; AWS publishes new versions periodically
#    and old ones are eventually deprecated. To look up the current version in your region:
#        aws lambda list-layer-versions --layer-name AWSSDKPandas-Python312 --region <YOUR_REGION> \
#          --query 'LayerVersions[0].LayerVersionArn' --output text
LAYER_ARN="arn:aws:lambda:<YOUR_REGION>:336392948345:layer:AWSSDKPandas-Python312:27"

# 3. Create the function
aws lambda create-function \
  --function-name yt-data-pipeline-json-to-parquet-dev \
  --runtime python3.12 \
  --role "arn:aws:iam::<ACCOUNT_ID>:role/yt-data-pipeline-lambda-role-dev" \
  --handler lambda_json_to_parquet.lambda_handler \
  --timeout 60 \
  --memory-size 512 \
  --zip-file fileb:///tmp/lambda_json_to_parquet.zip \
  --layers "$LAYER_ARN" \
  --environment "Variables={s3_cleansed_layer=s3://yt-data-pipeline-silver-<YOUR_REGION>-dev/youtube/raw_statistics_reference_data/,glue_catalog_db_name=yt_pipeline_silver_dev,glue_catalog_table_name=clean_reference_data,write_data_operation=append}"

# 4. Grant S3 permission to invoke the Lambda
aws lambda add-permission \
  --function-name yt-data-pipeline-json-to-parquet-dev \
  --statement-id AllowS3InvokeJsonToParquet \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::yt-data-pipeline-bronze-<YOUR_REGION>-dev"

# 5. Configure the S3 event notification
aws s3api put-bucket-notification-configuration \
  --bucket yt-data-pipeline-bronze-<YOUR_REGION>-dev \
  --notification-configuration "$(cat <<'EOF'
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "TriggerJsonToParquetOnReferenceData",
      "LambdaFunctionArn": "arn:aws:lambda:<YOUR_REGION>:<ACCOUNT_ID>:function:yt-data-pipeline-json-to-parquet-dev",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            { "Name": "prefix", "Value": "youtube/raw_statistics_reference_data/" },
            { "Name": "suffix", "Value": ".json" }
          ]
        }
      }
    }
  ]
}
EOF
)"
```

> Terraform: [9. Lambda — JSON to Parquet](#9-lambda--json-to-parquet) · [10. S3 Event Notification (Lambda Trigger)](#10-s3-event-notification-lambda-trigger)

&nbsp;

## Step 11: Glue ETL — Bronze to Silver (Statistics)

This Glue job reads the `raw_statistics` Bronze table and writes cleansed, partitioned Parquet to Silver. It mirrors the trainer's [`pyspark_code.py`](https://github.com/darshilparmar/dataengineering-youtube-analysis-project/blob/main/pyspark_code.py) with two reusability tweaks: job parameters instead of hard-coded paths, and no `sys.exit(0)` (Glue 5.0 treats any `SystemExit` as job failure). The job uses Glue's `DynamicFrame` API — `ApplyMapping` → `ResolveChoice("make_struct")` → `DropNullFields` — which is the right tool when the Bronze prefix can contain rows with differing column shapes: `DynamicFrame`'s `ChoiceType` absorbs the mismatch instead of raising `UNRESOLVED_COLUMN` the way a strict Spark `DataFrame.select(F.col(...))` would.

### 11.1 — Create the Glue Job

#### Console

1. Go to **Glue → ETL jobs → Script editor**
2. Engine: **Spark**
3. Options: **Start fresh**
4. Click **Create script**
5. Paste the PySpark script from [`docs/resources/glue_bronze_to_silver.py`](docs/resources/glue_bronze_to_silver.py) into the editor
6. Go to **Job details** tab and configure:

| Setting | Value |
|---------|-------|
| Name | `yt-data-pipeline-bronze-to-silver-dev` |
| IAM Role | `yt-data-pipeline-glue-role-dev` |
| Worker type | **G.1X** |
| Number of workers | **2** (reduced from default 10 to minimize cost) |
| Job timeout | **30 minutes** |
| Job bookmark | **Enable** (prevents reprocessing) |

7. Under **Job parameters**, add:

| Key | Value |
|-----|-------|
| `--bronze_database` | `yt_pipeline_bronze_dev` |
| `--bronze_table` | `raw_statistics` |
| `--silver_bucket` | `yt-data-pipeline-silver-<ACCOUNT_ID>-dev` |
| `--silver_database` | `yt_pipeline_silver_dev` |
| `--silver_table` | `clean_statistics` |

> **Bucket name substitution** — replace `<ACCOUNT_ID>` in `--silver_bucket` with your 12-digit AWS account ID from [Step 1.1](#11--create-the-s3-buckets). Just the bucket name, no `s3://` prefix, no trailing slash — the script builds the full URI itself.
>
> **⚠ Job-parameter console quirk:** The Job parameters grid in the Glue console's Job details tab silently preserves leading/trailing whitespace. After saving, reopen Job details and eyeball the `--silver_bucket` value — if the cursor sits one character to the left of the first letter when you press Home, delete the invisible space. A leading space turns the bucket name into an invalid URI and the job fails with `NoSuchBucket`. Same applies to any other bucket-name param you set.

8. Click **Save** → **Run**

#### CLI

```bash
# Upload the script to S3 first
aws s3 cp docs/resources/glue_bronze_to_silver.py \
  s3://yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/glue/glue_bronze_to_silver.py

# Create the job
aws glue create-job \
  --name yt-data-pipeline-bronze-to-silver-dev \
  --role yt-data-pipeline-glue-role-dev \
  --command '{
    "Name": "glueetl",
    "ScriptLocation": "s3://yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/glue/glue_bronze_to_silver.py",
    "PythonVersion": "3"
  }' \
  --default-arguments '{
    "--bronze_database": "yt_pipeline_bronze_dev",
    "--bronze_table": "raw_statistics",
    "--silver_bucket": "yt-data-pipeline-silver-<ACCOUNT_ID>-dev",
    "--silver_database": "yt_pipeline_silver_dev",
    "--silver_table": "clean_statistics",
    "--job-bookmark-option": "job-bookmark-enable"
  }' \
  --glue-version "5.0" \
  --number-of-workers 2 \
  --worker-type "G.1X" \
  --region <YOUR_REGION>
```

### 11.2 — What the PySpark Script Does

The script you pasted in [11.1.5](#111--create-the-glue-job) reads job parameters via `getResolvedOptions` — the values you configured in 11.1.7. Here's the parameter map for reference:

| Parameter | Purpose |
|-----------|---------|
| `--bronze_database` | Glue database to read from (`yt_pipeline_bronze_dev`) |
| `--bronze_table` | Table name to read (`raw_statistics`) |
| `--silver_bucket` | Silver S3 bucket name (path is `s3://<bucket>/youtube/statistics/`) |
| `--silver_database` | Silver Glue database (`yt_pipeline_silver_dev`) |
| `--silver_table` | Silver catalog table name (`clean_statistics`) |

**Transformations the script applies, in order** (mirrors the trainer's [`pyspark_code.py`](https://github.com/darshilparmar/dataengineering-youtube-analysis-project/blob/main/pyspark_code.py) with minor reusability tweaks):

1. **Predicate pushdown** — filters to `ca, gb, us, in` regions at source (avoids scanning all partitions)
2. **ApplyMapping** — casts the 17 catalog columns (16 CSV columns + `region` partition) to their Silver types. Columns absent from a given row (e.g. from JSON-shaped sources served against a CSV-only catalog schema) are tolerated and surface as nulls downstream.
3. **ResolveChoice (`make_struct`)** — Glue's `DynamicFrame` tracks ambiguous types as `ChoiceType` when a column is seen as e.g. both `long` and `string` across rows. `make_struct` packs the alternatives into a single struct so no row errors out the job.
4. **DropNullFields** — strips columns that ended up fully null for the batch (nothing to store).
5. **Parquet output** — coalesced to 1 partition per region and written via `glueContext.write_dynamic_frame.from_options` to `s3://<silver_bucket>/youtube/statistics/`, Snappy-compressed, partitioned by `region`.
6. **Catalog registration** — the job explicitly `CREATE TABLE ... USING PARQUET LOCATION ...` + `MSCK REPAIR TABLE` at the end (instead of `enableUpdateCatalog=True`, which has append-only semantics that break on re-runs).

Silver is deliberately minimal: it stores the cleansed statistics as-is. Deriving analytics fields like `like_ratio`, `engagement_rate`, or `trending_date_parsed` is the Silver→Gold job's responsibility ([Step 13](#step-13-glue-etl--silver-to-gold)) — keeping Silver flat makes it cheap to reprocess and easy to join against on the Athena side.

### 11.3 — Verify the Silver Output

After the job's **Run** status reaches **Succeeded** (check under **Glue → ETL jobs → `yt-data-pipeline-bronze-to-silver-dev` → Runs**; first run takes 2–5 minutes because of Spark cold start), confirm:

1. **Silver bucket** — objects should appear under `s3://yt-data-pipeline-silver-<ACCOUNT_ID>-dev/youtube/statistics/region={ca,gb,in,us}/` (4 partitions × 1 Parquet file each because of the `coalesce(1)` before write)
2. **Silver catalog** — `yt_pipeline_silver_dev.clean_statistics` should exist with 17 columns (the 16 CSV columns from the Bronze catalog + `region` partition column). Matches the trainer's Silver schema 1:1 — analytics-derived fields (`like_ratio`, `engagement_rate`, `trending_date_parsed`) are produced later by the Silver→Gold job, not here.
3. **Athena spot-check** — switch to the `yt-pipeline-dev` workgroup in the query editor, then run:
   ```sql
   SELECT region, COUNT(*) FROM yt_pipeline_silver_dev.clean_statistics GROUP BY region ORDER BY region;
   ```
   You should see 4 regions. Row counts mirror the raw Kaggle CSVs almost 1:1 (the trainer's approach intentionally does not dedup at Silver — that's a Gold-time choice if needed).

> Terraform: [11. Glue ETL Job (Bronze → Silver)](#11-glue-etl-job-bronze--silver)

&nbsp;

## Step 12: Lambda — Data Quality Gate

Data Flow **#5 QUALITY** — the gate between Silver and Gold. By this point, the Silver `clean_statistics` table (from [Step 11](#step-11-glue-etl--bronze-to-silver-statistics)) and `clean_reference_data` table (from [Step 10](#step-10-lambda--json-to-parquet)) both exist in `yt_pipeline_silver_dev`. This Lambda validates them and blocks the Gold aggregation if any check fails. The Step Functions workflow ([Step 14](#step-14-step-functions--pipeline-orchestration)) uses this Lambda as its gate between Silver and Gold.

### 12.1 — Create the Lambda Function

#### Console

1. Go to **Lambda → Create function**
2. **Author from scratch**
3. Function name: `yt-data-pipeline-data-quality-dev`
4. Runtime: **Python 3.12**
5. Scroll down and expand the **Custom settings** accordion (collapsed by default — without expanding it, you can't see the toggle in step 6). Inside, toggle on **Custom execution role**
6. In the **Configure custom execution role** panel, select `yt-data-pipeline-lambda-role-dev` from the **Execution role** dropdown
7. Click **Save** → **Create function**

### 12.2 — Configure Resources

Go to **Lambda → function → Configuration → General configuration → Edit**:

| Setting | Value | Why |
|---------|-------|-----|
| Memory | **512 MB** | Pandas + awswrangler need headroom |
| Timeout | **60 seconds** | Athena queries + in-memory validation |

Click **Save**.

### 12.3 — Attach the awswrangler Lambda Layer

The DQ Lambda uses [`awswrangler`](https://aws-sdk-pandas.readthedocs.io/) (AWS SDK for pandas) to read from Athena. Attach the same public `AWSSDKPandas-Python312` layer used in [Step 10.3](#103--attach-the-aws-data-wrangler-layer).

### 12.4 — Configure Environment Variables

Go to **Lambda → function → Configuration → Environment variables → Edit**:

| Key | Value | How to get it |
|-----|-------|---------------|
| `DQ_MIN_ROW_COUNT` | `10` | Minimum rows per table to pass the row-count check |
| `DQ_MAX_NULL_PERCENT` | `5.0` | Max allowed null percentage for critical columns |
| `ATHENA_WORKGROUP` | `yt-pipeline-dev` | The dedicated workgroup created in [Step 9.1](#91--configure-query-results). **Must be set explicitly** — without this env var the code falls back to the `primary` workgroup, which the least-privilege IAM policy from [Step 2.2.2](#222--add-the-inline-policy) does NOT permit, and you'll get `AccessDeniedException: athena:GetWorkGroup` on the first test invocation. |
| `SNS_ALERT_TOPIC_ARN` | `arn:aws:sns:<region>:<account-id>:yt-data-pipeline-alerts-dev` | From [Step 4.1](#41--create-the-topic-and-subscription) |

### 12.5 — Add the Lambda Code

Paste the contents of [`docs/resources/lambda_data_quality.py`](docs/resources/lambda_data_quality.py) into the Lambda code editor and **Deploy**.

The function:
1. Accepts a `{database, tables}` payload (defaults to `yt_pipeline_silver_dev` + `clean_statistics`).
2. Reads up to 10,000 rows per table via `awswrangler.athena.read_sql_query`.
3. Runs 5 check families per table:
    - **row_count** — table has ≥ `DQ_MIN_ROW_COUNT` rows
    - **null_pct** — critical columns have ≤ `DQ_MAX_NULL_PERCENT` nulls
    - **schema** — all expected columns exist
    - **value_range** — views are non-negative and ≤ 50 billion
    - **freshness** — latest `_processed_at` / `_ingestion_timestamp` is within 48h. Auto-skips (passes with a "no timestamp column" note) when the Silver table doesn't carry one, as with the trainer-style Bronze→Silver that only writes the raw cleansed columns.
4. Returns `{"quality_passed": bool, "checks_passed": N, "checks_total": M, "details": [...]}` — Step Functions uses `quality_passed` to gate the Gold job.
5. On failure, publishes a summary to the SNS alerts topic.

### 12.6 — Test

Use a test event:

```json
{
  "database": "yt_pipeline_silver_dev",
  "tables": ["clean_statistics"]
}
```

Expected response on a healthy Silver:

```json
{
  "quality_passed": true,
  "checks_passed": 9,
  "checks_total": 9,
  "details": [...]
}
```

> **If the first test invocation fails with `AccessDeniedException` on the workgroup, S3 bucket, or Glue Catalog** — wait ~60 seconds and re-invoke. IAM policy updates have a short propagation delay, especially the first time a fresh Lambda role is exercised. The simulator (`aws iam simulate-principal-policy`) may already say "allowed" while the Lambda's execution context is still on the pre-update cached version. If it's still failing after 60 seconds, compare the bucket ARN in the policy against your actual bucket name from Step 1.1 — any mismatch (generic `yt-data-pipeline-...` vs. your prefixed `yourname-yt-data-pipeline-...`) will manifest as `InvalidRequestException: Unable to verify/create output bucket`.

> Terraform: [14. Lambda — Data Quality Gate](#14-lambda--data-quality-gate)

&nbsp;

## Step 13: Glue ETL — Silver to Gold

Joins the cleansed Silver statistics with the cleansed reference data (for category names), then produces three business-level aggregate tables in Gold, each partitioned by `region` and written as Snappy-compressed Parquet.

> **Idempotency:** This job uses Spark's `DataFrameWriter.mode("overwrite")` with `spark.sql.sources.partitionOverwriteMode = dynamic`. Running the job twice with the same Silver input produces the same Gold state — per-partition atomic replace, no row-level doubling. The previous `getSink(enableUpdateCatalog=True)` pattern defaulted to append and would have double-counted aggregates on every re-run (see Step 13.2 for the full explanation).
>
> **Catalog registration moved out of the ETL job.** Because we're no longer using `getSink`'s auto-register mechanism, the Gold Glue Catalog is refreshed by a dedicated crawler ([Step 13.4](#134--create-the-gold-crawler)) that runs as the next state in the Step Functions pipeline. Decoupling compute from catalog-refresh means a transient Glue Catalog failure doesn't roll back a successful ETL run — each concern is retried independently.

### 13.1 — Create the Glue Job

#### Console

1. Go to **Glue → ETL jobs → Script editor**
2. Engine: **Spark**
3. Options: **Start fresh**
4. Click **Create script**
5. Paste the contents of [`docs/resources/glue_silver_to_gold.py`](docs/resources/glue_silver_to_gold.py) into the editor
6. Go to **Job details** tab and configure:

| Setting | Value |
|---------|-------|
| Name | `yt-data-pipeline-silver-to-gold-dev` |
| IAM Role | `yt-data-pipeline-glue-role-dev` |
| Worker type | **G.1X** |
| Number of workers | **2** |
| Job timeout | **30 minutes** |
| Job bookmark | **Disable** (Gold is a full refresh on every run) |

7. Under **Job parameters**, add:

| Key | Value |
|-----|-------|
| `--silver_database` | `yt_pipeline_silver_dev` |
| `--gold_bucket` | `yt-data-pipeline-gold-<ACCOUNT_ID>-dev` |

> **Bucket name substitution** — replace `<ACCOUNT_ID>` in `--gold_bucket` with your 12-digit AWS account ID from [Step 1.1](#11--create-the-s3-buckets). Just the bucket name, no `s3://` prefix. Same leading-whitespace warning from [Step 11.1](#111--create-the-glue-job) applies — re-check the value after saving.
>
> Note: `--gold_database` is **not** passed to this job. The script writes Parquet to S3 only — the Gold Glue Catalog database is populated by the Gold crawler created in [Step 13.4](#134--create-the-gold-crawler).

8. Click **Save** → **Run**

#### CLI

```bash
# Upload the script to S3 first
aws s3 cp docs/resources/glue_silver_to_gold.py \
  s3://yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/glue/glue_silver_to_gold.py

# Create the job
aws glue create-job \
  --name yt-data-pipeline-silver-to-gold-dev \
  --role yt-data-pipeline-glue-role-dev \
  --command '{
    "Name": "glueetl",
    "ScriptLocation": "s3://yt-data-pipeline-scripts-<ACCOUNT_ID>-dev/glue/glue_silver_to_gold.py",
    "PythonVersion": "3"
  }' \
  --default-arguments '{
    "--silver_database": "yt_pipeline_silver_dev",
    "--gold_bucket": "yt-data-pipeline-gold-<ACCOUNT_ID>-dev"
  }' \
  --glue-version "5.0" \
  --number-of-workers 2 \
  --worker-type "G.1X" \
  --region <YOUR_REGION>
```

### 13.2 — What It Does

1. **Read Silver statistics** from `yt_pipeline_silver_dev.clean_statistics` (the trainer-style flat Silver — 17 columns, no derivations).
2. **Optional join with reference data** — reads `clean_reference_data`, handles both `snippet.title` and `snippet_title` flattening variants, broadcasts a `(category_id → category_name)` lookup, and left-joins it. If reference data is missing or unreadable, fills `category_name = "Unknown"` so aggregations still succeed.
3. **Derive analytics columns** — computes `trending_date_parsed` (via `to_date(trending_date, 'yy.dd.MM')` since Kaggle encodes dates as `YY.DD.MM`), `like_ratio = likes / (likes + dislikes)`, and `engagement_rate = (likes + dislikes + comment_count) / views`. Kept here (not in Silver) so Silver can mirror the trainer's minimal schema 1:1 and stay cheap to reprocess.
4. **Produces three Gold tables**, each written to `s3://<gold_bucket>/youtube/<table_name>/` in Snappy-compressed Parquet, partitioned by `region`:

| Gold Table | Grouping | What it's for |
|------------|----------|---------------|
| `trending_analytics` | `region × trending_date` | Daily trending summaries — total videos, views, likes, engagement, unique channels, unique categories |
| `channel_analytics` | `channel_title × region` | Per-channel performance — total views, engagement, times trending, first/last trending date, category set. Includes `rank_in_region` column |
| `category_analytics` | `category × region × trending_date` | Category-level trends — video count, views, engagement, plus `view_share_pct` (category's share of regional views per day) |

5. **Writes each table with `DataFrameWriter.mode("overwrite")`** plus `spark.sql.sources.partitionOverwriteMode = dynamic`. The Gold Glue Catalog is not touched here — the crawler created in [Step 13.4](#134--create-the-gold-crawler) does that in a separate Step Functions state right after this job finishes.

> **Why explicit overwrite instead of `getSink(enableUpdateCatalog=True)`?** The Glue `getSink()` API — and the related `glueContext.write_dynamic_frame.from_options()` — has no `mode` parameter. Its default behaviour is **append**: every run adds a new set of Parquet files under the target prefix alongside the previous output. Because the catalog table points at the whole prefix, Athena would then read the union of every run. A `SELECT SUM(views) FROM trending_analytics WHERE region = 'us'` would grow linearly with the number of pipeline runs — not a row-level duplicate, but a double-count of every aggregated metric.
>
> Spark's `DataFrameWriter.mode("overwrite")` commits atomically from the driver's perspective (writes go to a staging directory, then a single commit swap). With `partitionOverwriteMode=dynamic`, only the partitions *emitted by the current run* are replaced — partitions for regions that happen to be absent from this run's Silver input are left alone. Together this gives a strict idempotency guarantee: **running the pipeline twice produces the same Gold state as running it once.**

### 13.3 — Gold Table Schemas

**`trending_analytics`** — daily regional summaries:

| Column | Type | Description |
|--------|------|-------------|
| `region` | STRING | Partition key |
| `trending_date_parsed` | DATE | Day being summarized |
| `total_videos` | LONG | Count of trending videos |
| `total_views`, `total_likes`, `total_dislikes`, `total_comments` | LONG | Sum aggregates |
| `avg_views_per_video`, `avg_like_ratio`, `avg_engagement_rate` | DOUBLE | Averages |
| `max_views` | LONG | Peak view count for the day |
| `unique_channels`, `unique_categories` | LONG | Distinct counts |
| `_aggregated_at` | TIMESTAMP | When this row was computed |

**`channel_analytics`** — channel performance ranked within region:

| Column | Type | Description |
|--------|------|-------------|
| `channel_title` | STRING | Channel name |
| `region` | STRING | Partition key |
| `total_videos`, `total_views`, `total_likes`, `total_comments` | LONG | Sums |
| `avg_views_per_video`, `avg_engagement_rate` | DOUBLE | Averages |
| `peak_views` | LONG | Best-performing video for the channel |
| `times_trending` | LONG | How many trending-day entries this channel has |
| `first_trending`, `last_trending` | DATE | Date range channel was seen in trending |
| `categories` | ARRAY\<STRING\> | Distinct category names the channel appeared in |
| `rank_in_region` | LONG | Row number (by `total_views` desc) within region |
| `_aggregated_at` | TIMESTAMP | When this row was computed |

**`category_analytics`** — category trends over time with view share:

| Column | Type | Description |
|--------|------|-------------|
| `category_name`, `category_id` | STRING, LONG | Category identity |
| `region` | STRING | Partition key |
| `trending_date_parsed` | DATE | Day being summarized |
| `video_count` | LONG | Trending videos in category that day |
| `total_views`, `total_likes`, `total_comments` | LONG | Sums |
| `avg_engagement_rate` | DOUBLE | Average engagement |
| `unique_channels` | LONG | Distinct channels in category |
| `view_share_pct` | DOUBLE | Share of regional views for the day (sums to 100 per region+day) |
| `_aggregated_at` | TIMESTAMP | When this row was computed |

> **Why the join is what makes Gold useful:** Without `clean_reference_data`, `category_id = 10` is just a number. Joining the category lookup turns it into `"Music"` — which is what dashboards actually need to show. The join is defensive (`left broadcast join`, fallback to `"Unknown"`) so a missing reference table doesn't kill the whole Gold build.

### 13.4 — Create the Gold Crawler

Now that the Silver→Gold job writes Parquet without touching the Glue Catalog, we need a crawler to pick up the three output tables and register them in `yt_pipeline_gold_dev`. The crawler runs once per Gold ETL run — it's triggered as the state immediately after the Silver→Gold job in the Step Functions pipeline ([Step 14](#step-14-step-functions--pipeline-orchestration)).

#### Console

1. Go to **Glue → Data Catalog → Crawlers → Create crawler**
2. Name: `yt-data-pipeline-gold-crawler-dev`
3. **Add a data source** (one per Gold table — the crawler handles all three in a single run):
   - Source: **S3**, Path: `s3://yt-data-pipeline-gold-<ACCOUNT_ID>-dev/youtube/trending_analytics/`
4. Click **Add another data source**:
   - Source: **S3**, Path: `s3://yt-data-pipeline-gold-<ACCOUNT_ID>-dev/youtube/channel_analytics/`
5. Click **Add another data source** once more:
   - Source: **S3**, Path: `s3://yt-data-pipeline-gold-<ACCOUNT_ID>-dev/youtube/category_analytics/`
6. IAM role: `yt-data-pipeline-glue-role-dev`
7. Target database: `yt_pipeline_gold_dev`
8. Schedule: **On demand** (the Step Functions state triggers it; no cron needed)
9. Click **Create crawler**

#### CLI

```bash
aws glue create-crawler \
  --name yt-data-pipeline-gold-crawler-dev \
  --role yt-data-pipeline-glue-role-dev \
  --database-name yt_pipeline_gold_dev \
  --targets '{
    "S3Targets": [
      {"Path": "s3://yt-data-pipeline-gold-<ACCOUNT_ID>-dev/youtube/trending_analytics/"},
      {"Path": "s3://yt-data-pipeline-gold-<ACCOUNT_ID>-dev/youtube/channel_analytics/"},
      {"Path": "s3://yt-data-pipeline-gold-<ACCOUNT_ID>-dev/youtube/category_analytics/"}
    ]
  }' \
  --region <YOUR_REGION>
```

**What the crawler produces** — three tables in `yt_pipeline_gold_dev`, each with `region` auto-detected as a partition key (see Step 13.3 for the full column schema):

| Table | Location | Partition |
|-------|----------|-----------|
| `trending_analytics` | `youtube/trending_analytics/region=xx/` | `region` |
| `channel_analytics` | `youtube/channel_analytics/region=xx/` | `region` |
| `category_analytics` | `youtube/category_analytics/region=xx/` | `region` |

> **Why three data sources in one crawler, not three crawlers?** All three tables share the same IAM role, target database, and schedule — and the Gold ETL job writes all three atomically, so they always need to be re-catalogued together. One crawler with three S3 targets means one Step Functions state, one IAM grant, and one billing unit per run. Separate crawlers would triple the coordination overhead for no gain.
>
> **Why "On demand" schedule?** This crawler is invoked by the Step Functions workflow after the Gold ETL job succeeds (see the state machine diagram in [Step 14.2](#142--create-the-state-machine) and the state-by-state breakdown in [Step 14.3](#143--what-each-state-does)). A cron schedule would fire the crawler on its own timeline, potentially while the ETL job is mid-write — creating a race condition where the crawler catalogues a half-finished table. On-demand means the crawler only runs when we explicitly call `glue:StartCrawler` from the orchestration layer.
>
> **No manual Run button press needed right now.** You've created the crawler, but don't click **Run** — leave it idle. [Step 14's Step Functions state machine](#step-14-step-functions--pipeline-orchestration) includes a `CatalogGoldTables` state that calls `glue:StartCrawler` automatically as part of each pipeline run, right after the Silver→Gold job succeeds. That's the only legitimate way to fire this crawler — running it manually now would just populate the catalog once with whatever's already in Gold S3 from a previous ETL run, and then when Step Functions tries to start it during the next full pipeline execution, it might hit `Glue.CrawlerRunningException` if the manual run is still in flight. The state machine also has a retry on that exception, so it'd recover, but it's cleaner to let orchestration own the trigger from the start. If you really want to validate the crawler works in isolation before building Step 14, you can click Run once — expect ~1–2 minutes for it to scan the three prefixes and register the tables in `yt_pipeline_gold_dev`. Athena queries against Gold ([Step 15](#step-15-athena--query-the-gold-layer)) will then succeed against those cataloged tables.

> Terraform: [15. Glue ETL Job (Silver → Gold)](#15-glue-etl-job-silver--gold) · [15b. Glue Crawler (Gold)](#15b-glue-crawler-gold)

&nbsp;

## Step 14: Step Functions — Pipeline Orchestration

Step Functions is AWS's workflow orchestrator — the thing that chains every component built in Steps 7–13 (YouTube API Lambda, JSON-to-Parquet Lambda, Bronze→Silver Glue job, DQ Gate Lambda, Silver→Gold Glue job, Gold crawler) into a single retriable, auditable pipeline run.

> **Why a Standard workflow (not Express):** Step Functions has two workflow types, chosen permanently at state-machine creation time. **Express** is optimized for high-frequency event processing (IoT, API orchestration) — it's cheap at scale but has a hard **5-minute execution cap** and does **not support** the `.sync` service integration this pipeline relies on for Glue jobs. **Standard** is built for long-running, auditable business processes; it supports every integration pattern and runs up to 1 year per execution.
>
> For this pipeline, Standard isn't just a cost preference — it's the only option that works. The two Glue `.sync` states (`RunBronzeToSilverGlueJob`, `RunSilverToGoldGlueJob`) rely on Step Functions blocking until the Glue job finishes. Express can't do that. And the end-to-end run takes 4–8 minutes on the Kaggle dataset, already over Express's 5-minute ceiling on a healthy run.
>
> **Cost context:** Standard bills at $0.025 per 1,000 state transitions. This pipeline has ~15 transitions per run. Running hourly for a month comes out to ~$0.27/month — dominated by Glue compute (1000× more), not by the orchestrator. The "Standard is 25× more expensive than Express" comparison you'll see online is literally true and functionally irrelevant at this scale.
>
> **When Express would apply:** If this pipeline had no Glue jobs (pure Lambda chains), stayed under 5 minutes end-to-end, and ran at high frequency (e.g., per-event from an EventBridge stream), Express would be the correct choice. That's not this pipeline.

### 14.1 — Prerequisite: Create the Step Functions Role

Execution role for the Step Functions state machine. Needs permissions to invoke Lambda functions, start Glue jobs, pass the Glue role, and publish to SNS.

#### 14.1.1 — Create the Role

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **AWS service**
3. Use case: **Step Functions**
4. Click **Next**
5. Do **not** attach any managed policies — the inline policy below provides all needed access
6. Click **Next**
7. Role name: `yt-data-pipeline-step-function-role-dev`
8. Click **Create role**

#### 14.1.2 — Add the Inline Policy

1. Go to **IAM → Roles → `yt-data-pipeline-step-function-role-dev`**
2. Click **Add permissions → Create inline policy**
3. Switch to the **JSON** editor
4. Paste the JSON below — replace `<ACCOUNT_ID>` with your AWS account ID (found top-right in the console)
5. Policy name: `sfn-pipeline-access`
6. Click **Create policy**

**Inline policy** (`sfn-pipeline-access`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeLambdaFunctions",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:*:*:function:yt-data-pipeline-*"
    },
    {
      "Sid": "RunGlueJobs",
      "Effect": "Allow",
      "Action": [
        "glue:StartJobRun",
        "glue:GetJobRun",
        "glue:GetJobRuns",
        "glue:BatchStopJobRun"
      ],
      "Resource": "arn:aws:glue:*:*:job/yt-data-pipeline-*"
    },
    {
      "Sid": "RunGlueCrawlers",
      "Effect": "Allow",
      "Action": [
        "glue:StartCrawler",
        "glue:GetCrawler"
      ],
      "Resource": "arn:aws:glue:*:*:crawler/yt-data-pipeline-*"
    },
    {
      "Sid": "PassGlueRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/yt-data-pipeline-glue-role-dev",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "glue.amazonaws.com"
        }
      }
    },
    {
      "Sid": "PublishAlerts",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:*:*:yt-data-pipeline-alerts-dev"
    }
  ]
}
```

> **⚠️ Replace `<ACCOUNT_ID>`** with your 12-digit AWS account ID in the `iam:PassRole` statement. This permission is required because Step Functions must pass the Glue execution role when starting a Glue job.

Or via CLI:

```bash
# 1. Create the trust policy file
cat > trust-policy-sfn.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "states.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# 2. Create the role
aws iam create-role \
  --role-name yt-data-pipeline-step-function-role-dev \
  --assume-role-policy-document file://trust-policy-sfn.json

# 3. Add the inline policy (save the JSON above as sfn-pipeline-access.json, replace <ACCOUNT_ID>)
aws iam put-role-policy \
  --role-name yt-data-pipeline-step-function-role-dev \
  --policy-name sfn-pipeline-access \
  --policy-document file://sfn-pipeline-access.json
```

> Terraform: [5. IAM — Step Functions Role](#5-iam--step-functions-role)

### 14.2 — Create the State Machine

#### Console

1. Go to **Step Functions** (use the AWS Console search bar)
2. On the **Create your state machine** landing screen, click **Create your own**
3. On the **Create state machine** panel:
   - **State machine name**: `yt-data-pipeline-orchestrator-dev`
   - **Type**: **Standard** (see [Step 14 intro](#step-14-step-functions--pipeline-orchestration) for why Express won't work)
   - Click **Continue**

4. You're now in the visual editor. Top-middle tab switcher shows **Design** (default) / **Code** / **Config**. Click **Code**.

5. **Select all and replace** the empty-scaffold JSON with the full contents of [`docs/resources/step_functions_definition.json`](docs/resources/step_functions_definition.json) — and substitute both `<REGION>` (your AWS region, e.g. `eu-north-1`) and `<ACCOUNT_ID>` (your 12-digit AWS account ID) everywhere they appear. Switch back to **Design** to verify the graph renders all the states (`IngestFromYouTubeAPI` → `WaitForS3Consistency` → `ProcessInParallel` → `RunDataQualityChecks` → etc.). If the Design canvas looks empty, **zoom out and pan** — the default viewport often places a graph this size off-screen (typically far to the right).

6. Click the **Config** tab:
   - **Execution role**: **Choose an existing role** → `yt-data-pipeline-step-function-role-dev` (created in [Step 14.1](#141--prerequisite-create-the-step-functions-role))
   - Leave everything else at its default

7. Click **Create** in the top-right corner.

Once created, the state machine's **Definition** tab renders the full graph. Exported below for reference — this is what the orchestrator looks like end-to-end (ingest → parallel Silver transforms → DQ gate → Silver→Gold ETL → Gold catalog refresh → success/failure notifications):

![Step Functions state machine — yt-data-pipeline-orchestrator-dev](docs/diagrams/stepfunctions_graph.svg)

> To regenerate this diagram after any state-machine edit: on the state machine's detail page → **Definition** tab → graph-pane toolbar → **Export** → save as PNG or SVG → replace `docs/diagrams/stepfunctions_graph.{png,svg}`.

#### CLI

```bash
# Save the JSON from docs/resources/step_functions_definition.json locally,
# replacing <REGION> and <ACCOUNT_ID> with your values first
aws stepfunctions create-state-machine \
  --name yt-data-pipeline-orchestrator-dev \
  --definition file://step_functions_definition.json \
  --role-arn arn:aws:iam::<ACCOUNT_ID>:role/yt-data-pipeline-step-function-role-dev \
  --type STANDARD \
  --region <YOUR_REGION>
```

### 14.3 — What Each State Does

| State | Type | Resource | Behavior |
|-------|------|----------|----------|
| `IngestFromYouTubeAPI` | Task | Lambda (sync invoke) | Passes `execution_id` in payload. Retries on Lambda service errors (3×, 30s base, 2× backoff). Catches all → `NotifyIngestionFailure` |
| `WaitForS3Consistency` | Wait | — | 10s buffer for S3 eventual consistency before the catalog is read |
| `ProcessInParallel` | Parallel | — | Runs reference-data Lambda AND Bronze-to-Silver Glue job concurrently. Catches all → `NotifyTransformFailure` |
| `TransformReferenceData` (branch) | Task | Lambda (sync invoke) | JSON-to-Parquet Lambda processing the reference files. Retries 2×. |
| `RunBronzeToSilverGlueJob` (branch) | Task | Glue `startJobRun.sync` | Blocks until the Glue job finishes. Passes all job parameters. Retries 2× with 60s base. |
| `RunDataQualityChecks` | Task | Lambda (sync invoke) | Runs the DQ Lambda over `clean_statistics` + `clean_reference_data`. Output: `quality_passed` boolean. |
| `EvaluateDataQuality` | Choice | — | Gate: `quality_passed=true` → proceed to Gold; otherwise → `NotifyDQFailure` (stops the run) |
| `RunSilverToGoldGlueJob` | Task | Glue `startJobRun.sync` | Runs `yt-data-pipeline-silver-to-gold-dev`. Writes Parquet to Gold S3; does **not** touch the Glue Catalog (see Step 13.2 for why). Catches all → `NotifyGoldFailure` |
| `CatalogGoldTables` | Task | `aws-sdk:glue:startCrawler` | Starts the Gold crawler ([Step 13.4](#134--create-the-gold-crawler)) asynchronously. Retries on `Glue.CrawlerRunningException` (another run already in progress). Catches all → `NotifyCatalogFailure` |
| `WaitForCrawlerToFinish` | Wait | — | 30s poll interval before checking crawler state again |
| `CheckCrawlerState` | Task | `aws-sdk:glue:getCrawler` | Reads the crawler's current state to detect completion |
| `IsCrawlerDone` | Choice | — | `READY` → succeed. `RUNNING`/`STOPPING` → loop back to `WaitForCrawlerToFinish`. Anything else → `NotifyCatalogFailure` |
| `NotifySuccess` | Task | SNS publish | Formats `"Pipeline run {execution_id} completed."` and publishes to the alerts topic |
| `NotifyIngestionFailure` / `NotifyTransformFailure` / `NotifyDQFailure` / `NotifyGoldFailure` / `NotifyCatalogFailure` | Task | SNS publish | Terminal failure branches — each publishes a targeted subject + JSON-stringified error payload. The catalog-failure variant is distinct because Gold Parquet *has* been written successfully at that point; only the catalog refresh failed |

> **Why `startJobRun.sync` (Glue jobs) but plain `startCrawler` (crawler):** The `.sync` integration pattern is only available for Glue *jobs*, not crawlers — AWS hasn't implemented `.sync` semantics for `glue:StartCrawler`. So we emulate it ourselves with the `startCrawler` → `Wait` → `getCrawler` → `Choice` loop. This adds three states but it's the idiomatic workaround; without it, the state machine would advance to `NotifySuccess` while the crawler is still running, potentially sending the "done" notification before the catalog has the fresh schema.
>
> **Why both retry AND catch:** Retry handles *transient* failures (Lambda throttling, Glue cold starts, `Glue.CrawlerRunningException` if a prior run is still finishing) — the same step re-runs automatically. Catch handles *terminal* failures after retries are exhausted — routes execution to a Notify state instead of failing the whole run silently. Every task state has at least one of each.
>
> **Why a separate `NotifyCatalogFailure`:** Unlike the other failure branches, a catalog failure means the data is fine — Athena queries against Gold will just see stale schema until someone re-runs the crawler manually. Differentiating this failure mode in the SNS subject line makes on-call triage faster (most catalog failures are safe to ignore until the next scheduled run).

### 14.4 — Trigger the Pipeline

#### Console

1. Go to **Step Functions → State machines → `yt-data-pipeline-orchestrator-dev`**
2. Click **Start execution**
3. Use the default `{}` input and click **Start execution**
4. Watch the visual execution graph — each state lights up as it runs; clicking a state shows its input/output JSON

#### CLI

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:<YOUR_REGION>:<ACCOUNT_ID>:stateMachine:yt-data-pipeline-orchestrator-dev \
  --input '{}' \
  --region <YOUR_REGION>
```

### 14.5 — Schedule

Wires the state machine to an **EventBridge Scheduler schedule** so it fires at a fixed time every day (02:00 UTC in this config). EventBridge is its own AWS service — it doesn't inherit any permission from you or the state machine, so it needs its own IAM role with permission to start your state machine.

#### 14.5.1 — Prerequisite: Create the EventBridge Scheduler Invoke Role

Execution role EventBridge Scheduler assumes when firing the scheduled rule. Needs a single permission: start executions on the orchestrator state machine.

##### Console

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **Custom trust policy** (not "AWS service" — the EventBridge use case under "AWS service" creates a service-linked role with a fixed, non-editable name, which we don't want)
3. Paste the trust policy JSON below into the editor:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": { "Service": "scheduler.amazonaws.com" },
         "Action": "sts:AssumeRole"
       }
     ]
   }
   ```
4. Click **Next**
5. Do **not** attach any managed policies — the inline policy below provides all needed access
6. Click **Next**
7. Role name: `yt-data-pipeline-scheduler-role-dev`
8. Click **Create role**

Then add the inline policy:

1. Go to **IAM → Roles → `yt-data-pipeline-scheduler-role-dev`**
2. Click **Add permissions → Create inline policy**
3. Switch to the **JSON** editor
4. Paste the JSON below — replace `<ACCOUNT_ID>` with your AWS account ID and `<YOUR_REGION>` with your region (e.g. `eu-north-1`)
5. Policy name: `scheduler-invoke-stepfn-access`
6. Click **Create policy**

**Inline policy** (`scheduler-invoke-stepfn-access`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StartPipelineExecution",
      "Effect": "Allow",
      "Action": "states:StartExecution",
      "Resource": "arn:aws:states:<YOUR_REGION>:<ACCOUNT_ID>:stateMachine:yt-data-pipeline-orchestrator-dev"
    }
  ]
}
```

##### CLI

```bash
# 1. Create the trust policy file
cat > trust-policy-scheduler.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "scheduler.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# 2. Create the role with the custom trust policy
aws iam create-role \
  --role-name yt-data-pipeline-scheduler-role-dev \
  --assume-role-policy-document file://trust-policy-scheduler.json

# 3. Add the inline policy (save the JSON above as scheduler-invoke-stepfn-access.json,
#    replacing <ACCOUNT_ID> and <YOUR_REGION> first)
aws iam put-role-policy \
  --role-name yt-data-pipeline-scheduler-role-dev \
  --policy-name scheduler-invoke-stepfn-access \
  --policy-document file://scheduler-invoke-stepfn-access.json
```

#### 14.5.2 — Create the Schedule

##### Console

1. Go to **Amazon EventBridge → Scheduler → Schedules → Create schedule** (left-nav section **Scheduler**, NOT **Rules**)
2. **Step 1 — Specify schedule detail**:
   - **Schedule name**: `yt-data-pipeline-daily-dev`
   - **Description**: `Run YT data pipeline daily at 02:00 UTC`
   - **Schedule group**: `default`
   - **Occurrence**: **Recurring schedule**
   - **Schedule type**: **Cron-based schedule** (NOT "Rate-based schedule" — cron is the right tool for "fire at a fixed time of day"; rate-based only expresses intervals like "every N hours")
   - **Cron expression**: `0 2 * * ? *`
     - *Field-by-field*: minute=`0`, hour=`2`, day-of-month=`*` (every day), month=`*` (every month), day-of-week=`?` (not specified — must be `?` when day-of-month is `*`), year=`*` (every year)
     - *Note*: EventBridge Scheduler cron has **six fields** and requires exactly one of day-of-month / day-of-week to be `?`. Different from Linux cron (5 fields).
   - **Timezone**: `UTC` (dropdown — pick explicitly even though UTC is the default, so the schedule is unambiguous across DST transitions and team members in different regions)
   - **Flexible time window**: `Off`
   - Click **Next**
3. **Step 2 — Select target**:
   - **Target API**: **Templated targets** → **AWS Step Functions StartExecution**
   - **State machine**: `yt-data-pipeline-orchestrator-dev`
   - **Input**: `{}` (the state machine doesn't read any input; an empty object is fine)
   - Click **Next**
4. **Step 3 — Settings - optional**:
   - **Schedule state — Enable**: toggle **ON**
   - **Action after schedule completion**: `NONE`
   - **Retry policy and dead-letter queue (DLQ)**:
     - **Retry**: leave OFF (default)
     - **Dead-letter queue (DLQ)**: **None**
   - **Encryption**: leave at default (do NOT toggle "Customize encryption settings")
   - **Permissions**: select **Use existing role** → dropdown: **`yt-data-pipeline-scheduler-role-dev`** (created in 14.5.1)
   - Click **Next**
5. **Step 4 — Review and create schedule**: click **Create schedule**

The schedule is **enabled on create**. First execution fires at the next rate interval.

##### CLI

```bash
# Create the schedule. Replace <YOUR_REGION> and <ACCOUNT_ID>.
aws scheduler create-schedule \
  --name yt-data-pipeline-daily-dev \
  --schedule-expression "cron(0 2 * * ? *)" \
  --schedule-expression-timezone "UTC" \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target '{
    "Arn": "arn:aws:states:<YOUR_REGION>:<ACCOUNT_ID>:stateMachine:yt-data-pipeline-orchestrator-dev",
    "RoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/yt-data-pipeline-scheduler-role-dev",
    "Input": "{}"
  }' \
  --state ENABLED \
  --description "Run YT data pipeline daily at 02:00 UTC" \
  --region <YOUR_REGION>
```

> **Schedule expression syntax** — EventBridge Scheduler accepts three forms:
> - `rate(<value> <unit>)` — where unit is `minutes | hours | days` (minimum 1 minute)
> - `cron(<minute> <hour> <day-of-month> <month> <day-of-week> <year>)` — six fields; exactly one of `day-of-month` or `day-of-week` must be `?`. Example: `cron(0 7 * * ? *)` = daily at 07:00 UTC.
> - `at(YYYY-MM-DDTHH:MM:SS)` — one-off schedule, single fire time.

#### 14.5.3 — Verify

Scheduler fires the schedule at the next cron match — for `cron(0 2 * * ? *)` that's the next 02:00 UTC. If you created the schedule at 15:30 UTC today, the first tick is tomorrow at 02:00 UTC (~10 hours). Unlike rate-based schedules, cron does NOT fire an extra tick on creation — the clock runs strictly by wall-clock match.

To verify sooner without waiting for 02:00, edit the cron expression to a time ~5 minutes in the future via **EventBridge → Scheduler → Schedules → yt-data-pipeline-daily-dev → Edit** (e.g. if it's 15:30 UTC now, set `cron(35 15 * * ? *)`), let the tick fire, then revert to `cron(0 2 * * ? *)`. **Do NOT use `rate(1 minute)` for testing** — Scheduler queues backlog ticks from rate-based schedules that fire before your next update lands, which can flood Step Functions with concurrent executions (the Bronze→Silver Glue job has `MaxConcurrentRuns=1`, so concurrent executions beyond 1 fail with `ConcurrentRunsExceededException`).

After a tick fires, check:

1. **Step Functions → yt-data-pipeline-orchestrator-dev → Executions** — a new execution appears with name auto-generated by Scheduler (e.g. a GUID like `8569f0eb-8718-4b15-87f9-2308e097c112`)
2. **EventBridge → Scheduler → Schedules → yt-data-pipeline-daily-dev** — shows `Last invocation` and `Next invocation` timestamps. If invocations aren't landing, Scheduler publishes `InvocationsFailedToBeSentToDeadLetterQueueCount` and related CloudWatch metrics under namespace `AWS/Scheduler` — check there for permission failures. Almost always the role from 14.5.1 missing `states:StartExecution`, or a trust-policy principal typo (must be `scheduler.amazonaws.com`, NOT `events.amazonaws.com`).

To change the cadence later: **EventBridge → Scheduler → Schedules → yt-data-pipeline-daily-dev → Edit** → update the cron expression → **Save**.

To disable without deleting (e.g. during maintenance):

```bash
aws scheduler update-schedule \
  --name yt-data-pipeline-daily-dev \
  --state DISABLED \
  --schedule-expression "cron(0 2 * * ? *)" \
  --schedule-expression-timezone "UTC" \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target '{
    "Arn": "arn:aws:states:<YOUR_REGION>:<ACCOUNT_ID>:stateMachine:yt-data-pipeline-orchestrator-dev",
    "RoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/yt-data-pipeline-scheduler-role-dev",
    "Input": "{}"
  }' \
  --region <YOUR_REGION>

# Re-enable by setting --state ENABLED in the same call.
```

> Terraform: [17. EventBridge Schedule (Pipeline Trigger)](#17-eventbridge-schedule-pipeline-trigger)

&nbsp;

## Step 15: Athena — Query the Gold Layer

### 15.1 — Configure Query Results

If you already created the `yt-pipeline-dev` workgroup in [Step 9.1](#91--configure-query-results), select it from the workgroup dropdown in the top-right of the Athena query editor and skip ahead. If you haven't, do that first — pinning all pipeline queries to a single workgroup keeps the result bucket, scan limits, and IAM scope consistent across Bronze, Silver-via-DQ-Gate, and Gold queries.

### 15.2 — Example Queries

Before running any query, set the Athena editor's **Database** dropdown to `yt_pipeline_gold_dev` (for Gold aggregates) or `yt_pipeline_silver_dev` (for per-video rows). The queries below fully-qualify the table names so they work regardless, but the dropdown also controls unqualified references and the execution plan's scope.

**Aggregate analytics (Gold layer) — one row per region × date or region × channel:**

```sql
-- Top 10 highest-view days in the US (aggregate, not per-video)
SELECT trending_date_parsed,
       total_videos,
       total_views,
       total_likes,
       max_views
FROM yt_pipeline_gold_dev.trending_analytics
WHERE region = 'us'
ORDER BY total_views DESC
LIMIT 10;

-- Top channels present across 3+ regions
SELECT channel_title,
       COUNT(DISTINCT region) AS regions,
       SUM(total_views)       AS total_views_global
FROM yt_pipeline_gold_dev.channel_analytics
GROUP BY channel_title
HAVING COUNT(DISTINCT region) >= 3
ORDER BY total_views_global DESC
LIMIT 20;

-- Category performance by region
SELECT category_name,
       region,
       SUM(total_views)  AS total_views,
       SUM(video_count)  AS video_count
FROM yt_pipeline_gold_dev.category_analytics
GROUP BY category_name, region
ORDER BY total_views DESC
LIMIT 50;

-- Average like ratio by region (Gold already computed avg_like_ratio per day)
SELECT region,
       AVG(avg_like_ratio) AS avg_like_ratio_across_days
FROM yt_pipeline_gold_dev.trending_analytics
GROUP BY region
ORDER BY avg_like_ratio_across_days DESC;
```

**Per-video detail (Silver layer) — one row per video × trending day:**

```sql
-- Top 10 most-viewed videos in the US (per-video, from Silver)
SELECT video_id,
       title,
       channel_title,
       views,
       likes,
       comment_count
FROM yt_pipeline_silver_dev.clean_statistics
WHERE region = 'us'
ORDER BY views DESC
LIMIT 10;
```

> **Why Gold queries don't have `title` / `video_id`:** Gold is deliberately aggregated — `trending_analytics` groups by `region × trending_date_parsed`, `channel_analytics` by `channel_title × region`, `category_analytics` by `category × region × date`. Individual videos are collapsed into `total_videos`, `total_views`, etc. If your dashboard needs per-video detail, query Silver instead (it's still Parquet-on-S3 via the same Athena workgroup — no extra cost).

> **Note:** Athena workgroups and query result locations are configured via the console — no Terraform block required.

&nbsp;

## Step 16: QuickSight — Build Dashboards

### 16.1 — Connect QuickSight to Athena

1. Go to **QuickSight → Manage QuickSight → Security & permissions**
2. Enable access to **Athena** and the **S3 Gold bucket**
3. Go to **Datasets → New dataset → Athena**
4. Data source name: `yt-analytics`
5. Database: `yt_pipeline_gold_dev`
6. Choose **Import to SPICE** for faster dashboards (or **Direct query** for real-time)

### 16.2 — Suggested Visualizations

| Chart Type | Metric | Dimension | Insight |
|------------|--------|-----------|---------|
| Bar chart | Total views | Category name | Which categories are most popular |
| Pie chart | Video count | Region | Distribution of trending videos by country |
| Line chart | Views over time | Trending date | How engagement changes over time |
| Heat map | Engagement ratio | Region x Category | Where and what content performs best |
| Horizontal bar | Total views | Channel title | Top performing channels (T-Series, SpaceX, etc.) |
| KPI cards | Total videos, avg views, avg likes | — | High-level metrics |

> **Note:** QuickSight datasets, data sources, and dashboards are configured via the console — no Terraform block required.

> **Cost note:** This pipeline is designed to fit within the **AWS Free Tier** for learning. Key allowances: S3 (5 GB storage, 20K GET, 2K PUT/month), Lambda (1M requests, 400K GB-seconds/month), Glue Data Catalog: first 1M objects stored free. Glue ETL: first 10 DPU-hours/month free for initial 3-month trial only, Athena ($5/TB scanned — Parquet + partitioning keeps scans small), Step Functions (4,000 state transitions/month), SNS (1M publishes, 1K email deliveries/month), QuickSight (30-day free trial for 1 author). Always stop or delete Glue crawlers, ETL jobs, and QuickSight datasets when not in use. The S3 lifecycle rule to Glacier after 90 days helps control Bronze storage costs.

&nbsp;

## Troubleshooting

Common issues you may hit during setup, grouped by component. Start with the group that matches the error you're seeing.

### Lambda Issues

#### `No module named 'awswrangler'`

1. Verify the AWS Data Wrangler Lambda Layer is attached to the function
2. Go to **Lambda → function** and scroll down past the Code source and Runtime settings panels until the **Layers** panel is visible (near the bottom of the function detail page). Click **Edit** → **Add a layer** → **AWS layers**
3. Search for `AWSSDKPandas-Python312` and add the latest version

#### Lambda timeout

1. Check the current timeout value: **Configuration → General configuration**
2. Increase to **60-120 seconds** (default 3 seconds is too short for API calls and data processing)
3. Re-test the function

#### Lambda memory error

1. Check the current memory allocation: **Configuration → General configuration**
2. Increase to **512 MB** or higher (pandas + awswrangler need more than 128 MB)

#### Lambda Access Denied to S3

1. Go to **IAM → Roles → `yt-data-pipeline-lambda-role-dev`**
2. Verify the inline policy has `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`
3. Confirm the `Resource` ARNs match the correct bucket names (including `/*` for object-level actions)

### Glue Issues

#### Crawler creates wrong schema / too many tables

If the Bronze crawler produces ~45 micro-tables (one per file) instead of the two expected tables (`raw_statistics` + `raw_statistics_reference_data`), you've hit the **table-per-file explosion**. This happens when the crawler scans a prefix containing **heterogeneous file formats or incompatible schemas** — it refuses to merge them and creates a separate table for each file instead.

**Most common cause:** running the crawler after the YouTube API Lambda ([Step 7](#step-7-lambda--youtube-api-ingestion)) has already written JSON files into `raw_statistics/`. The prefix now mixes Kaggle CSVs with Lambda JSONs, so the crawler can't produce a single unified table. See [Step 8's ordering warning](#step-8-glue-crawler--catalog-bronze-data) for why this happens.

**Fix** — replay Step 8 from a clean CSV-only state:

> **⚠️ Destructive commands ahead.** Steps 1 and 2 below move S3 objects and delete Glue Catalog tables. Both operations are **unrecoverable** (no undo, no AWS soft-delete, no dry-run). Before running anything:
> - Confirm which AWS account you're targeting: `aws sts get-caller-identity --query Account --output text` — the number must match the account you expect. `AWS_PROFILE` and `AWS_DEFAULT_REGION` env vars silently redirect to other accounts/regions; a forgotten export from an earlier session is the most common way these commands get pointed at the wrong place.
> - Replace `<region>` in `$BUCKET` with your actual region, and replace `YYYY-MM-DD` with the date-partition the Lambda actually wrote (list it first: `aws s3 ls s3://<your-bucket>/youtube/raw_statistics/ --recursive | grep date=`). If you leave `YYYY-MM-DD` unsubstituted, the `mv` silently matches zero objects, and the crawler still explodes on the next run.
> - Pause any Step Functions schedule or EventBridge rule that might invoke the YouTube API Lambda while you're running the move — concurrent writes to `raw_statistics/` during `aws s3 mv` will leave files behind in the source prefix.

1. **Move the Lambda's JSON output to a parking prefix** so the crawler only sees Kaggle files:
   ```bash
   BUCKET=yt-data-pipeline-bronze-<ACCOUNT_ID>-dev
   for region in ca de fr gb in jp kr mx ru us; do
     aws s3 mv "s3://$BUCKET/youtube/raw_statistics/region=$region/date=YYYY-MM-DD/" \
               "s3://$BUCKET/_parked_api_lambda/raw_statistics/region=$region/date=YYYY-MM-DD/" \
               --recursive
     aws s3 mv "s3://$BUCKET/youtube/raw_statistics_reference_data/region=$region/date=YYYY-MM-DD/" \
               "s3://$BUCKET/_parked_api_lambda/raw_statistics_reference_data/region=$region/date=YYYY-MM-DD/" \
               --recursive
   done
   ```
2. **Delete all tables** from `yt_pipeline_bronze_dev` (keep the database):
   ```bash
   aws glue get-tables --database-name yt_pipeline_bronze_dev --query 'TableList[].Name' --output text | \
     tr '\t' '\n' | xargs -n 1 -I {} aws glue delete-table --database-name yt_pipeline_bronze_dev --name {}
   ```
3. **Re-run the existing crawler** — it will now produce exactly two tables, as documented in Step 8.
4. **Move the Lambda JSONs back** to `youtube/raw_statistics/` and `youtube/raw_statistics_reference_data/` (reverse the `aws s3 mv` from step 1). The Silver ETL reads them directly from S3 without needing another crawl.
5. **Do not re-run the Bronze crawler** after this point.

**Other causes** (less common for this pipeline):

1. Verify each crawler path contains only one data format
2. Use separate crawlers for CSVs and JSONs if you must keep them co-located
3. Schema drift across files — check the crawler's Include/Exclude patterns and `TableLevel` grouping setting

#### Partition column not detected

1. Verify folder structure follows Hive-style `key=value/` pattern
2. Re-upload data using partitioned paths (e.g., `region=us/`)
3. Delete the existing table and re-run the crawler

#### Glue job produces empty output

1. Check the predicate pushdown filter — verify region values match what the crawler detected
2. Confirm the database and table names in the script match the Glue Data Catalog
3. Preview the source table in the Glue Console to verify data exists

#### Glue job missing S3 access

1. Go to **IAM → Roles → `yt-data-pipeline-glue-role-dev`**
2. Update the inline policy to include all five bucket ARNs (Bronze, Silver, Gold, Scripts, Athena-results)
3. Re-run the Glue job

### Step Functions Issues

#### State machine fails at Lambda invoke

1. Verify the Step Functions role has `lambda:InvokeFunction` permission
2. Confirm the Lambda function ARNs in the state machine definition are correct
3. Check the Lambda function exists in the same region as the state machine

#### Quality check fails unexpectedly

1. Verify the Silver data has finished writing before the quality check runs
2. Increase the Wait state duration if needed
3. Confirm the quality check Lambda is pointed at the correct Silver database/table

### Athena Issues

#### "HIVE_METASTORE_ERROR" or table not found

1. Run the Glue Crawler to ensure the table is registered in the Data Catalog
2. Refresh the Athena table list
3. Verify you have the correct database selected in the Athena query editor

#### Query scans too much data

1. Add `WHERE region = '...'` to queries to enable partition pruning
2. Use Parquet-format tables (Silver/Gold) instead of raw CSV tables (Bronze) for analytical queries
3. Verify the table is partitioned by checking **Glue → Tables → Partitions**

### Console Teardown (Learning Account)

When you're done with the learning walkthrough and want to remove everything from your personal account, be aware that **deleting a Lambda function or Glue job does NOT delete its CloudWatch log group**. Log groups are managed by CloudWatch, not by the resource that wrote to them. They outlive the producer and keep costing you the monthly storage fee (`$0.03/GB/month`) until you manually remove them.

Because this guide builds everything via the console rather than Terraform, log groups are auto-created by AWS with **`Never Expire`** retention — meaning every log event you wrote during the walkthrough stays there forever unless you clean up.

**What to delete after you've removed the rest of the pipeline:**

1. Go to **CloudWatch → Log groups**
2. In the filter box, paste `/aws/lambda/yt-data-pipeline` and delete each matching log group:
   - `/aws/lambda/yt-data-pipeline-json-to-parquet-dev`
   - `/aws/lambda/yt-data-pipeline-youtube-ingestion-dev`
   - `/aws/lambda/yt-data-pipeline-data-quality-dev`
3. Clear the filter and search `/aws-glue/` — delete:
   - `/aws-glue/jobs/output`
   - `/aws-glue/jobs/error`
   - `/aws-glue/crawlers`
   - Any `/aws-glue/python-jobs/*` that appear

Or via CLI (destructive; double-check the account before running):

```bash
for lg in \
  "/aws/lambda/yt-data-pipeline-json-to-parquet-dev" \
  "/aws/lambda/yt-data-pipeline-youtube-ingestion-dev" \
  "/aws/lambda/yt-data-pipeline-data-quality-dev" \
  "/aws-glue/jobs/output" \
  "/aws-glue/jobs/error" \
  "/aws-glue/crawlers"; do
  aws logs delete-log-group --log-group-name "$lg" --region <YOUR_REGION> 2>/dev/null
done
```

> **Why the Terraform path doesn't have this problem:** The Terraform reference declares each log group explicitly with `retention_in_days = 14` and wires the Lambda to depend on it. `terraform destroy` removes the log groups along with the Lambdas — no orphans, no manual cleanup. See [Section 9](#9-lambda--json-to-parquet) and [Section 7c](#7c-glue-log-groups-account-scoped) in the Terraform Reference for why log groups must be declared separately even though Lambda would happily auto-create them.
>
> **⚠ Account-wide Glue log groups:** `/aws-glue/jobs/output`, `/aws-glue/jobs/error`, and `/aws-glue/crawlers` are **shared across every Glue workload in your AWS account**. If this is your only pipeline, delete them. If you have other Glue work running in the same account, leave them alone — the storage cost is minor and the shared groups will keep collecting logs from your other jobs.

&nbsp;

## Terraform Reference

This section provides a complete, copy-pasteable Terraform configuration that reproduces every AWS resource built through the console guide above. You can use it in two ways: **(a)** hand the entire file to your DevOps team so they can provision the pipeline in a repeatable, auditable manner, or **(b)** run it yourself in a sandbox account where you have admin rights, then point your team at the state file for production promotion.

**DevOps handoff workflow:** Because the corporate AWS account restricts direct IAM and infrastructure creation, the recommended workflow is to commit these Terraform files to your team's infra repository, open a merge request tagged `pipeline-infra`, and let DevOps review, plan, and apply. IAM-related blocks (the Lambda execution role, the Glue service role, the Step Functions role) are flagged below so reviewers know which resources require elevated privileges. All other resources (S3 buckets, Lambda functions, Glue crawlers, SNS topics) can typically be applied by a developer role with scoped permissions.

> **Order matters:** Apply these resources in the order listed. Later resources reference earlier ones (Lambda functions reference the IAM role; Glue crawlers reference the database; the S3 event notification references the Lambda function). Terraform handles the dependency graph automatically, but if you apply blocks selectively, follow the ordering below.

> **Scope:** Terraform covers only pipeline-level AWS resources — S3 buckets, Lambda functions, Glue jobs, Step Functions, SNS, and the **service roles** these resources need at runtime. Organization-level infrastructure (AWS SSO / IAM Identity Center, SCPs, developer assumed roles, CI/CD deployer roles) is managed separately — typically in a dedicated platform/identity Terraform repo owned by your DevOps or security team. QuickSight dashboards and Athena workgroups are configured via the console — not Terraform.

Before any `resource` blocks, your `.tf` file needs the standard provider preamble plus the set of input variables the rest of the configuration depends on. Keep `variables.tf` in the same directory (Terraform auto-loads any `*.tf` file in the directory):

### Provider

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Every taggable resource created by this provider inherits these tags.
  # You can still add resource-specific tags via a `tags = { ... }` block on
  # any individual resource — they merge with default_tags (resource-level
  # wins on key conflicts). See Section 18 below for how to activate these as
  # cost-allocation tags in the Billing console.
  default_tags {
    tags = {
      Project   = "yt-data-pipeline"
      Env       = var.env
      ManagedBy = "Terraform"
    }
  }
}

# Handy data sources referenced by later resources (layer ARN region, account ID for confused-deputy guards).
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
```

### Variables

```hcl
variable "aws_region" {
  description = "AWS region the pipeline is deployed into. Must be a region where AWSSDKPandas-Python312 is published."
  type        = string
  default     = "ap-south-1"
}

variable "env" {
  description = "Environment tag applied to every resource via default_tags (dev | staging | prod). Drives Cost Explorer breakdowns and any IAM conditions scoped on aws:ResourceTag/Env."
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be one of: dev, staging, prod."
  }
}

variable "notification_email" {
  description = "Email address subscribed to the SNS alert topic."
  type        = string
}

variable "youtube_api_key" {
  description = "Google API key for the YouTube Data API v3. Stored in AWS Secrets Manager, not in Lambda env vars."
  type        = string
  sensitive   = true
}

variable "pandas_layer_version" {
  description = "Version number of the public AWSSDKPandas-Python312 layer. Look up the current version with: aws lambda list-layer-versions --layer-name AWSSDKPandas-Python312 --region <region>"
  type        = number
  default     = 27
}
```

&nbsp;

### 1. S3 Buckets

Creates the five S3 buckets: four for the medallion architecture + scripts storage, plus a dedicated bucket for Athena query results. Corresponds to **Step 1** in the console guide.

```hcl
resource "aws_s3_bucket" "bronze" {
  bucket = "yt-data-pipeline-bronze-${data.aws_caller_identity.current.account_id}-dev"
}

resource "aws_s3_bucket" "silver" {
  bucket = "yt-data-pipeline-silver-${data.aws_caller_identity.current.account_id}-dev"
}

resource "aws_s3_bucket" "gold" {
  bucket = "yt-data-pipeline-gold-${data.aws_caller_identity.current.account_id}-dev"
}

resource "aws_s3_bucket" "scripts" {
  bucket = "yt-data-pipeline-scripts-${data.aws_caller_identity.current.account_id}-dev"
}

resource "aws_s3_bucket" "athena_results" {
  bucket = "yt-data-pipeline-athena-results-${data.aws_caller_identity.current.account_id}-dev"
}
```

&nbsp;

### 2. S3 Lifecycle Rule (Bronze Bucket)

Archives raw data to Glacier after 90 days to reduce storage costs. Corresponds to **Step 1** in the console guide.

```hcl
resource "aws_s3_bucket_lifecycle_configuration" "bronze_archive" {
  bucket = aws_s3_bucket.bronze.id

  rule {
    id     = "archive-old-raw-data"
    status = "Enabled"

    filter {
      prefix = "youtube/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}
```

&nbsp;

### 3. IAM — Lambda Execution Role

Creates the execution role for all three Lambda functions (JSON-to-Parquet, YouTube API ingestion, data quality gate) with the full inline policy in a single resource. **Because this creates an IAM role, it must be provisioned by your DevOps team per corporate policy.** Corresponds to **Step 2.2** in the console guide.

```hcl
resource "aws_iam_role" "lambda_execution_role" {
  name = "yt-data-pipeline-lambda-role-dev"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_pipeline_access" {
  name = "yt-pipeline-lambda-access"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.bronze.arn,
          "${aws_s3_bucket.bronze.arn}/*",
          aws_s3_bucket.silver.arn,
          "${aws_s3_bucket.silver.arn}/*",
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*"
        ]
      },
      {
        Sid    = "GlueCatalogAccess"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase", "glue:GetDatabases",
          "glue:GetTable", "glue:GetTables",
          "glue:CreateTable", "glue:UpdateTable",
          "glue:GetPartitions", "glue:GetPartition",
          "glue:BatchCreatePartition", "glue:BatchGetPartition"
        ]
        Resource = [
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog",
          aws_glue_catalog_database.bronze.arn,
          aws_glue_catalog_database.silver.arn,
          aws_glue_catalog_database.gold.arn,
          "${aws_glue_catalog_database.bronze.arn}/*",
          "${aws_glue_catalog_database.silver.arn}/*",
          "${aws_glue_catalog_database.gold.arn}/*",
          # Table-level ARNs (needed because glue:GetTable / CreateTable target tables, not databases).
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/yt_pipeline_bronze_dev/*",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/yt_pipeline_silver_dev/*",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/yt_pipeline_gold_dev/*"
        ]
      },
      {
        Sid    = "AthenaQueryAccess"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:GetWorkGroup",
          "athena:GetDataCatalog",
          "athena:ListDataCatalogs",
          "athena:GetDatabase",
          "athena:GetTableMetadata"
        ]
        Resource = [
          aws_athena_workgroup.yt_pipeline.arn,
          "arn:aws:athena:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:datacatalog/AwsDataCatalog"
        ]
      },
      {
        Sid      = "SNSPublish"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.pipeline_alerts.arn
      }
    ]
  })
}
```

&nbsp;

### 4. IAM — Glue Service Role

Creates the execution role for Glue crawlers and ETL jobs. Grants S3 access across all five buckets (Bronze, Silver, Gold, Scripts, Athena-results) and Glue Catalog management. **Because this creates an IAM role, it must be provisioned by your DevOps team per corporate policy.** Corresponds to **Step 3** in the console guide.

```hcl
resource "aws_iam_role" "glue_service_role" {
  name = "yt-data-pipeline-glue-role-dev"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_access" {
  name = "yt-pipeline-glue-access"
  role = aws_iam_role.glue_service_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read-only on immutable buckets: Bronze (raw data) and Scripts (ETL code).
        Sid    = "ReadOnlyOnImmutableBuckets"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.bronze.arn,  "${aws_s3_bucket.bronze.arn}/*",
          aws_s3_bucket.scripts.arn, "${aws_s3_bucket.scripts.arn}/*"
        ]
      },
      {
        # Read/write on buckets Glue legitimately mutates.
        Sid    = "ReadWriteOnMutableBuckets"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
        Resource = [
          aws_s3_bucket.silver.arn,         "${aws_s3_bucket.silver.arn}/*",
          aws_s3_bucket.gold.arn,           "${aws_s3_bucket.gold.arn}/*",
          aws_s3_bucket.athena_results.arn, "${aws_s3_bucket.athena_results.arn}/*"
        ]
      }
    ]
  })
}
```

&nbsp;

### 5. IAM — Step Functions Role

Creates the execution role for the Step Functions state machine. Grants permissions to invoke Lambda, start Glue jobs, and publish to SNS. **Because this creates an IAM role, it must be provisioned by your DevOps team per corporate policy.** Corresponds to **Step 14** in the console guide.

```hcl
resource "aws_iam_role" "step_functions_role" {
  name = "yt-data-pipeline-step-function-role-dev"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "step_functions_access" {
  name = "yt-data-pipeline-sfn-access"
  role = aws_iam_role.step_functions_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeLambdaFunctions"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:aws:lambda:*:*:function:yt-data-pipeline-*"
      },
      {
        Sid      = "RunGlueJobs"
        Effect   = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
        Resource = "arn:aws:glue:*:*:job/yt-data-pipeline-*"
      },
      {
        # Needed by the CatalogGoldTables / CheckCrawlerState states added to the
        # Silver→Gold pipeline — StartCrawler kicks off the refresh, GetCrawler
        # polls for READY so the state machine can complete cleanly.
        Sid      = "RunGlueCrawlers"
        Effect   = "Allow"
        Action   = ["glue:StartCrawler", "glue:GetCrawler"]
        Resource = "arn:aws:glue:*:*:crawler/yt-data-pipeline-*"
      },
      {
        Sid      = "PassGlueRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.glue_service_role.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "glue.amazonaws.com"
          }
        }
      },
      {
        Sid      = "PublishAlerts"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.pipeline_alerts.arn
      }
    ]
  })
}
```

&nbsp;

### 6. SNS Topic + Subscription

Creates the alert topic for pipeline notifications and subscribes an email. Corresponds to **Step 4** in the console guide.

```hcl
resource "aws_sns_topic" "pipeline_alerts" {
  name = "yt-data-pipeline-alerts-dev"
}

resource "aws_sns_topic_subscription" "email_alerts" {
  topic_arn = aws_sns_topic.pipeline_alerts.arn
  protocol  = "email"
  endpoint  = var.notification_email
}
```

&nbsp;

### 7. Glue Databases

Creates the three Glue Data Catalog databases for the medallion layers. Corresponds to **Step 5** in the console guide.

```hcl
resource "aws_glue_catalog_database" "bronze" {
  name        = "yt_pipeline_bronze_dev"
  description = "Raw data"
}

resource "aws_glue_catalog_database" "silver" {
  name        = "yt_pipeline_silver_dev"
  description = "Cleansed data"
}

resource "aws_glue_catalog_database" "gold" {
  name        = "yt_pipeline_gold_dev"
  description = "Analytics / aggregation"
}
```

&nbsp;

### 7b. Athena Workgroup

Creates a dedicated Athena workgroup that scopes IAM permissions for the DQ Gate Lambda and pins all pipeline queries to a single result bucket. Corresponds to **Step 9.1** in the console guide.

```hcl
resource "aws_athena_workgroup" "yt_pipeline" {
  name        = "yt-pipeline-dev"
  description = "YouTube pipeline workgroup (Bronze exploration, DQ checks, Gold queries)"

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/"
    }
  }
}
```

&nbsp;

### 7c. Glue Log Groups (Account-Scoped)

Glue jobs and crawlers don't create per-resource log groups — they share three **account-level** CloudWatch Logs groups: `/aws-glue/jobs/output`, `/aws-glue/jobs/error`, and `/aws-glue/crawlers`. Declaring these with explicit retention stops every Glue run in the account from writing into "Never Expire" groups. **Scope caveat:** because these log groups are account-scoped, setting retention here affects *every* Glue job and crawler in this AWS account — not just the ones in this pipeline. That's almost always what you want, but worth knowing if the account is shared with other Glue workloads.

```hcl
# Shared log group for ALL Glue ETL jobs in this account (stdout).
resource "aws_cloudwatch_log_group" "glue_jobs_output" {
  name              = "/aws-glue/jobs/output"
  retention_in_days = 14
}

# Shared log group for ALL Glue ETL jobs in this account (stderr / driver errors).
resource "aws_cloudwatch_log_group" "glue_jobs_error" {
  name              = "/aws-glue/jobs/error"
  retention_in_days = 14
}

# Shared log group for ALL Glue crawlers in this account.
resource "aws_cloudwatch_log_group" "glue_crawlers" {
  name              = "/aws-glue/crawlers"
  retention_in_days = 14
}
```

> **Why these names are fixed:** Glue writes to these exact log-group names and does not allow you to customize them per-job. Trying to set a different name via the job's `default_arguments` (e.g., `--continuous-log-logGroup`) diverges from the built-in integration — CloudWatch metrics and the Glue console both look at the hard-coded names. Keep the names as shown.
>
> **First-apply behavior:** If any Glue job or crawler has *ever* run in this account before Terraform is applied, these log groups already exist with Never-Expire retention. Terraform will adopt them on apply and set `retention_in_days = 14` going forward — historical log data keeps its original retention until it exits the 14-day window (or was set to Never Expire, in which case it stays until manually purged).

&nbsp;

### 8. Glue Crawler (Bronze)

Creates the Glue Crawler that scans the Bronze S3 bucket and registers tables in the Bronze database. Corresponds to **Step 8** in the console guide.

```hcl
resource "aws_glue_crawler" "bronze_statistics" {
  name          = "yt-data-pipeline-bronze-crawler-dev"
  role          = aws_iam_role.glue_service_role.arn
  database_name = aws_glue_catalog_database.bronze.name

  s3_target {
    path = "s3://${aws_s3_bucket.bronze.bucket}/youtube/raw_statistics/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.bronze.bucket}/youtube/raw_statistics_reference_data/"
  }
}
```

&nbsp;

### 9. Lambda — JSON to Parquet

Deploys the JSON-to-Parquet Lambda function and grants S3 permission to invoke it via event notification. Corresponds to **Step 10** in the console guide.

```hcl
data "archive_file" "lambda_json_to_parquet" {
  type        = "zip"
  source_file = "docs/resources/lambda_json_to_parquet.py"
  output_path = "lambda_json_to_parquet.zip"
}

# Declare the Lambda log group EXPLICITLY with a retention policy. Without
# this, Lambda auto-creates "/aws/lambda/<function-name>" on first invocation
# with retention = "Never Expire" — an unbounded, silent, ever-growing storage
# cost (CloudWatch Logs: $0.03/GB/month, paid monthly forever). Declaring the
# log group here forces Terraform to create it FIRST, so Lambda's implicit
# auto-create never runs. 14 days is a defensible default for dev/staging.
resource "aws_cloudwatch_log_group" "lambda_json_to_parquet" {
  name              = "/aws/lambda/yt-data-pipeline-json-to-parquet-dev"
  retention_in_days = 14
}

resource "aws_lambda_function" "json_to_parquet" {
  function_name    = "yt-data-pipeline-json-to-parquet-dev"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "lambda_json_to_parquet.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 512
  filename         = data.archive_file.lambda_json_to_parquet.output_path
  source_code_hash = data.archive_file.lambda_json_to_parquet.output_base64sha256

  # Explicit dependency on the log group so Terraform creates the log group
  # BEFORE the Lambda. Without this, a race between Lambda's auto-create and
  # our explicit resource can result in the log group being created by Lambda
  # first (with Never-Expire retention) and then adopted — the retention
  # setting still applies, but retroactively, and any logs written in the
  # interim keep the old retention.
  depends_on = [aws_cloudwatch_log_group.lambda_json_to_parquet]

  layers = [
    "arn:aws:lambda:${data.aws_region.current.name}:336392948345:layer:AWSSDKPandas-Python312:${var.pandas_layer_version}"
  ]

  environment {
    variables = {
      s3_cleansed_layer          = "s3://${aws_s3_bucket.silver.bucket}/youtube/raw_statistics_reference_data/"
      glue_catalog_db_name       = aws_glue_catalog_database.silver.name
      glue_catalog_table_name    = "clean_reference_data"
      write_data_operation       = "append"
    }
  }
}

# Allow S3 to invoke the Lambda (confused-deputy guard: source_arn + source_account)
resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id   = "AllowS3InvokeJsonToParquet"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.json_to_parquet.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.bronze.arn
  source_account = data.aws_caller_identity.current.account_id
}
```

&nbsp;

### 10. S3 Event Notification (Lambda Trigger)

Triggers the JSON-to-Parquet Lambda when new JSON files land in the Bronze bucket. Corresponds to **Step 10** in the console guide.

```hcl
resource "aws_s3_bucket_notification" "bronze_events" {
  bucket = aws_s3_bucket.bronze.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.json_to_parquet.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "youtube/raw_statistics_reference_data/"
    filter_suffix       = ".json"
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}
```

&nbsp;

### 11. Glue ETL Job (Bronze → Silver)

Deploys the PySpark ETL job that transforms raw CSV statistics to cleaned Parquet in the Silver layer. Corresponds to **Step 11** in the console guide.

```hcl
resource "aws_glue_job" "bronze_to_silver" {
  name     = "yt-data-pipeline-bronze-to-silver-dev"
  role_arn = aws_iam_role.glue_service_role.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.scripts.bucket}/glue/glue_bronze_to_silver.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-bookmark-option" = "job-bookmark-enable"
    "--TempDir"             = "s3://${aws_s3_bucket.scripts.bucket}/temp/"
    "--bronze_database"     = aws_glue_catalog_database.bronze.name
    "--bronze_table"        = "raw_statistics"
    "--silver_path"         = "s3://${aws_s3_bucket.silver.bucket}/youtube/raw_statistics/"
  }

  glue_version      = "5.0"    # Spark 3.5.4 — GA since Dec 2024, current AWS-recommended default
  number_of_workers = 2
  worker_type       = "G.1X"
  timeout           = 30       # minutes (not seconds — unlike Lambda)
}
```

&nbsp;

### 12. S3 Objects — Upload Glue Scripts

Uploads both PySpark ETL scripts to the Scripts bucket under the `glue/` prefix so the Glue jobs can reference them. Without these uploads, the Glue jobs' `script_location` values point to non-existent files and the first run fails with `ScriptLocation not found`. Corresponds to **Step 11** (Bronze→Silver) and **Step 13** (Silver→Gold) in the console guide — both scripts live in the same Scripts bucket, so they belong in the same Terraform block.

```hcl
resource "aws_s3_object" "glue_bronze_to_silver_script" {
  bucket = aws_s3_bucket.scripts.id
  key    = "glue/glue_bronze_to_silver.py"
  source = "docs/resources/glue_bronze_to_silver.py"
  etag   = filemd5("docs/resources/glue_bronze_to_silver.py")
}

resource "aws_s3_object" "glue_silver_to_gold_script" {
  bucket = aws_s3_bucket.scripts.id
  key    = "glue/glue_silver_to_gold.py"
  source = "docs/resources/glue_silver_to_gold.py"
  etag   = filemd5("docs/resources/glue_silver_to_gold.py")
}
```

&nbsp;

### 13. Lambda — YouTube API Ingestion

Deploys the Lambda function that fetches real-time trending data from the YouTube Data API v3. The API key is stored in AWS Secrets Manager and read at runtime — **never** as a plaintext Lambda env var (any principal with `lambda:GetFunctionConfiguration` would be able to read plaintext env vars). Corresponds to **Step 7** in the console guide.

```hcl
# Secrets Manager entry for the YouTube API key. The value is supplied via var.youtube_api_key
# (which should be set via `TF_VAR_youtube_api_key` env var or a .tfvars file in .gitignore).
resource "aws_secretsmanager_secret" "youtube_api_key" {
  name        = "yt-data-pipeline/youtube-api-key-dev"
  description = "Google YouTube Data API v3 key used by the ingestion Lambda"
}

resource "aws_secretsmanager_secret_version" "youtube_api_key" {
  secret_id     = aws_secretsmanager_secret.youtube_api_key.id
  secret_string = var.youtube_api_key
}

# Additional IAM statement granting the Lambda role permission to read ONLY this one secret.
resource "aws_iam_role_policy" "lambda_youtube_secret_read" {
  name = "yt-pipeline-youtube-secret-read"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.youtube_api_key.arn
    }]
  })
}

data "archive_file" "lambda_youtube_ingestion" {
  type        = "zip"
  source_file = "docs/resources/lambda_youtube_api_ingestion.py"
  output_path = "lambda_youtube_ingestion.zip"
}

# Explicit log group with bounded retention — see the comment on the JSON-to-Parquet
# log group (Section 9) for the full rationale. Short version: Lambda auto-creates
# log groups with "Never Expire" retention otherwise.
resource "aws_cloudwatch_log_group" "lambda_youtube_ingestion" {
  name              = "/aws/lambda/yt-data-pipeline-youtube-ingestion-dev"
  retention_in_days = 14
}

resource "aws_lambda_function" "youtube_ingestion" {
  function_name    = "yt-data-pipeline-youtube-ingestion-dev"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "lambda_youtube_api_ingestion.lambda_handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 512
  filename         = data.archive_file.lambda_youtube_ingestion.output_path
  source_code_hash = data.archive_file.lambda_youtube_ingestion.output_base64sha256

  depends_on = [aws_cloudwatch_log_group.lambda_youtube_ingestion]

  environment {
    variables = {
      # API key is NOT stored here — Lambda code calls secretsmanager:GetSecretValue at runtime.
      YOUTUBE_API_KEY_SECRET_ARN = aws_secretsmanager_secret.youtube_api_key.arn
      S3_BUCKET                  = aws_s3_bucket.bronze.bucket
      SNS_ALERT_TOPIC_ARN        = aws_sns_topic.pipeline_alerts.arn
    }
  }
}
```

> **Lambda code change required:** the handler reads the secret via `boto3.client('secretsmanager').get_secret_value(SecretId=os.environ['YOUTUBE_API_KEY_SECRET_ARN'])['SecretString']` instead of `os.environ['youtube_api_key']`. Cache the value at module scope so warm invocations reuse it. See the updated reference implementation in `docs/resources/lambda_youtube_api_ingestion.py`.

&nbsp;

### 14. Lambda — Data Quality Gate

Deploys the Lambda function that validates Silver layer data before it reaches Gold. Corresponds to **Step 12** in the console guide.

```hcl
data "archive_file" "lambda_data_quality" {
  type        = "zip"
  source_file = "docs/resources/lambda_data_quality.py"
  output_path = "lambda_data_quality.zip"
}

# Explicit log group with bounded retention — see Section 9 for rationale.
resource "aws_cloudwatch_log_group" "lambda_data_quality" {
  name              = "/aws/lambda/yt-data-pipeline-data-quality-dev"
  retention_in_days = 14
}

resource "aws_lambda_function" "data_quality" {
  function_name    = "yt-data-pipeline-data-quality-dev"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "lambda_data_quality.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 512
  filename         = data.archive_file.lambda_data_quality.output_path
  source_code_hash = data.archive_file.lambda_data_quality.output_base64sha256

  depends_on = [aws_cloudwatch_log_group.lambda_data_quality]

  layers = [
    "arn:aws:lambda:${data.aws_region.current.name}:336392948345:layer:AWSSDKPandas-Python312:${var.pandas_layer_version}"
  ]

  environment {
    variables = {
      SILVER_DATABASE = aws_glue_catalog_database.silver.name
      SILVER_BUCKET   = aws_s3_bucket.silver.bucket
    }
  }
}
```

&nbsp;

### 15. Glue ETL Job (Silver → Gold)

Deploys the PySpark ETL job that joins cleaned statistics with category reference data to produce analytics-ready Gold tables. The job is idempotent — it uses `DataFrameWriter.mode("overwrite")` with dynamic partition overwrite semantics — and does **not** register tables in the Glue Catalog itself. Catalog refresh is handled by the Gold crawler in block 15b, triggered by the Step Functions state machine. Corresponds to **Step 13** in the console guide.

```hcl
resource "aws_glue_job" "silver_to_gold" {
  name     = "yt-data-pipeline-silver-to-gold-dev"
  role_arn = aws_iam_role.glue_service_role.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.scripts.bucket}/glue/glue_silver_to_gold.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-bookmark-option"  = "job-bookmark-enable"
    "--TempDir"              = "s3://${aws_s3_bucket.scripts.bucket}/temp/"
    "--silver_database"      = aws_glue_catalog_database.silver.name
    "--gold_bucket"          = aws_s3_bucket.gold.bucket
    # NOTE: no --gold_database — the Silver→Gold script writes Parquet only,
    # and the Gold crawler (block 15b) populates the catalog.
  }

  glue_version      = "5.0"    # Spark 3.5.4 — GA since Dec 2024, current AWS-recommended default
  number_of_workers = 2
  worker_type       = "G.1X"
  timeout           = 30       # minutes (not seconds — unlike Lambda)
}
```

&nbsp;

### 15b. Glue Crawler (Gold)

Refreshes the Gold Glue Catalog after every Silver→Gold ETL run. The crawler targets three S3 prefixes (one per Gold table) and registers them in `yt_pipeline_gold_dev` with `region` as an auto-detected partition. On-demand schedule — the Step Functions `CatalogGoldTables` state is the only thing that starts it, which avoids race conditions with in-flight ETL writes. Corresponds to **Step 13.4** in the console guide.

```hcl
resource "aws_glue_crawler" "gold_tables" {
  name          = "yt-data-pipeline-gold-crawler-dev"
  role          = aws_iam_role.glue_service_role.arn
  database_name = aws_glue_catalog_database.gold.name

  s3_target {
    path = "s3://${aws_s3_bucket.gold.bucket}/youtube/trending_analytics/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.gold.bucket}/youtube/channel_analytics/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.gold.bucket}/youtube/category_analytics/"
  }
}
```

&nbsp;

### 16. Step Functions State Machine

Deploys the pipeline orchestrator that runs the end-to-end flow: ingest → wait → parallel transform → quality check → Gold ETL → notify. Corresponds to **Step 14** in the console guide.

```hcl
resource "aws_sfn_state_machine" "pipeline_orchestration" {
  name     = "yt-data-pipeline-orchestration-dev"
  role_arn = aws_iam_role.step_functions_role.arn

  definition = jsonencode({
    Comment = "YouTube Trending Data Pipeline Orchestration"
    StartAt = "IngestFromYouTubeAPI"
    States = {
      IngestFromYouTubeAPI = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.youtube_ingestion.arn
          Payload      = { "triggered_by" = "step_function" }
        }
        ResultPath = "$.ingestionResult"
        Retry      = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 5, MaxAttempts = 2 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], Next = "NotifyFailure" }]
        Next       = "WaitForS3Consistency"
      }
      WaitForS3Consistency = {
        Type    = "Wait"
        Seconds = 10
        Next    = "ProcessInParallel"
      }
      ProcessInParallel = {
        Type = "Parallel"
        Branches = [
          {
            StartAt = "TransformJSON"
            States = {
              TransformJSON = {
                Type     = "Task"
                Resource = "arn:aws:states:::lambda:invoke"
                Parameters = {
                  FunctionName = aws_lambda_function.json_to_parquet.arn
                }
                Retry = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 5, MaxAttempts = 2 }]
                End   = true
              }
            }
          },
          {
            StartAt = "RunBronzeToSilverETL"
            States = {
              RunBronzeToSilverETL = {
                Type     = "Task"
                Resource = "arn:aws:states:::glue:startJobRun.sync"
                Parameters = {
                  JobName = aws_glue_job.bronze_to_silver.name
                }
                Retry = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 10, MaxAttempts = 2 }]
                End   = true
              }
            }
          }
        ]
        ResultPath = "$.parallelResult"
        Catch      = [{ ErrorEquals = ["States.ALL"], Next = "NotifyFailure" }]
        Next       = "RunDataQualityCheck"
      }
      RunDataQualityCheck = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.data_quality.arn
        }
        ResultPath = "$.qualityResult"
        Retry      = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 5, MaxAttempts = 2 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], Next = "NotifyFailure" }]
        Next       = "EvaluateQuality"
      }
      EvaluateQuality = {
        Type = "Choice"
        Choices = [{
          Variable     = "$.qualityResult.Payload.status"
          StringEquals = "PASS"
          Next         = "RunSilverToGoldETL"
        }]
        Default = "NotifyFailure"
      }
      RunSilverToGoldETL = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = aws_glue_job.silver_to_gold.name
        }
        Retry = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 10, MaxAttempts = 2 }]
        Catch = [{ ErrorEquals = ["States.ALL"], Next = "NotifyFailure" }]
        Next  = "CatalogGoldTables"
      }
      # Gold crawler states — refresh the Glue Catalog now that the Silver→Gold
      # job no longer registers tables itself. See Step 13.4 / 14.2 in the guide
      # for the rationale and the state machine diagram.
      CatalogGoldTables = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:glue:startCrawler"
        Parameters = {
          Name = aws_glue_crawler.gold_tables.name
        }
        Retry = [
          # Another crawler run may be in flight from a concurrent execution —
          # back off and retry rather than failing the whole pipeline.
          { ErrorEquals = ["Glue.CrawlerRunningException"], IntervalSeconds = 30, MaxAttempts = 4, BackoffRate = 2 },
          { ErrorEquals = ["States.ALL"],                   IntervalSeconds = 15, MaxAttempts = 2, BackoffRate = 2 }
        ]
        Catch = [{ ErrorEquals = ["States.ALL"], Next = "NotifyCatalogFailure" }]
        Next  = "WaitForCrawlerToFinish"
      }
      WaitForCrawlerToFinish = {
        Type    = "Wait"
        Seconds = 30
        Next    = "CheckCrawlerState"
      }
      CheckCrawlerState = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:glue:getCrawler"
        Parameters = {
          Name = aws_glue_crawler.gold_tables.name
        }
        ResultPath = "$.goldCrawlerStatus"
        Next       = "IsCrawlerDone"
      }
      IsCrawlerDone = {
        Type = "Choice"
        Choices = [
          { Variable = "$.goldCrawlerStatus.Crawler.State", StringEquals = "READY",    Next = "NotifySuccess" },
          { Variable = "$.goldCrawlerStatus.Crawler.State", StringEquals = "RUNNING",  Next = "WaitForCrawlerToFinish" },
          { Variable = "$.goldCrawlerStatus.Crawler.State", StringEquals = "STOPPING", Next = "WaitForCrawlerToFinish" }
        ]
        Default = "NotifyCatalogFailure"
      }
      NotifySuccess = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = aws_sns_topic.pipeline_alerts.arn
          Message  = "Pipeline completed successfully. Gold catalog refreshed."
          Subject  = "YT Pipeline — Success"
        }
        End = true
      }
      NotifyFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = aws_sns_topic.pipeline_alerts.arn
          "Message.$"  = "States.Format('Pipeline failed. Error: {}', $.Error)"
          Subject  = "YT Pipeline — FAILURE"
        }
        End = true
      }
      # Distinct terminal for catalog-only failures: Gold Parquet was written
      # successfully, so this is recoverable by re-running the crawler manually.
      # Differentiating the subject line helps on-call distinguish "data bad" vs
      # "data good, catalog stale."
      NotifyCatalogFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = aws_sns_topic.pipeline_alerts.arn
          "Message.$"  = "States.Format('Gold Parquet was written successfully, but the Gold crawler failed. Athena queries may see stale schema until the crawler is re-run. Error: {}', $.Error)"
          Subject  = "YT Pipeline — Catalog refresh failed"
        }
        End = true
      }
    }
  })
}
```

&nbsp;

### 17. EventBridge Schedule (Pipeline Trigger)

Fires the state machine daily at 02:00 UTC via a cron-based schedule. Uses **EventBridge Scheduler** — the current AWS recommendation for schedules (the older "EventBridge Rules → Schedule" path has been removed from new console flows). The `aws_iam_role` below is the dedicated Scheduler invoke role — Scheduler assumes it when the schedule ticks, then calls `states:StartExecution` on the orchestrator. Corresponds to **Step 14.5** in the console guide.

```hcl
resource "aws_iam_role" "scheduler_invoke_stepfn" {
  name = "yt-data-pipeline-scheduler-role-dev"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_stepfn" {
  name = "scheduler-invoke-stepfn-access"
  role = aws_iam_role.scheduler_invoke_stepfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "StartPipelineExecution"
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.pipeline_orchestration.arn
    }]
  })
}

resource "aws_scheduler_schedule" "pipeline_schedule" {
  name        = "yt-data-pipeline-daily-dev"
  description = "Run YT data pipeline daily at 02:00 UTC"
  group_name  = "default"

  schedule_expression          = "cron(0 2 * * ? *)"
  schedule_expression_timezone = "UTC"
  state               = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.pipeline_orchestration.arn
    role_arn = aws_iam_role.scheduler_invoke_stepfn.arn
    input    = jsonencode({})
  }
}
```

> **Why a separate IAM role, not the Step Functions role reused:** The Step Functions execution role (`aws_iam_role.step_functions_role` from [Section 5](#5-iam--step-functions-role)) grants the state machine permissions to do its internal work — invoke Lambdas, run Glue jobs, publish SNS. It has no trust relationship with `scheduler.amazonaws.com`, so Scheduler can't assume it even if we wanted to. This invoke role carries a single permission (`states:StartExecution`) and a separate trust policy, keeping blast radius minimal if the role is ever misused.
>
> **Why Scheduler, not EventBridge Rules:** `aws_cloudwatch_event_rule` + `aws_cloudwatch_event_target` with a `schedule_expression` still works, but AWS has deprecated it in the console (the "Schedule" rule type is no longer exposed in new-rule creation flows) and recommends Scheduler for all new work. Scheduler also supports timezones, one-off `at(...)` schedules, and flexible time windows that EventBridge Rules don't.

&nbsp;

### 18. Tagging + Cost Allocation (Post-Apply Admin Step)

The `default_tags` block in the provider (shown at the top of this Terraform reference) applies `Project`, `Env`, and `ManagedBy` to every taggable resource automatically. Terraform writes the tags; Cost Explorer does **not** use them out of the box. To actually break down the AWS bill by pipeline, someone with Billing access has to activate each tag as a **cost-allocation tag** — a one-time, per-AWS-account step that can't be done from Terraform (the Billing API requires organization-master-account credentials with no IAM-policy surface to delegate cleanly).

**One-time activation:**

1. Sign in as the AWS account root or a user with `aws-portal:*` billing permissions
2. Go to **Billing and Cost Management → Cost allocation tags**
3. Under **User-defined cost allocation tags**, find `Project`, `Env`, and `ManagedBy` in the list (they appear after the first `terraform apply` once AWS has seen the tags at least once — this can take up to 24 hours)
4. Check each one → click **Activate**

After activation, Cost Explorer (and the Billing CSV export) will accept these as group-by / filter dimensions:

| Question | Cost Explorer filter |
|----------|----------------------|
| "What does the YouTube pipeline cost us this month?" | Group by tag `Project`, filter `Project = yt-data-pipeline` |
| "What's our dev vs prod spend?" | Group by tag `Env` |
| "Which resources are Terraform-managed vs created by hand?" | Filter `ManagedBy = Terraform` (untagged resources show up as "(no value)" and are your manual-creation leaks) |

> **Why this is a manual step and not a Terraform resource:** The Billing API that toggles cost-allocation tags (`ce:UpdateCostAllocationTagsStatus`) exists only at the organization-master account level, not per-sub-account. There's no `aws_ce_cost_allocation_tag` Terraform resource because the semantics don't fit the standard provider model. AWS treats this as an account-level administrative action, not infrastructure.

> **On naming:** Use `PascalCase` keys for tag names in AWS (`Project`, not `project`). Tag keys are case-sensitive, and AWS's own managed tags (applied by services like ElasticBeanstalk, CloudFormation) all use PascalCase. Mixing cases means a tag key `Project` and `project` become two separate dimensions in Cost Explorer — a common mistake that splits a pipeline's costs across two filter values.

> **Before `terraform apply`:** Populate the input variables either via a `terraform.tfvars` file or via `-var` flags on the CLI. Minimum required values:
>
> ```hcl
> # terraform.tfvars (do NOT commit this file — add to .gitignore)
> aws_region         = "eu-north-1"
> notification_email = "you@example.com"
> youtube_api_key    = "AIza..."         # prefer -var or environment variable TF_VAR_youtube_api_key
> env                = "dev"             # default; override to "staging" or "prod" for other environments
> ```
>
> Note: there is no `bucket_suffix` variable — bucket names are constructed from the AWS account ID at plan time via `data.aws_caller_identity.current.account_id`, so they're automatically globally unique per account.
>
> For the API key, pass it as an environment variable instead of a file to avoid committing it to disk: `export TF_VAR_youtube_api_key="AIza..."`. Terraform picks up any `TF_VAR_*` env var automatically. Every other AWS resource reference is resolved automatically by Terraform at plan time. Run `terraform validate` for a syntax-only check and `terraform plan` to preview the graph before applying.
>
> **After the first `terraform apply`** — activate the `Project`, `Env`, and `ManagedBy` tags as cost-allocation dimensions in the Billing console. See [Section 18](#18-tagging--cost-allocation-post-apply-admin-step) for the one-time admin step. Without this, the tags are applied to resources but not usable for Cost Explorer filtering.
