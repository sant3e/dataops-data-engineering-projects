# CoinGecko ETL Pipeline — Full AWS (Glue + Athena)

**Topic:** Alternative loading layer for the CoinGecko ETL pipeline using AWS Glue Data Catalog and Amazon Athena instead of Snowflake

![Full-AWS pipeline architecture — EventBridge, Lambda extract/transform, S3 storage, Glue Crawler, Data Catalog, and Athena](docs/diagrams/s3_to_glue_architecture.svg)

> **Companion guide:** This is a continuation of the base pipeline documented in [aws_snowflake_pipeline_setup.md](./aws_snowflake_pipeline_setup.md).
> The first pipeline extracts CoinGecko cryptocurrency data, transforms it via Lambda, and stores it as CSV files in S3.
> This guide covers the **alternative loading layer** — instead of Snowflake, we use AWS Glue Data Catalog and Amazon Athena.

---

## Data Flow

This pipeline picks up where the [primary pipeline](./aws_snowflake_pipeline_setup.md) leaves off — CSVs already exist in S3. It replaces Snowflake + Snowpipe with AWS Glue Data Catalog + Amazon Athena; no data is copied or loaded, Athena reads S3 directly at query time.

```
1. PRODUCE    Transform Lambda (from the primary pipeline) runs
                → writes CSVs to S3: <bucket>/transformed_data/{coin_data,market_data,price_data}/

2. CATALOG    Register the table schema in the AWS Glue Data Catalog (one-time setup)
                → Approach 1: run the Glue Crawler (auto-detects schema from S3 files)
                → Approach 2: run Athena DDL (manual `CREATE EXTERNAL TABLE` statements)
                → result: 3 tables in coingecko_db — coin_data, market_data, price_data

3. QUERY      Amazon Athena reads the Data Catalog for schema resolution
                → queries CSV files directly in S3 (no data copied, no cluster managed)
                → pay per query: $5 per TB scanned
```

---

## S3 Bucket Layout

```
coingecko-etl-bucket/
└── transformed_data/                                 ← Pre-existing prefix (built by the primary pipeline)
    ├── coin_data/                                    ← CSVs → Athena table: coingecko_db.coin_data
    ├── market_data/                                  ← CSVs → Athena table: coingecko_db.market_data
    └── price_data/                                   ← CSVs → Athena table: coingecko_db.price_data
```

