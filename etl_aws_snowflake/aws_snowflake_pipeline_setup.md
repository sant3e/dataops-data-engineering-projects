<div align="center"><strong style="font-size:2em">CoinGecko ETL Pipeline — AWS & Snowflake Setup Guide</strong></div>


&nbsp;

# Section 1: Architecture

This pipeline ingests cryptocurrency market data from the **CoinGecko API** every 5 minutes, transforms it into normalized CSVs when an S3 event notification triggers the transform Lambda, and loads them into Snowflake automatically via Snowpipe.

The pipeline uses:
- **Amazon S3** — cloud file storage (like a hard drive in the cloud)
- **AWS Lambda** — serverless functions that run code without managing servers
- **Amazon EventBridge Scheduler** — triggers the extract Lambda on a schedule
- **S3 Event Notifications** — triggers the transform Lambda when new JSON files land in S3, and notifies Snowpipe when new CSV files arrive
- **Amazon SQS** — a message queue that bridges AWS and Snowflake
- **Snowpipe** — Snowflake's auto-ingestion service that loads files from S3 into tables

&nbsp;

## Architecture Overview

![S3-to-Snowflake pipeline architecture — API extraction through S3, Lambda, and Snowflake loading](diagrams/s3_to_snowflake_architecture.svg)


&nbsp;

## Data Flow

1. **Lambda** (`coingecko_api_data_extract`) fetches coin data from the CoinGecko API and saves the raw JSON to S3
   - Trigger: **EventBridge Scheduler** every 5 minutes
2. **Lambda** (`coingecko_api_data_transform`) reads the JSON, applies transformations, and splits it into 3 normalized CSVs (idempotent — each file is processed exactly once)
   - Trigger: **S3 Event Notification** when new `.json` files land in `raw_data/to_process/`
3. **Snowpipe** runs `COPY INTO` to load each CSV into the corresponding landing table in Snowflake (`COINGECKO_DB.landing`)
   - Trigger: **SQS** messages sent by a second S3 Event Notification when new `.csv` files land in `transformed_data/`

&nbsp;

## Component-by-Component Walkthrough

**S3 (Simple Storage Service)** — The storage backbone. All data lives in a single bucket (`coingecko-etl-bucket`) organized by prefix — raw JSON from the API, transformed CSVs, and archived files. S3 also generates event notifications that connect the pipeline stages together.

**Lambda** (`coingecko_api_data_extract`) — Calls the CoinGecko public API (free, no key required), fetches the top 50 coins by market cap, and writes the raw JSON response to `s3://coingecko-etl-bucket/raw_data/to_process/`. It uses only built-in Python libraries (`urllib`, `boto3`, `json`), so no Lambda Layers are needed.
- **Trigger:** EventBridge Scheduler — runs every 5 minutes using a `rate(5 minutes)` expression. Can be enabled/disabled from the EventBridge console.

**Lambda** (`coingecko_api_data_transform`) — Reads the raw JSON, applies transformations (symbol uppercase, name title case, market cap tier classification, price-to-ATH ratio, daily price range, volume-to-mcap ratio, days since ATH, extraction timestamp), and splits the data into 3 normalized CSVs written to separate S3 folders — `transformed_data/coin_data/`, `transformed_data/market_data/`, and `transformed_data/price_data/`. After the transformation, it moves the source JSON from `to_process/` to `processed/` (idempotent pipeline — each file is processed exactly once).
- **Trigger:** S3 Event Notification (`lambda-transform-trigger`) — monitors `s3://coingecko-etl-bucket/raw_data/to_process/` for new `.json` files and invokes this function.

**SQS (Simple Queue Service)** — Acts as the bridge between AWS and Snowflake — notifies Snowpipe that new CSV files are ready for loading. The queue ARN is retrieved by running `DESC PIPE` in Snowflake. All three pipes share the same SQS queue.
- **Trigger:** S3 Event Notification (`snowpipe-coingecko-autoload`) — monitors `s3://coingecko-etl-bucket/transformed_data/` for new `.csv` files and sends a message to this queue.

**Snowpipe** — Three pipes (`coin_data_pipe`, `market_data_pipe`, `price_data_pipe`) with `AUTO_INGEST=TRUE`. Each pipe listens on the shared SQS queue and runs `COPY INTO` automatically when new CSVs arrive. Uses `MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE` so CSV header order doesn't matter.

**Snowflake Tables** — Three landing tables in `COINGECKO_DB.landing` receive appended snapshots (APPEND mode). Each pipeline run adds 50 rows per table. Historical data is preserved, enabling time-series analysis via the `extracted_at` column.

&nbsp;

## Services Used

