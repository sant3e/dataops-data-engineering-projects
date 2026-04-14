# DataOps — Data Engineering Projects

Hands-on data engineering projects covering batch and real-time pipelines on AWS with Snowflake.

## Projects

### [ETL Pipeline: AWS & Snowflake](etl_aws_snowflake/)
Batch ETL pipeline that ingests cryptocurrency market data from the **CoinGecko API** every 5 minutes, transforms it with AWS Lambda, and loads it into Snowflake via Snowpipe.

**Stack:** S3 · Lambda · EventBridge · SQS · Snowpipe · Snowflake

### [Real-Time AQI Pipeline](real_time_aws_pipeline/)
Real-time streaming pipeline that processes Air Quality Index data through two parallel workflows — raw archival via Firehose and analytical processing via Apache Flink.

**Stack:** S3 · Lambda · Kinesis Data Streams · Firehose · Flink · Glue · Athena · CloudWatch · Grafana
