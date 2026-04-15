# Existing IAM Roles Available for This Project

Discovered from AWS account `025044153839` (cbap-aws-dev). Only roles with `darshyl`/`darshil` in the name — created for prior training projects.

All roles have access to **`darshyl-snowflake-bucket`** (eu-west-2).

---

## Reusable for This Project

### `snowflake_darshyl_lambda_role`

**Trust:** `lambda.amazonaws.com`
**Use for:** Any Lambda functions in this pipeline (e.g., Kafka producer if EC2 is blocked)

| Policy | Type | What It Grants |
|--------|------|----------------|
| `AWSLambdaBasicExecutionRole` | Managed | CloudWatch Logs for Lambda |
| `snowflake-darshyl-lambda-s3-access-policy-dev` | Managed | Full R/W on `darshyl-snowflake-bucket` |
| `lambda-s3-coingecko-access` | Inline | S3 Get/Put/Delete/List/Copy on `darshyl-snowflake-bucket` |
| `lambda-kinesis-aqi-access-darshil` | Inline | Kinesis PutRecord/PutRecords on `AQI_Stream` (AQI project) |
| `lambda-cloudwatch-sns-aqi-access-darshyl` | Inline | Kinesis read on `AQI_Logs`, CloudWatch Logs write, SNS publish (AQI project) |

> **Note:** The AQI-specific inline policies are harmless — they grant access to AQI resources that won't conflict. If new Kinesis streams or CloudWatch log groups are needed for this project, add new inline policies.

---

### `glue-coingecko-crawler-role-darshil`

**Trust:** `glue.amazonaws.com`
**Use for:** Glue Crawler to catalog processed Parquet files in S3

| Policy | Type | What It Grants |
|--------|------|----------------|
| `AWSGlueServiceRole` | Managed | Glue Data Catalog read/write, CloudWatch Logs |
| `glue-coingecko-s3-access-darshil` | Inline | S3 Get/List/Put on `darshyl-snowflake-bucket` |

> **Note:** Already scoped to the same bucket this project uses. No changes needed unless the crawler needs access to additional buckets.

---

## Not Needed for This Project

### `snowflake_darshyl_role`

**Trust:** Snowflake external ID (cross-account)
**Purpose:** Allows Snowflake storage integration to read from S3. Not relevant for this pipeline.

### `kinesis-analytics-AQI_Analytics-us-east-1_darshil`

**Trust:** `kinesisanalytics.amazonaws.com`
**Purpose:** Flink Studio Notebook for AQI project. Not relevant (this project uses EMR, not Flink).

---

## New Roles Needed (Request from DevOps)

### EMR Serverless Execution Role

**Trust:** `emr-serverless.amazonaws.com`
**Needs:** S3 read/write on `darshyl-snowflake-bucket`, Glue Catalog access, CloudWatch Logs

### Step Functions Execution Role

**Trust:** `states.amazonaws.com`
**Needs:** `emr-serverless:StartJobRun`, `emr-serverless:GetJobRun`, `emr-serverless:CancelJobRun`, `iam:PassRole` for the EMR execution role, S3 read, EventBridge rule management

### Firehose Service Role

**Trust:** `firehose.amazonaws.com`
**Needs:** MSK read (Connect, DescribeTopic, ReadData), S3 write on `darshyl-snowflake-bucket`
**Note:** AWS may auto-create this when you create the Firehose stream via console (like in the AQI project). If so, just verify the auto-created role has the right permissions.

### MSK-Related Permissions

**Needs:** EC2 instance (or Lambda) needs `kafka-cluster:Connect`, `kafka-cluster:CreateTopic`, `kafka-cluster:WriteData`, `kafka-cluster:ReadData`, `kafka-cluster:DescribeTopic` on the MSK cluster. If using Lambda, add as inline policy on `snowflake_darshyl_lambda_role`. If using EC2, the instance profile role needs these permissions.