| Service | Role in Pipeline |
|---------|-----------------|
| **S3** (`coingecko-etl-bucket`) | Object storage for raw JSON, transformed CSVs, and archived files |
| **Lambda** (`coingecko_api_data_extract`) | Calls CoinGecko API, writes raw JSON to S3 |
| **EventBridge Scheduler** | Invokes extract Lambda every 5 minutes |
| **Lambda** (`coingecko_api_data_transform`) | Parses JSON, applies transformations, splits into 3 CSVs |
| **S3 Event Notifications** | Triggers transform Lambda on new JSON; notifies Snowpipe SQS on new CSVs |
| **SQS** | Bridge between AWS and Snowflake — notifies Snowpipe that new CSVs are ready for loading |
| **Snowpipe** (3 pipes) | Auto-ingests CSVs from S3 into Snowflake landing tables |
| **Snowflake** (`COINGECKO_DB.landing`) | Data warehouse — 3 landing tables for coin, market, and price data |
| **IAM** (`coingecko_lambda_role`) | Shared execution role for both Lambda functions |
| **CloudWatch Logs** | Automatic logging for Lambda executions |

&nbsp;

## S3 Bucket Structure

```
coingecko-etl-bucket/
├── raw_data/
│   ├── to_process/     ← extract Lambda writes raw JSON here
│   └── processed/      ← transform Lambda moves JSON here after processing
└── transformed_data/
    ├── coin_data/       ← coin identity CSVs
    ├── market_data/     ← market metrics CSVs
    └── price_data/      ← price details CSVs
```

### Why two raw_data folders?
- `to_process/` acts as an inbox — new files land here and trigger the transform Lambda
- `processed/` acts as an archive — files move here after transformation so they are not processed twice

&nbsp;

# Section 2: Step-by-Step AWS Console Guide