> **Note:** This pipeline reads from the bucket already provisioned by the [primary pipeline](./aws_snowflake_pipeline_setup.md#s3-bucket-layout). Only the 3 `transformed_data/` prefixes are queried by Athena — `raw_data/` is not used here.

---

## AWS Services Used

| Service | Role in This Pipeline | Pricing Model |
|---|---|---|
| **S3** | Stores the CSVs (shared with the primary pipeline) | Storage + request fees |
| **AWS Glue Data Catalog** | Stores table metadata (database, schema, S3 locations) | Free tier: 1M objects/month |
| **AWS Glue Crawler** | Auto-detects schema from S3 files (optional) | Per DPU-hour ($0.44/DPU-hour) |
| **Amazon Athena** | Serverless SQL queries against S3 data | $5 per TB scanned |
| **IAM** | Role for Glue Crawler to access S3 and Data Catalog | Free |

---

## Component-by-Component Walkthrough

### AWS Glue Crawler

The Glue Crawler scans S3 paths, infers the file format and schema, and writes table definitions to the Glue Data Catalog. For this pipeline, the crawler targets three S3 prefixes under `transformed_data/`.

**Key behaviors:**
- Infers column names and types from file content
- Creates one table per S3 prefix (when properly configured)
- Requires an IAM role with S3 read access and Glue Data Catalog write access
- For all-string CSV data, the built-in classifier cannot reliably detect headers — a known limitation documented in Step 3 below

### AWS Glue Data Catalog

The Data Catalog is AWS's centralized metadata store — it holds database and table definitions that Athena, Redshift Spectrum, and EMR all share. For this pipeline:

- **Database:** `coingecko_db`
- **Tables:** `coin_data`, `market_data`, `price_data`
- Each table stores: column names, column types, S3 location, SerDe (serialization/deserialization) configuration, and table properties like `skip.header.line.count`

The Data Catalog is metadata only — it never stores actual data.

### Amazon Athena

Athena is a serverless SQL query engine that reads data directly from S3 using schema definitions in the Glue Data Catalog. Key characteristics:

- **No infrastructure to manage** — no clusters, no servers, no provisioning
- **Pay per query** — $5 per TB of data scanned
- **Standard SQL** — uses Presto/Trino under the hood
- **Immediate availability** — new CSV files in S3 are queryable instantly, no ingestion step

---

## How Athena Tables Work

Athena tables are always **external tables** — data stays in S3 and is read in place at query time. This means:

- New CSV files written by the Lambda are **immediately queryable** — no ingestion step needed
- The Glue Data Catalog only stores the **schema and S3 location** — it is a metadata index, not a data store
- This is the same concept as `EXTERNAL TABLE` in Snowflake, except in Athena there is no other kind
- Deleting a table in the Data Catalog does **not** delete the S3 data — only the metadata is removed

---

## Two Approaches to Table Creation

The Glue Data Catalog tables can be created in two ways. Both result in identical query behavior in Athena.

| | Approach 1: Glue Crawler | Approach 2: Athena DDL |
|---|---|---|
| How schema is defined | Inferred automatically from files | Declared explicitly by you |
| Setup effort | Low initially | Minimal — one SQL statement per table |
| Reliability for all-string CSV | ⚠️ Unreliable — known limitation | ✅ Always correct |
| Header row handling | Requires classifier workarounds | `skip.header.line.count=1` in DDL |
| Schema changes | Re-crawl (may misdetect again) | `ALTER TABLE` or recreate |
| Recommended for this pipeline | No — schema is known and fixed | ✅ Yes |

> **Recommendation:** Use **Approach 2 (Athena DDL)** for this pipeline. The Lambda output schema is fixed and fully known — there is no benefit to having the crawler guess it. Step 3 below documents the crawler path in full for reference. Jump to [Step 4: Approach 2 — Athena DDL](#step-4-approach-2--athena-ddl--recommended) to use the recommended approach.

---

## Step 1: Prerequisites

This guide assumes you have already built the base pipeline from the [primary guide](./aws_snowflake_pipeline_setup.md) — the S3 bucket (`coingecko-etl-bucket`) with its folder structure, both Lambda functions (extract + transform), and the EventBridge scheduler are all in place. You should also have at least one successful pipeline run so that CSV files exist in `transformed_data/coin_data/`, `transformed_data/market_data/`, and `transformed_data/price_data/`.

With that infrastructure ready, this guide adds the Glue Data Catalog and Athena query layer on top.

---

## Step 2: Glue Database

Create the logical database namespace in the Glue Data Catalog.

1. Go to **AWS Glue → Data Catalog → Databases → Add database**
2. Name: `coingecko_db`
3. Leave **Location** blank (not needed for a metadata-only database)
4. Click **Create database**

Or via CLI:

```bash
aws glue create-database \
  --database-input '{"Name":"coingecko_db","Description":"CoinGecko ETL tables (coin_data, market_data, price_data)"}' \
  --region eu-west-2
```

This database will hold all three tables (`coin_data`, `market_data`, `price_data`).

> Terraform: [2. Glue Database](#2-glue-database)

### Verify

Go to **AWS Glue → Data Catalog → Databases** and confirm `coingecko_db` appears in the list.

Or via CLI:

```bash
aws glue get-database --name coingecko_db --region eu-west-2
```

---

## Step 3: Approach 1 — Glue Crawler

> **Note:** This approach uses the Glue Crawler to auto-detect the schema from the CSV files and register the tables in the Data Catalog. For this pipeline's all-string CSV data, the built-in classifier cannot reliably detect column names — a custom classifier with manual header configuration is required, and post-crawl schema fixes are needed. All steps are documented in full below. If you want to skip this complexity, jump to [Step 4: Approach 2 — Athena DDL](#step-4-approach-2--athena-ddl--recommended).

### 3.1 — IAM Role for Glue Crawler

The Glue Crawler needs an IAM role to access S3 and write to the Glue Data Catalog. Since the `developer` role has a Permissions Boundary that prevents creating roles, ask your admin to create a dedicated role.

**Role requirements:**
- **Role name:** `coingecko-glue-crawler-role`
- **Trusted principal:** `glue.amazonaws.com`
- **Managed policy:** `AWSGlueServiceRole` (provides Data Catalog write access)
- **Inline policy:** `glue-coingecko-s3-access` — grants `s3:GetObject`, `s3:ListBucket`, `s3:PutObject` on `coingecko-etl-bucket`

**Trust policy:**
```json
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
```

**Inline S3 access policy (`glue-coingecko-s3-access`):**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket", "s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::coingecko-etl-bucket",
        "arn:aws:s3:::coingecko-etl-bucket/*"
      ]
    }
  ]
}
```

Or via CLI (admin with IAM create privileges):

```bash
# 1. Create the role with the trust policy
cat > trust-policy-glue.json <<'EOF'
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

