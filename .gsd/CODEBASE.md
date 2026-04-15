# Codebase Map

Generated: 2026-04-15T13:03:18Z | Files: 29 | Described: 0/29
<!-- gsd:codebase-meta {"generatedAt":"2026-04-15T13:03:18Z","fingerprint":"2f44ce41f49e26a693dc50eebb9973c65726181c","fileCount":29,"truncated":false} -->

### (root)/
- `.gitignore`
- `README.md`

### etl_aws_snowflake/
- `etl_aws_snowflake/aws_snowflake_pipeline_setup.md`
- `etl_aws_snowflake/cdc_workflow.md`
- `etl_aws_snowflake/full_aws_pipeline_setup.md`
- `etl_aws_snowflake/pipeline_documentation_style_guide.md`
- `etl_aws_snowflake/requirements.txt`
- `etl_aws_snowflake/snowflake_setup.sql`

### etl_aws_snowflake/diagrams/
- `etl_aws_snowflake/diagrams/s3_to_glue_architecture.drawio`
- `etl_aws_snowflake/diagrams/s3_to_snowflake_architecture.drawio`

### etl_aws_snowflake/diagrams/overall_architecture/
- `etl_aws_snowflake/diagrams/overall_architecture/coingecko_architecture.drawio`

### etl_aws_snowflake/resources/
- `etl_aws_snowflake/resources/coingecko_etl_local_run.py`
- `etl_aws_snowflake/resources/coingecko_extract.zip`
- `etl_aws_snowflake/resources/coingecko_transform.zip`
- `etl_aws_snowflake/resources/coingeecko_api_data_extract_lambda.py`
- `etl_aws_snowflake/resources/coingeecko_api_data_transform_lambda.py`

### real_time_aws_pipeline/
- `real_time_aws_pipeline/aqi_pipeline_setup.md`

### real_time_aws_pipeline/diagrams/
- `real_time_aws_pipeline/diagrams/firehose_pipeline.drawio`
- `real_time_aws_pipeline/diagrams/flink_architecture.drawio`
- `real_time_aws_pipeline/diagrams/pipeline_architecture.drawio`
- `real_time_aws_pipeline/diagrams/s3_bucket_layout.drawio`

### real_time_aws_pipeline/resources/
- `real_time_aws_pipeline/resources/AQI_Flink_Table .txt`
- `real_time_aws_pipeline/resources/aws_services.md`
- `real_time_aws_pipeline/resources/Flink_to_s3_kinesis.txt`
- `real_time_aws_pipeline/resources/Grafana Query the logs and see visualization.txt`
- `real_time_aws_pipeline/resources/kinesis_to_cloudwatch_lambda.py`
- `real_time_aws_pipeline/resources/openaq_location_6946_measurment.csv`
- `real_time_aws_pipeline/resources/s3_to_kinesis_lambda.py`
- `real_time_aws_pipeline/resources/s3_to_kinesis.py`
