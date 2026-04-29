# DataOps — Data Engineering Projects

Hands-on data engineering projects covering batch and real-time pipelines on AWS with Snowflake.

## Projects

### [AWS Serverless ETL to Snowflake](aws_serverless_etl_to_snowflake/)
Batch ETL pipeline that ingests cryptocurrency market data from the **CoinGecko API** every 5 minutes and transforms it with AWS Lambda. Two loading variants are documented: Snowpipe auto-ingest into Snowflake landing tables, and an AWS-only path that catalogs the transformed CSVs in Glue and queries them with Athena.

**Stack:** Python · Terraform · S3 · Lambda · EventBridge · Glue · Athena · SQS · Snowpipe · Snowflake

### [Realtime Kinesis AWS Pipeline](realtime_kinesis_aws_pipeline/)
Real-time streaming pipeline that processes Air Quality Index data through two parallel workflows — raw archival via Firehose and analytical processing via Apache Flink.

**Stack:** Python · Terraform · S3 · Lambda · Kinesis Data Streams · Firehose · Flink · Glue · Athena · CloudWatch · Grafana

### [Realtime Kafka AWS Pipeline](realtime_kafka_aws_pipeline/)
End-to-end real-time pipeline that ingests NYC taxi ride data via Kafka, delivers to S3 through Firehose, transforms with Glue and EMR Serverless (star schema), catalogs with Athena, and models with dbt. Orchestrated by Step Functions and EventBridge.

**Stack:** Python · Terraform · MSK · Kinesis Firehose · S3 · Glue · EMR Serverless · Athena · Step Functions · EventBridge · dbt · EC2

### [YouTube Trending Data Pipeline (AWS medallion)](darshyl_youtube_aws/)
Serverless medallion-architecture pipeline (Bronze/Silver/Gold) that ingests YouTube Trending data from Kaggle CSVs and the YouTube Data API, transforms it with Glue PySpark ETL, validates with a data-quality Lambda gate, and exposes aggregate analytics via Athena. Orchestrated by Step Functions with EventBridge Scheduler for a daily cron-based trigger.

**Stack:** Python · Terraform · S3 · Lambda · Glue (Crawlers + PySpark ETL + DynamicFrames) · Athena · Step Functions · EventBridge Scheduler · SNS · Secrets Manager