aws iam create-role \
  --role-name coingecko-glue-crawler-role \
  --assume-role-policy-document file://trust-policy-glue.json

# 2. Attach the managed Glue service role policy
aws iam attach-role-policy \
  --role-name coingecko-glue-crawler-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole

# 3. Attach the inline S3 access policy
aws iam put-role-policy \
  --role-name coingecko-glue-crawler-role \
  --policy-name glue-coingecko-s3-access \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":["s3:GetObject","s3:ListBucket","s3:PutObject"],
      "Resource":["arn:aws:s3:::coingecko-etl-bucket","arn:aws:s3:::coingecko-etl-bucket/*"]
    }]
  }'
```

> Terraform: [1. IAM — Glue Crawler Role](#1-iam--glue-crawler-role)

#### Why a dedicated role?

The `developer` role is assumed via Okta SAML federation — its Trust Policy only allows human login, not AWS services. Glue requires a role with `glue.amazonaws.com` as a trusted principal. The `developer` role also has a Permissions Boundary that restricts role creation.

---

### 3.2 — Create the Crawler

Go to **AWS Glue → Crawlers → Create crawler**.

#### 3.2.1 — Crawler Properties
- Name: `coingecko_data_crawler`

#### 3.2.2 — Data Sources
- Data source type: **S3**
- S3 path: `s3://coingecko-etl-bucket/transformed_data/coin_data/`
- Crawl behavior: **Recrawl all**
- Click **Add an S3 data source**

> **Note:** Start with `coin_data/` only. Add `market_data/` and `price_data/` as separate data sources after verifying the first one works, or add all three at once if preferred.

#### 3.2.3 — Security Settings
- IAM role: select `coingecko-glue-crawler-role`

#### 3.2.4 — Output and Scheduling
- Target database: `coingecko_db`
- Schedule: **On demand** (run manually for now)

#### 3.2.5 — Advanced Settings (important)

Verify these settings:
- **Schema updates in the data store**: `Update the table definition in the data catalog`
- **Object deletion**: `Mark the table as deprecated in the data catalog`
- **Repeat crawls**: `Crawl all folders again with every subsequent crawl`

Click **Create crawler**.

Or via CLI (creates the crawler directly, targeting all 3 prefixes — replace `<ACCOUNT_ID>`):

```bash
aws glue create-crawler \
  --name coingecko_data_crawler \
  --role arn:aws:iam::<ACCOUNT_ID>:role/coingecko-glue-crawler-role \
  --database-name coingecko_db \
  --targets '{
    "S3Targets": [
      { "Path": "s3://coingecko-etl-bucket/transformed_data/coin_data/" },
      { "Path": "s3://coingecko-etl-bucket/transformed_data/market_data/" },
      { "Path": "s3://coingecko-etl-bucket/transformed_data/price_data/" }
    ]
  }' \
  --schema-change-policy '{
    "UpdateBehavior": "UPDATE_IN_DATABASE",
    "DeleteBehavior": "DEPRECATE_IN_DATABASE"
  }' \
  --recrawl-policy '{ "RecrawlBehavior": "CRAWL_EVERYTHING" }' \
  --region eu-west-2
```