This section walks you through creating every **AWS** resource in the pipeline using the AWS Management Console. Each phase builds on the previous one, and most steps include a cross-reference to the equivalent Terraform block in [Section 4](#section-4-terraform-configurations).

> **Scope:** This section covers only AWS resources — S3, IAM, Lambda, EventBridge, and S3 Event Notifications. Snowflake resources (database, schema, tables, pipes, storage integration) are created in Snowsight and are covered in [Section 3](#section-3-snowflake-setup-snowsight).

&nbsp;

## Phase 1: S3 Bucket + Folder Structure

### 1.1 — Create the S3 Bucket

1. Go to **S3 → Create bucket**
2. Bucket name: `coingecko-etl-bucket`
3. Region: **eu-west-2** (must match all other resources)
4. Leave remaining settings as default → Click **Create bucket**

> Terraform: [S3 Bucket + Prefixes](#terraform-s3-bucket--prefixes)

### 1.2 — Create the Folder Prefixes

1. Go to **S3 → `coingecko-etl-bucket`**
2. Create the following folders (use **Create folder** for each):
   - `raw_data/to_process/`
   - `raw_data/processed/`
   - `transformed_data/coin_data/`
   - `transformed_data/market_data/`
   - `transformed_data/price_data/`

> **Note:** S3 has no real folders — these are zero-byte objects that establish the prefixes. The pipeline writes files under these prefixes.

> Terraform: [S3 Bucket + Prefixes](#terraform-s3-bucket--prefixes)

&nbsp;

## Phase 2: IAM Role (coingecko_lambda_role)

Shared execution role for both Lambda functions. Needs S3 read/write on the pipeline bucket and CloudWatch Logs access.

### 2.1 — Create the IAM Role

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **AWS service**
3. Use case: **Lambda**
4. Click **Next**
5. Attach the managed policy: **AWSLambdaBasicExecutionRole** (provides CloudWatch Logs)
6. Click **Next**
7. Role name: `coingecko_lambda_role`
8. Click **Create role**

### 2.2 — Add S3 Access Policy

1. Go to **IAM → Roles → `coingecko_lambda_role`**
2. Click **Add permissions → Create inline policy**
3. Switch to the **JSON** editor
4. Paste the policy from [Terraform: IAM Lambda Role](#terraform-iam-lambda-role) — specifically the `lambda_s3_access` inline policy JSON. It grants `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, and `s3:ListBucket` on `coingecko-etl-bucket`.
5. Policy name: `lambda-s3-coingecko-access`
6. Click **Create policy**

> Terraform: [IAM Lambda Role](#terraform-iam-lambda-role)

&nbsp;

## Phase 3: Lambda Extract Function

### What it does
1. Calls the CoinGecko public API (free, no API key required)
2. Fetches the top 50 cryptocurrencies by market cap
3. Saves the raw API response as a timestamped JSON file in S3

### Output file example
```
s3://coingecko-etl-bucket/raw_data/to_process/coingecko_raw_20260401T112815.json
```

### 3.1 — Create the Lambda Function

1. Go to **Lambda → Create function**
2. **Author from scratch**
3. Function name: `coingecko_api_data_extract`
4. Runtime: **Python 3.12**
5. Execution role: **Use an existing role** → select `coingecko_lambda_role`
6. Click **Create function**
7. In the code editor, paste the contents of `coingeecko_api_data_extract_lambda.py`
8. Click **Deploy**
9. Go to **Configuration → General configuration → Edit**:
   - Timeout: **60 seconds** (default 3s is too short for API calls)
   - Memory: **128 MB** (sufficient)
   - Click **Save**

### Runtime
- **Runtime:** Python 3.12
- **Memory:** 128 MB
- **Timeout:** 60 seconds
- **Execution role:** `coingecko_lambda_role`
- **Source file:** `coingeecko_api_data_extract_lambda.py`
- **Libraries used:** `urllib`, `boto3`, `json` — all built-in, no Lambda Layers needed

### Packaging

The zip must be created before running `terraform apply`. The `handler` value follows the pattern `<filename_without_extension>.lambda_handler`.

**Manual (local):**
```bash
zip coingecko_extract.zip coingeecko_api_data_extract_lambda.py
```

**CI/CD (GitLab example):**
```yaml
build:
  script:
    - zip coingecko_extract.zip coingeecko_api_data_extract_lambda.py
  artifacts:
    paths:
      - coingecko_extract.zip
```

> Terraform: [Lambda Extract + EventBridge](#terraform-lambda-extract--eventbridge)

&nbsp;

## Phase 4: EventBridge Scheduler

The EventBridge Scheduler triggers the extract Lambda every 5 minutes.

### 4.1 — Create the Schedule

1. Go to **EventBridge → Scheduler → Schedules → Create schedule**
2. Name: `coingecko-extract-every-5-minutes`
3. Schedule type: **Rate-based** → `rate(5 minutes)`
4. Flexible time window: **Off**
5. Target: **Lambda** → select `coingecko_api_data_extract`
6. Click **Create schedule**

> **Note:** EventBridge Scheduler needs its own IAM role to invoke Lambda. AWS creates this automatically when you create the schedule via the console. In Terraform, it must be declared explicitly.

> Terraform: [Lambda Extract + EventBridge](#terraform-lambda-extract--eventbridge)

&nbsp;

## Phase 5: Lambda Transform Function

### What it does
1. Lists all `.json` files in `raw_data/to_process/`
2. For each file, reads and parses the JSON
3. Applies transformations (see below)
4. Splits data into 3 normalized CSV files and writes them to S3
5. Moves the original JSON from `to_process/` to `processed/`

### Transformations applied
| Transformation | Description |
|---|---|
| Symbol uppercase | BTC, ETH, etc. |
| Name title case | "bitcoin" → "Bitcoin" |
| Market cap tier | Small (<$1B), Mid ($1-10B), Large ($10-100B), Mega (>$100B) |
| Price-to-ATH ratio | current_price / all_time_high — shows how far from peak (1.0 = at ATH) |
| Daily price range | high_24h - low_24h |
| Volume-to-mcap ratio | total_volume / market_cap — liquidity indicator |
| Days since ATH | Days elapsed since the coin hit its all-time high |
| Extraction timestamp | When the pipeline ran |

### Output files (3 CSVs per run, 50 rows each)

#### coin_data — identity and classification
| Column | Type | Description |
|---|---|---|
| id | VARCHAR | Unique identifier (e.g. "bitcoin") |
| symbol | VARCHAR | Ticker (e.g. "BTC") |
| name | VARCHAR | Full name (e.g. "Bitcoin") |
| market_cap_tier | VARCHAR | Small / Mid / Large / Mega |
| extracted_at | TIMESTAMP | Pipeline run timestamp |

#### market_data — market size and liquidity
| Column | Type | Description |
|---|---|---|
| id | VARCHAR | Join key to coin_data |
| market_cap | NUMBER | Total market cap in USD |
| total_volume | NUMBER | 24h trading volume in USD |
| circulating_supply | NUMBER | Coins in circulation |
| volume_to_mcap_ratio | FLOAT | Liquidity indicator |
| extracted_at | TIMESTAMP | Pipeline run timestamp |

#### price_data — detailed price metrics
| Column | Type | Description |
|---|---|---|
| id | VARCHAR | Join key to coin_data |
| current_price | FLOAT | Current price in USD |
| high_24h | FLOAT | 24h high |
| low_24h | FLOAT | 24h low |
| ath | FLOAT | All-time high price |
| ath_date | TIMESTAMP | Date of all-time high |
| price_change_percentage_24h | FLOAT | % change in 24h |
| price_to_ath_ratio | FLOAT | How close to ATH (1.0 = at ATH) |
| daily_price_range | FLOAT | high_24h - low_24h |
| days_since_ath | INTEGER | Days since all-time high |
| last_updated | TIMESTAMP | CoinGecko last update time |
| extracted_at | TIMESTAMP | Pipeline run timestamp |

### 5.1 — Create the Lambda Function

1. Go to **Lambda → Create function**
2. **Author from scratch**
3. Function name: `coingecko_api_data_transform`
4. Runtime: **Python 3.12**
5. Execution role: **Use an existing role** → select `coingecko_lambda_role`
6. Click **Create function**
7. In the code editor, paste the contents of `coingeecko_api_data_transform_lambda.py`
8. Click **Deploy**
9. Go to **Configuration → General configuration → Edit**:
   - Timeout: **60 seconds**
   - Memory: **128 MB**
   - Click **Save**

### Runtime
- **Runtime:** Python 3.12
- **Memory:** 128 MB
- **Timeout:** 60 seconds
- **Execution role:** `coingecko_lambda_role`
- **Source file:** `coingeecko_api_data_transform_lambda.py`
- **Libraries used:** `json`, `csv`, `boto3`, `io`, `datetime` — all built-in, no Lambda Layers needed

### Trigger: S3 Event Notification
- The transform Lambda is triggered automatically by the `lambda-transform-trigger` S3 event notification (configured in Phase 6)
- After saving the notification in S3, the trigger automatically appears in the Lambda console after a few minutes (AWS propagation delay)

### Packaging

**Manual (local):**
```bash
zip coingecko_transform.zip coingeecko_api_data_transform_lambda.py
```

**CI/CD (GitLab example):**
```yaml
build:
  script:
    - zip coingecko_transform.zip coingeecko_api_data_transform_lambda.py
  artifacts:
    paths:
      - coingecko_transform.zip
```

> Terraform: [Lambda Transform](#terraform-lambda-transform)

&nbsp;

## Phase 6: S3 Event Notifications

Two notifications configured on `coingecko-etl-bucket`:

| Name | Prefix | Suffix | Destination | Purpose |
|---|---|---|---|---|
| `lambda-transform-trigger` | `raw_data/to_process/` | `.json` | Lambda: `coingecko_api_data_transform` | Triggers transformation when raw JSON arrives |
| `snowpipe-coingecko-autoload` | `transformed_data/` | `.csv` | SQS → Snowpipe | Notifies Snowpipe to load new CSVs into Snowflake |

### 6.1 — Set up `lambda-transform-trigger`

**Where:** S3 → `coingecko-etl-bucket` → Properties → Event notifications → Create event notification

| Field | Value | Why |
|---|---|---|
| Name | `lambda-transform-trigger` | Descriptive name |
| Event types | All object create events | Fire on any new file upload |
| Prefix | `raw_data/to_process/` | Only watch the inbox folder, not the whole bucket |
| Suffix | `.json` | Only trigger on JSON files, not CSVs or other files |
| Destination | Lambda function | We want to invoke a Lambda |
| Lambda ARN | `arn:aws:lambda:eu-west-2:<ACCOUNT_ID>:function:coingecko_api_data_transform` | The transform Lambda's ARN — found in Lambda console → function page → top right "Function ARN" |

After saving, this notification automatically appears as a trigger in the Lambda console after a few minutes (AWS propagation delay).

### 6.2 — Set up `snowpipe-coingecko-autoload`

**Where:** S3 → `coingecko-etl-bucket` → Properties → Event notifications → Create event notification

| Field | Value | Why |
|---|---|---|
| Name | `snowpipe-coingecko-autoload` | Descriptive name |
| Event types | All object create events | Fire on any new file upload |
| Prefix | `transformed_data/` | Only watch the transformed output folder |
| Suffix | `.csv` | Only trigger on CSV files |
| Destination | SQS queue | Snowpipe listens to an SQS queue, not Lambda |
| SQS ARN | *(from Snowflake `DESC PIPE` — see below)* | See below |

**Where does the SQS ARN come from?**

The SQS queue is created and managed by **Snowflake** (its AWS account, not yours). You get the ARN by running Step 6 in [`snowflake_setup.sql`](./snowflake_setup.sql):
```sql
DESC PIPE COINGECKO_DB.landing.coin_data_pipe;
```
The `notification_channel` column contains the SQS ARN. All three pipes share the same ARN since Snowflake uses one queue per account.

> **Important:** You must complete Steps 1–6 of [`snowflake_setup.sql`](./snowflake_setup.sql) before configuring this notification, because the SQS ARN comes from the `DESC PIPE` output in Step 6.

### 6.3 — Create the Snowflake S3 Access Role (coingecko_snowflake_role)

This IAM role allows Snowflake's storage integration to read from the S3 bucket. It is referenced in [`snowflake_setup.sql`](./snowflake_setup.sql) Step 2 (`STORAGE_AWS_ROLE_ARN`).

1. Go to **IAM → Roles → Create role**
2. Trusted entity type: **Custom trust policy**
3. Paste the trust policy from [Terraform: IAM Snowflake S3 Role](#terraform-iam-snowflake-s3-role) — it allows Snowflake's IAM user to assume this role using an external ID
4. Click **Next**
5. Do **not** attach any managed policies — the inline policy below provides the access
6. Role name: `coingecko_snowflake_role`
7. Click **Create role**
8. Go to **IAM → Roles → `coingecko_snowflake_role`** → **Add permissions → Create inline policy**
9. Paste the S3 read policy from [Terraform: IAM Snowflake S3 Role](#terraform-iam-snowflake-s3-role) — it grants `s3:GetObject`, `s3:GetObjectVersion`, and `s3:ListBucket` on `coingecko-etl-bucket`
10. Policy name: `snowflake-s3-coingecko-read`
11. Click **Create policy**

> **After creating the role:** Run Step 2 of [`snowflake_setup.sql`](./snowflake_setup.sql) to create the storage integration, then run `DESC INTEGRATION S3_COINGECKO_INTEGRATION;` to get the `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID` values. Update this role's trust policy with those values — replace `<SNOWFLAKE_IAM_USER_ARN>` and `<SNOWFLAKE_EXTERNAL_ID>` with the actual values from Snowflake.

> Terraform: [IAM Snowflake S3 Role](#terraform-iam-snowflake-s3-role)

&nbsp;

### Important notes
- AWS S3 does not allow two notifications with overlapping prefixes — these two use completely separate prefixes so they coexist without conflict
- `lambda-transform-trigger` is created from the **S3 console** and automatically appears in Lambda's trigger list after a few minutes
- `snowpipe-coingecko-autoload` uses a single SQS ARN shared across all 3 Snowpipes — Snowflake routes internally to the correct pipe based on the file path
- Amazon EventBridge notifications are enabled on the bucket (toggled On) but not used for Lambda triggering due to corporate SCP restrictions

### Why EventBridge was not used for the transform trigger
Corporate SCPs (Service Control Policies) blocked `iam:CreateRole` and prevented EventBridge from assuming any role to invoke Lambda. The direct S3 event notification approach bypasses this entirely.

> Terraform: [S3 Event Notifications](#terraform-s3-event-notifications)

### Code Changes & Redeployment

Every time a Lambda source file is modified, the zip must be recreated and Terraform re-applied. Terraform detects the change automatically via `source_code_hash` — if the zip is identical to the previous version, the Lambda is not redeployed.

**Manual workflow:**
```bash
# Re-zip whichever file changed (or both)
zip coingecko_extract.zip coingeecko_api_data_extract_lambda.py
zip coingecko_transform.zip coingeecko_api_data_transform_lambda.py

# Terraform detects the hash change and redeploys only what changed
terraform apply
```

**CI/CD workflow (GitLab):**

Push your code change and the pipeline handles packaging and deployment automatically. No manual zip or apply needed.

```yaml
stages:
  - package
  - deploy

package_lambdas:
  stage: package
  script:
    - zip coingecko_extract.zip coingeecko_api_data_extract_lambda.py
    - zip coingecko_transform.zip coingeecko_api_data_transform_lambda.py
  artifacts:
    paths:
      - coingecko_extract.zip
      - coingecko_transform.zip

terraform_deploy:
  stage: deploy
  script:
    - terraform init
    - terraform apply -auto-approve
  dependencies:
    - package_lambdas
```

> **How Terraform knows when to redeploy:** `source_code_hash = filebase64sha256("file.zip")` computes a hash of the zip on every `terraform plan/apply`. If the hash matches the last deployed version, the Lambda is skipped. If the zip changed, Terraform updates the function code automatically.

> **Alternative — store zips in S3:** For team environments or when multiple CI runners are deploying, push the zip to an S3 artifacts bucket first and reference it via `s3_bucket` / `s3_key` instead of `filename`. This avoids the zip needing to be present on the machine running Terraform.

&nbsp;

# Section 3: Snowflake Setup (Snowsight)

All Snowflake resources — database, schema, role, storage integration, external stage, file format, tables, and Snowpipes — are provisioned via SQL in **Snowsight** (Snowflake's web UI). These are completely separate from the AWS resources in Section 2.

&nbsp;

## Phase 7: Run the Snowflake Setup Script

Open [`snowflake_setup.sql`](./snowflake_setup.sql) in a Snowsight SQL worksheet and run it top to bottom. The script is organized in 9 sequential steps — each builds on the previous one:

| Step | What it creates | Role used |
|---|---|---|
| 1 | Database (`COINGECKO_DB`), schema (`landing`), role (`COINGECKO_DEVELOPER`), grants | `ACCOUNTADMIN` |
| 2 | Storage integration (`S3_COINGECKO_INTEGRATION`) — establishes trust with AWS | `ACCOUNTADMIN` |
| 3 | CSV file format (`ff_csv`) and external stage (`coingecko_stage`) | `COINGECKO_DEVELOPER` |
| 4 | Landing tables — `coin_data`, `market_data`, `price_data` | `COINGECKO_DEVELOPER` |
| 5 | Snowpipes — one per CSV subfolder, `AUTO_INGEST = TRUE` | `COINGECKO_DEVELOPER` |
| 6 | `DESC PIPE` to get the SQS ARN for the S3 event notification | `COINGECKO_DEVELOPER` |
| 7 | Verify pipe status and stage/pipe ownership alignment | `COINGECKO_DEVELOPER` |
| 8 | Force-load files already in S3 (one-time, before `AUTO_INGEST` takes over) | `COINGECKO_DEVELOPER` |
| 9 | Verify data loaded — copy history, row counts, sample join query | `COINGECKO_DEVELOPER` |

The script also includes **Pause** and **Resume** sections at the end for cost management.

> **Prerequisites:** Before starting, you need the S3 bucket (`coingecko-etl-bucket`) from Phase 1 and the `coingecko_snowflake_role` IAM role from [Phase 6.3](#63--create-the-snowflake-s3-access-role-coingecko_snowflake_role) (for the storage integration trust relationship).

> **Circular dependency with Phase 6.2:** The SQS ARN for the `snowpipe-coingecko-autoload` S3 event notification comes from Step 6 of this script (`DESC PIPE`). Complete this script through Step 6, then return to [Phase 6.2](#62--set-up-snowpipe-coingecko-autoload) to configure the notification.

> **Key rule:** All pipes, tables, and stages must be owned by the same role (`COINGECKO_DEVELOPER`). If you accidentally create objects under `ACCOUNTADMIN`, the script includes ownership transfer commands. See the troubleshooting section on [Snowpipe STALLED_COMPILATION_ERROR](#snowpipe-stalled_compilation_error-role-ownership) for details.

### IAM Roles Reference

| Role | Purpose |
|---|---|
| `coingecko_lambda_role` | Shared execution role for both Lambda functions. Needs S3 read/write and CloudWatch Logs. Created in [Phase 2](#phase-2-iam-role-coingecko_lambda_role). |
| `coingecko_snowflake_role` | Used by the Snowflake storage integration to access S3. Created in [Phase 6.3](#63--create-the-snowflake-s3-access-role-coingecko_snowflake_role). |
| Developer role | Your login role via Okta SSO (SAML federation). Cannot be assumed by AWS services. |

### Monitoring: CloudWatch Logs

**Lambda** → select function → **Monitor** tab → **View CloudWatch logs**

**Successful transform run log:**
```
START RequestId: abc123
Processing: raw_data/to_process/coingecko_raw_20260401T083125.json
Written 50 rows to s3://coingecko-etl-bucket/transformed_data/coin_data/coin_data_20260401T083125.csv
Written 50 rows to s3://coingecko-etl-bucket/transformed_data/market_data/market_data_20260401T083125.csv
Written 50 rows to s3://coingecko-etl-bucket/transformed_data/price_data/price_data_20260401T083125.csv
Moved raw_data/to_process/coingecko_raw_20260401T083125.json -> raw_data/processed/coingecko_raw_20260401T083125.json
END RequestId: abc123
REPORT Duration: 760ms
```

&nbsp;

# Section 4: Terraform Configurations

This section provides Terraform configurations that reproduce the AWS infrastructure from [Section 2](#section-2-step-by-step-aws-console-guide). Each block cross-references the console phase it automates.

> **Scope:** Terraform covers only AWS infrastructure. Snowflake objects (database, schema, role, storage integration, stage, file format, tables, pipes) are provisioned via SQL in [Section 3](#section-3-snowflake-setup-snowsight) — not Terraform.

Before any `resource` blocks, your `.tf` file needs the standard provider preamble:

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
  region = "eu-west-2"   # London — must match console guide
}
```

&nbsp;

## Terraform: S3 Bucket + Prefixes

Creates the S3 bucket and all folder prefixes used by the pipeline. Corresponds to **Phase 1** in the console guide.

```hcl
resource "aws_s3_bucket" "coingecko_pipeline" {
  bucket = "coingecko-etl-bucket"
}

# Folder placeholders — S3 has no real folders; zero-byte objects establish the prefixes
resource "aws_s3_object" "raw_to_process"         { bucket = aws_s3_bucket.coingecko_pipeline.id; key = "raw_data/to_process/";          content = "" }
resource "aws_s3_object" "raw_processed"          { bucket = aws_s3_bucket.coingecko_pipeline.id; key = "raw_data/processed/";           content = "" }
resource "aws_s3_object" "transformed_coin_data"  { bucket = aws_s3_bucket.coingecko_pipeline.id; key = "transformed_data/coin_data/";   content = "" }
resource "aws_s3_object" "transformed_market_data"{ bucket = aws_s3_bucket.coingecko_pipeline.id; key = "transformed_data/market_data/"; content = "" }
resource "aws_s3_object" "transformed_price_data" { bucket = aws_s3_bucket.coingecko_pipeline.id; key = "transformed_data/price_data/";  content = "" }
```

&nbsp;

## Terraform: IAM Lambda Role

Creates the shared execution role for both Lambda functions with S3 access and CloudWatch Logs. Corresponds to **Phase 2** in the console guide.

```hcl
resource "aws_iam_role" "lambda_execution_role" {
  name = "coingecko_lambda_role"

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

resource "aws_iam_role_policy" "lambda_s3_access" {
  name = "lambda-s3-coingecko-access"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        "arn:aws:s3:::coingecko-etl-bucket",
        "arn:aws:s3:::coingecko-etl-bucket/*"
      ]
    }]
  })
}
```

&nbsp;

## Terraform: Lambda Extract + EventBridge

Deploys the extract Lambda function and EventBridge Scheduler that triggers it every 5 minutes. Corresponds to **Phase 3 and Phase 4** in the console guide.

```hcl
resource "aws_lambda_function" "coingecko_extract" {
  function_name    = "coingecko_api_data_extract"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "coingeecko_api_data_extract_lambda.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 128
  filename         = "coingecko_extract.zip"
  source_code_hash = filebase64sha256("coingecko_extract.zip")

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.coingecko_pipeline.bucket
    }
  }
}

# EventBridge Scheduler needs its own role to invoke Lambda
resource "aws_iam_role" "eventbridge_scheduler_role" {
  name = "eventbridge-coingecko-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_invoke_lambda" {
  name = "invoke-coingecko-extract-lambda"
  role = aws_iam_role.eventbridge_scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.coingecko_extract.arn
    }]
  })
}

resource "aws_scheduler_schedule" "coingecko_extract" {
  name = "coingecko-extract-every-5-minutes"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(5 minutes)"

  target {
    arn      = aws_lambda_function.coingecko_extract.arn
    role_arn = aws_iam_role.eventbridge_scheduler_role.arn
  }
}
```

&nbsp;

## Terraform: Lambda Transform

Deploys the transform Lambda function and grants S3 permission to invoke it. Corresponds to **Phase 5** in the console guide.

```hcl
resource "aws_lambda_function" "coingecko_transform" {
  function_name    = "coingecko_api_data_transform"
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "coingeecko_api_data_transform_lambda.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 128
  filename         = "coingecko_transform.zip"
  source_code_hash = filebase64sha256("coingecko_transform.zip")

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.coingecko_pipeline.bucket
    }
  }
}

# Allow S3 to invoke the transform Lambda
resource "aws_lambda_permission" "allow_s3_invoke_transform" {
  statement_id  = "AllowS3InvokeTransform"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.coingecko_transform.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.coingecko_pipeline.arn
}
```

&nbsp;

## Terraform: S3 Event Notifications

Both notifications must be declared in a **single** `aws_s3_bucket_notification` resource — AWS replaces the entire notification configuration on each apply, so splitting them into two resources would cause one to overwrite the other. Corresponds to **Phase 6** in the console guide.

```hcl
resource "aws_s3_bucket_notification" "coingecko_pipeline" {
  bucket = aws_s3_bucket.coingecko_pipeline.id

  # Triggers the transform Lambda when a raw JSON file lands in the inbox
  lambda_function {
    id                  = "lambda-transform-trigger"
    lambda_function_arn = aws_lambda_function.coingecko_transform.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw_data/to_process/"
    filter_suffix       = ".json"
  }

  # Notifies Snowpipe via Snowflake-managed SQS when a transformed CSV is ready
  queue {
    id            = "snowpipe-coingecko-autoload"
    queue_arn     = var.snowpipe_sqs_arn  # From Snowflake DESC PIPE output
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "transformed_data/"
    filter_suffix = ".csv"
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke_transform]
}
```

> **Note:** The `snowpipe_sqs_arn` variable value comes from Snowflake — it belongs to Snowflake's AWS account, not yours. Obtain it by running `DESC PIPE COINGECKO_DB.landing.coin_data_pipe;` in Snowflake (Step 6 of [`snowflake_setup.sql`](./snowflake_setup.sql)) and copying the `notification_channel` value. Define the variable in your Terraform configuration:
> ```hcl
> variable "snowpipe_sqs_arn" {
>   description = "SQS ARN from Snowflake DESC PIPE output (notification_channel)"
>   type        = string
> }
> ```

&nbsp;

## Terraform: IAM Snowflake S3 Role

Creates the IAM role that Snowflake assumes (via its storage integration) to read from the S3 bucket. Corresponds to **Phase 6.3** in the console guide.

After applying this Terraform, you must:
1. Create the storage integration in Snowflake (Step 2 of `snowflake_setup.sql`)
2. Run `DESC INTEGRATION S3_COINGECKO_INTEGRATION;` to get the actual Snowflake IAM user ARN and external ID
3. Update the `snowflake_iam_user_arn` and `snowflake_external_id` variables with the real values
4. Run `terraform apply` again to update the trust policy

```hcl
variable "snowflake_iam_user_arn" {
  description = "Snowflake IAM user ARN from DESC INTEGRATION output (STORAGE_AWS_IAM_USER_ARN)"
  type        = string
  default     = "arn:aws:iam::123456789012:user/placeholder"  # Replace after DESC INTEGRATION
}

variable "snowflake_external_id" {
  description = "Snowflake external ID from DESC INTEGRATION output (STORAGE_AWS_EXTERNAL_ID)"
  type        = string
  default     = "placeholder"  # Replace after DESC INTEGRATION
}

resource "aws_iam_role" "snowflake_s3_role" {
  name = "coingecko_snowflake_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.snowflake_iam_user_arn }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "sts:ExternalId" = var.snowflake_external_id
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "snowflake_s3_access" {
  name = "snowflake-s3-coingecko-read"
  role = aws_iam_role.snowflake_s3_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = "arn:aws:s3:::coingecko-etl-bucket/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::coingecko-etl-bucket"
        Condition = {
          StringLike = {
            "s3:prefix" = ["transformed_data/*"]
          }
        }
      }
    ]
  })
}
```

&nbsp;

# Section 5: Troubleshooting

Common issues you may hit during setup, grouped by component. Start with the group that matches the error you're seeing.

&nbsp;

## Lambda Issues

### Lambda timeout / memory

- **Timeout:** Default is 3 seconds — increase to 60 seconds for both functions. The extract Lambda waits on an external API call; the transform Lambda processes up to 50 rows.
- **Memory:** 128 MB is sufficient. If processing larger payloads, increase to 256 MB.
- **Check:** Lambda → function → Configuration → General configuration

### Lambda Access Denied

1. Verify `coingecko_lambda_role` has `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` on `coingecko-etl-bucket`
2. Verify `AWSLambdaBasicExecutionRole` is attached (CloudWatch Logs)
3. Check CloudWatch Logs: **Lambda → function → Monitor → View CloudWatch logs**

&nbsp;

## S3 Event Not Firing

### `lambda-transform-trigger` not invoking transform Lambda

1. Go to **S3 → `coingecko-etl-bucket` → Properties → Event notifications** — verify the notification exists
2. Check the prefix and suffix match exactly: `raw_data/to_process/` and `.json`
3. Verify the Lambda ARN is correct
4. Check if the Lambda resource policy allows S3 to invoke it: **Lambda → function → Configuration → Permissions → Resource-based policy**. If missing, run:
   ```bash
   aws lambda add-permission \
     --function-name coingecko_api_data_transform \
     --statement-id AllowS3InvokeTransform \
     --action lambda:InvokeFunction \
     --principal s3.amazonaws.com \
     --source-arn arn:aws:s3:::coingecko-etl-bucket
   ```
5. After saving the notification in S3, the trigger takes a few minutes to appear in the Lambda console (AWS propagation delay)

### `snowpipe-coingecko-autoload` not notifying Snowpipe

1. Verify the SQS ARN matches what `DESC PIPE` returns in Snowflake
2. Check the prefix and suffix: `transformed_data/` and `.csv`
3. Verify the SQS queue policy allows S3 to send messages (Snowflake configures this automatically)

&nbsp;

## Snowpipe STALLED_COMPILATION_ERROR (Role Ownership)

This is the most common Snowpipe error and is caused by a **role ownership mismatch**.

```sql
SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.coin_data_pipe');
-- {"executionState":"STALLED_COMPILATION_ERROR",...}
```

**Cause:** The pipe owner does not have access to the stage or table. Snowpipe runs `COPY INTO` using the **pipe owner's** privileges, not the caller's.

**Fix:**
1. Ensure the stage, tables, and pipes are all owned by `COINGECKO_DEVELOPER`
2. If tables were created under `ACCOUNTADMIN`, transfer ownership:
   ```sql
   USE ROLE ACCOUNTADMIN;
   GRANT OWNERSHIP ON TABLE COINGECKO_DB.landing.coin_data TO ROLE COINGECKO_DEVELOPER COPY CURRENT GRANTS;
   GRANT OWNERSHIP ON TABLE COINGECKO_DB.landing.market_data TO ROLE COINGECKO_DEVELOPER COPY CURRENT GRANTS;
   GRANT OWNERSHIP ON TABLE COINGECKO_DB.landing.price_data TO ROLE COINGECKO_DEVELOPER COPY CURRENT GRANTS;
   ```
3. Recreate the pipes under `COINGECKO_DEVELOPER` (not `ACCOUNTADMIN`)
4. Verify ownership alignment:
   ```sql
   SHOW STAGES IN SCHEMA COINGECKO_DB.landing;
   SHOW PIPES IN SCHEMA COINGECKO_DB.landing;
   -- Check the "owner" column matches for stages and pipes
   ```

&nbsp;

## Snowpipe STOPPED_MISSING_TABLE

```sql
SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.coin_data_pipe');
-- {"executionState":"STOPPED_MISSING_TABLE",...}
```

**Cause:** The target table does not exist or is not visible to the pipe owner role.

**Fix:**
1. Verify the table exists: `SHOW TABLES IN SCHEMA COINGECKO_DB.landing;`
2. Check the pipe owner has access: `USE ROLE COINGECKO_DEVELOPER; SELECT * FROM COINGECKO_DB.landing.coin_data LIMIT 1;`
3. If the table was dropped and recreated, recreate the pipe (pipe definitions reference table metadata at creation time)

&nbsp;

## EventBridge Not Triggering

### EventBridge schedule not invoking Lambda

1. Go to **EventBridge → Scheduler → Schedules** — verify `coingecko-extract-every-5-minutes` exists and is **Enabled**
2. Check the target Lambda ARN is correct
3. Verify the EventBridge Scheduler role has `lambda:InvokeFunction` permission
4. Check CloudWatch Logs for the extract Lambda — if no logs appear, EventBridge is not invoking it
5. Test manually: **Lambda → `coingecko_api_data_extract` → Test** — if manual test works but EventBridge doesn't, the issue is the scheduler role or schedule configuration
