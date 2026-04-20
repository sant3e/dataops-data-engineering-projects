# DataOps — Data Engineering Projects

Hands-on data engineering projects covering batch and real-time pipelines on AWS with Snowflake.

## Projects

### [ETL Pipeline: AWS & Snowflake](etl_aws_snowflake/)
Batch ETL pipeline that ingests cryptocurrency market data from the **CoinGecko API** every 5 minutes, transforms it with AWS Lambda, and loads it into Snowflake via Snowpipe.

**Stack:** Python · Terraform · S3 · Lambda · EventBridge · SQS · Snowpipe · Snowflake

### [Real-Time AQI Pipeline](real_time_aws_pipeline/)
Real-time streaming pipeline that processes Air Quality Index data through two parallel workflows — raw archival via Firehose and analytical processing via Apache Flink.

**Stack:** Python · Terraform · S3 · Lambda · Kinesis Data Streams · Firehose · Flink · Glue · Athena · CloudWatch · Grafana

### [Real-Time Ride Data Pipeline](real_time_aws_dbt_architecture/)
End-to-end real-time pipeline that ingests NYC taxi ride data via Kafka, delivers to S3 through Firehose, transforms with Glue and EMR Serverless (star schema), catalogs with Athena, and models with dbt. Orchestrated by Step Functions and EventBridge.

**Stack:** Python · Terraform · MSK · Kinesis Firehose · S3 · Glue · EMR Serverless · Athena · Step Functions · EventBridge · dbt · EC2

**Docs:** [`docs/pipeline_guide_refactored.md`](real_time_aws_dbt_architecture/docs/pipeline_guide_refactored.md) — full setup guide with architecture diagrams, step-by-step console walkthrough, parameterized Terraform, and troubleshooting reference.