> Terraform: [3. Glue Crawler](#3-glue-crawler)

---

### 3.3 — Run and Verify the Crawler

1. Go to **Glue → Crawlers → coingecko_data_crawler → Run crawler**
2. Wait for status to return to `Ready` (~30–60 seconds)
3. Check **Last run status** → should show `Succeeded`
4. Go to **Glue → Databases → coingecko_db → Tables** → verify `coin_data` was created

Or via CLI:

```bash
# Run the crawler
aws glue start-crawler --name coingecko_data_crawler --region eu-west-2

# Poll status until it returns to READY
aws glue get-crawler --name coingecko_data_crawler --region eu-west-2 \
  --query 'Crawler.{State:State,LastCrawl:LastCrawl.Status}'

# List tables created in the database
aws glue get-tables --database-name coingecko_db --region eu-west-2 \
  --query 'TableList[].Name'
```

---

### 3.4 — Classifier Workaround

#### The problem

AWS Glue's built-in CSV classifier produces generic column names (`col0`, `col1`...) for all-string CSV files because it cannot statistically distinguish the header row from data rows when all values are strings.

Custom classifiers with `Detect headings` detect headers but do not reliably apply them to table creation. The `Has headings` setting requires the Header field to be filled manually and does not read from the file.

#### Root cause (confirmed)

The table JSON confirms the built-in classifier is always applied, never the custom one:

```json
{
  "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
  "Parameters": { "field.delim": "," }
}
```

No `skip.header.line.count`, no `OpenCSVSerDe`, no named columns — all signs of built-in classifier output.

#### Workaround — Fix the table manually after crawling

After running the crawler, apply two fixes:

**Fix 1 — Rename columns**

Go to **Glue → Databases → coingecko_db → Tables → coin_data → Edit schema**

Rename each column:

| Old name | New name | Type |
|---|---|---|
| `col0` | `id` | `string` |
| `col1` | `symbol` | `string` |
| `col2` | `name` | `string` |
| `col3` | `market_cap_tier` | `string` |
| `col4` | `extracted_at` | `string` |

Click **Save as new table version**.

**Fix 2 — Skip the header row**

Go to **Glue → Tables → coin_data → Edit table → Table properties → Add**:

| Key | Value |
|---|---|
| `skip.header.line.count` | `1` |

Save the table.

> **Warning:** If the crawler re-runs, it will overwrite these manual changes. Either run the crawler only when needed, or re-apply the fixes after each crawl. As an alternative, use Approach 2 below which avoids this problem entirely.

---

### 3.5 — Verify in Athena

After applying the column renames and header skip:

1. Go to **Amazon Athena → Query editor**
2. Select database: `coingecko_db`
3. Run:

```sql
SELECT * FROM coingecko_db.coin_data LIMIT 10;
```

**Expected result:** Rows with named columns (`id`, `symbol`, `name`, `market_cap_tier`, `extracted_at`) and no header row in the data.

Or via CLI:

```bash
# Kick off the query; returns an execution ID
QID=$(aws athena start-query-execution \
  --query-string "SELECT * FROM coingecko_db.coin_data LIMIT 10" \
  --query-execution-context Database=coingecko_db \
  --result-configuration OutputLocation=s3://coingecko-etl-bucket/athena-results/ \
  --region eu-west-2 \
  --query 'QueryExecutionId' --output text)

# Wait for completion and fetch results
aws athena get-query-execution --query-execution-id "$QID" --region eu-west-2 \
  --query 'QueryExecution.Status.State'

aws athena get-query-results --query-execution-id "$QID" --region eu-west-2
```

---

## Step 4: Approach 2 — Athena DDL ✅ Recommended

Instead of using the Glue Crawler to infer the schema, define the tables directly in Athena using `CREATE EXTERNAL TABLE`. Athena writes the table metadata to the Glue Data Catalog automatically — the end result is identical to what the crawler produces, but with full control over column names, types, and header handling.

**When to use this approach:**
- You own the Lambda that produces the files and know the schema exactly
- The crawler's schema detection is unreliable (all-string CSV — as experienced in Step 3)
- You want a stable, repeatable table definition that won't be overwritten by future crawler runs
- You're starting fresh and want to skip the crawler entirely

If you used the crawler in Step 3, delete the crawler-created tables from `coingecko_db` first. Then run the following DDL statements in the Athena Query Editor.

> **Via CLI:** Instead of running each DDL interactively, wrap them in `aws athena start-query-execution` calls. One generic helper at the bottom of this step runs any of the three DDL statements from a file.

### coin_data

```sql
CREATE EXTERNAL TABLE coingecko_db.coin_data (
  id               STRING,
  symbol           STRING,
  name             STRING,
  market_cap_tier  STRING,
  extracted_at     STRING
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
LOCATION 's3://coingecko-etl-bucket/transformed_data/coin_data/'
TBLPROPERTIES ('skip.header.line.count'='1');
```

### market_data

```sql
CREATE EXTERNAL TABLE coingecko_db.market_data (
  id                    STRING,
  market_cap            STRING,
  total_volume          STRING,
  circulating_supply    STRING,
  volume_to_mcap_ratio  STRING,
  extracted_at          STRING
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
LOCATION 's3://coingecko-etl-bucket/transformed_data/market_data/'
TBLPROPERTIES ('skip.header.line.count'='1');
```

### price_data

```sql
CREATE EXTERNAL TABLE coingecko_db.price_data (
  id                            STRING,
  current_price                 STRING,
  high_24h                      STRING,
  low_24h                       STRING,
  ath                           STRING,
  ath_date                      STRING,
  price_change_percentage_24h   STRING,
  price_to_ath_ratio            STRING,
  daily_price_range             STRING,
  days_since_ath                STRING,
  last_updated                  STRING,
  extracted_at                  STRING
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
LOCATION 's3://coingecko-etl-bucket/transformed_data/price_data/'
TBLPROPERTIES ('skip.header.line.count'='1');
```

> The Glue Crawler can still be kept and used to detect new partitions or files — it won't overwrite these tables if you set its **Schema change behavior** to `Log only`. But for schema definition, the DDL above is the single source of truth.

Or via CLI (run any DDL file against Athena):

```bash
# Save one of the CREATE EXTERNAL TABLE statements above to a file, e.g. coin_data_ddl.sql
aws athena start-query-execution \
  --query-string "$(cat coin_data_ddl.sql)" \
  --query-execution-context Database=coingecko_db \
  --result-configuration OutputLocation=s3://coingecko-etl-bucket/athena-results/ \
  --region eu-west-2
```

### Verify Tables

After running all three DDL statements:

1. Go to **Glue → Databases → coingecko_db → Tables**
2. Confirm all three tables appear: `coin_data`, `market_data`, `price_data`
3. Click each table and verify the column names and types match the DDL above

Or via CLI:

```bash
aws glue get-tables --database-name coingecko_db --region eu-west-2 \
  --query 'TableList[].{Name:Name,Columns:StorageDescriptor.Columns[].Name}'
```

---

## Step 5: Querying with Athena

Once the tables exist in the Glue Data Catalog — regardless of whether you used Step 3 or Step 4 — querying works identically.

### Set the Output Location

Athena requires an S3 location to store query results. If prompted:

1. Go to **Athena → Settings → Manage**
2. Set query result location: `s3://coingecko-etl-bucket/athena-results/`
3. Click **Save**

Or via CLI (set the default workgroup output location):

```bash
aws athena update-work-group \
  --work-group primary \
  --configuration-updates '{
    "ResultConfigurationUpdates": {
      "OutputLocation": "s3://coingecko-etl-bucket/athena-results/"
    },
    "EnforceWorkGroupConfiguration": true
  }' \
  --region eu-west-2
```

### Sample Queries

**All coins with their market cap tier:**

```sql
SELECT id, symbol, name, market_cap_tier
FROM coingecko_db.coin_data
ORDER BY market_cap_tier;
```

**Mega cap coins only:**

```sql
SELECT id, symbol, name
FROM coingecko_db.coin_data
WHERE market_cap_tier = 'Mega';
```

**Join coin info with price data:**

```sql
SELECT c.name, c.symbol, c.market_cap_tier,
       p.current_price, p.price_change_percentage_24h
FROM coingecko_db.coin_data c
JOIN coingecko_db.price_data p ON c.id = p.id
WHERE c.extracted_at = p.extracted_at
ORDER BY CAST(p.current_price AS DOUBLE) DESC
LIMIT 20;
```

**Coins with highest volume-to-market-cap ratio:**

```sql
SELECT c.name, m.volume_to_mcap_ratio
FROM coingecko_db.coin_data c
JOIN coingecko_db.market_data m ON c.id = m.id
ORDER BY CAST(m.volume_to_mcap_ratio AS DOUBLE) DESC
LIMIT 10;
```

---

## Terraform Reference

This section provides a complete, copy-pasteable Terraform configuration that reproduces every AWS resource built through the console guide above. You can use it in two ways: **(a)** hand the entire file to your DevOps team so they can provision the pipeline in a repeatable, auditable manner, or **(b)** run it yourself in a sandbox account where you have admin rights, then point your team at the state file for production promotion.

**DevOps handoff workflow:** Because the corporate AWS account restricts direct IAM and infrastructure creation, the recommended workflow is to commit these Terraform files to your team's infra repository, open a merge request tagged `pipeline-infra`, and let DevOps review, plan, and apply. The Glue Crawler IAM role is flagged below as it requires elevated privileges; the Glue database and crawler resources can typically be applied by a developer role with scoped Glue permissions.

> **Order matters:** Apply these resources in the order listed. The crawler references both the Glue database and the IAM role, so those must exist first. Terraform handles the dependency graph automatically, but if you apply blocks selectively, follow the ordering below.

Before any `resource` blocks, your `.tf` file needs the provider preamble and a `data` source for the pre-existing S3 bucket (provisioned by the [primary pipeline](./aws_snowflake_pipeline_setup.md#1-s3-bucket--folder-prefixes)). This module does **not** create the bucket — it only reads from it.

### Provider

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-2"   # London — must match the primary pipeline
}

# Look up the existing bucket created by the primary pipeline
data "aws_s3_bucket" "coingecko_pipeline" {
  bucket = "coingecko-etl-bucket"   # Must match the primary pipeline's bucket name
}
```

---

### 1. IAM — Glue Crawler Role

Role that allows the Glue Crawler to read S3 and write to the Data Catalog. Uses `glue.amazonaws.com` as the trusted service principal; attaches the managed `AWSGlueServiceRole` policy plus an inline policy for S3 read/write on the pipeline bucket.

> **Console equivalent:** [Step 3.1 — IAM Role for Glue Crawler](#31--iam-role-for-glue-crawler)

```hcl
resource "aws_iam_role" "glue_coingecko_role" {
  name = "coingecko-glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service_coingecko" {
  role       = aws_iam_role.glue_coingecko_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_access_coingecko" {
  name = "glue-coingecko-s3-access"
  role = aws_iam_role.glue_coingecko_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:ListBucket", "s3:PutObject"]
      Resource = [
        data.aws_s3_bucket.coingecko_pipeline.arn,
        "${data.aws_s3_bucket.coingecko_pipeline.arn}/*"
      ]
    }]
  })
}
```

---

### 2. Glue Database

> **Console equivalent:** [Step 2: Glue Database](#step-2-glue-database)

```hcl
resource "aws_glue_catalog_database" "coingecko_db" {
  name = "coingecko_db"
}
```

---

### 3. Glue Crawler

> **Console equivalent:** [Step 3.2 — Create the Crawler](#32--create-the-crawler)

```hcl
resource "aws_glue_crawler" "coingecko_crawler" {
  database_name = aws_glue_catalog_database.coingecko_db.name
  name          = "coingecko_data_crawler"
  role          = aws_iam_role.glue_coingecko_role.arn

  s3_target {
    path = "s3://${data.aws_s3_bucket.coingecko_pipeline.id}/transformed_data/coin_data/"
  }

  s3_target {
    path = "s3://${data.aws_s3_bucket.coingecko_pipeline.id}/transformed_data/market_data/"
  }

  s3_target {
    path = "s3://${data.aws_s3_bucket.coingecko_pipeline.id}/transformed_data/price_data/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "DEPRECATE_IN_DATABASE"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_EVERYTHING"
  }
}
```

---

## Troubleshooting

### Athena Query Returns Zero Rows

**Symptom:** `SELECT * FROM coingecko_db.coin_data LIMIT 10` returns empty results.

**Cause:** Either the S3 LOCATION in the table definition doesn't match the actual S3 path where CSVs live, or no CSVs have been written yet.

**Fix:**
1. Verify CSVs exist: go to **S3 → coingecko-etl-bucket → transformed_data → coin_data/** and confirm `.csv` files are present
2. Verify LOCATION matches: check the table definition in Glue and compare the LOCATION value to the actual S3 path
3. Ensure the trailing `/` is present in the LOCATION — `s3://coingecko-etl-bucket/transformed_data/coin_data/` (not without slash)

---

### Athena "Query has not been saved" or No Database Visible

**Symptom:** Athena query editor shows no databases, or saved queries don't appear.

**Cause:** The Athena workgroup or region doesn't match where the Glue database was created.

**Fix:**
1. Ensure you're in the same AWS region where the Glue database was created
2. Check **Athena → Workgroups** — use the `primary` workgroup unless your org has a custom one
3. Click the database dropdown and confirm `coingecko_db` appears

---

## Key Differences vs Snowflake Pipeline

| Aspect | Snowflake Pipeline | This Pipeline |
|---|---|---|
| Loading trigger | SQS → Snowpipe (event-driven) | Manual crawler run or scheduled |
| Schema management | Defined in Snowflake DDL | Glue Data Catalog (via crawler or Athena DDL) |
| Query engine | Snowflake | Athena (serverless, pay per query) |
| Cost model | Snowflake credits | Athena: $5/TB scanned |
| Data stays in | Snowflake storage | S3 (queried in place) |
| Auto-ingest | Yes (Snowpipe) | No (crawler runs on demand/schedule) |
| Schema evolution | Manual `ALTER TABLE` | Re-crawl or `ALTER TABLE` in Athena |
| Infrastructure required | AWS + Snowflake account | AWS only |
| Table type | Internal + External tables | External tables only (always) |
| Startup cost | Snowflake credits from first query | Athena free tier available |
