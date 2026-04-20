# Codebase Map

Generated: 2026-04-20T15:38:01Z | Files: 54 | Described: 0/54
<!-- gsd:codebase-meta {"generatedAt":"2026-04-20T15:38:01Z","fingerprint":"08262cfc6fe965758981f2d5a6f4a2d3efddeb7d","fileCount":54,"truncated":false} -->

### (root)/
- `.gitignore`
- `pipeline_documentation_style_guide.md`
- `README.md`
- `refactor_documentation_prompt.md`

### docs/
- `docs/console_guide.md`
- `docs/pipeline_guide_refactored.md`

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

### real_time_aws_dbt_architecture/
- `real_time_aws_dbt_architecture/taxi_riders_full_aws_pipeline_setup.md`

### real_time_aws_dbt_architecture/docs/
- `real_time_aws_dbt_architecture/docs/console_guide.md`
- `real_time_aws_dbt_architecture/docs/gap_analysis.md`
- `real_time_aws_dbt_architecture/docs/pipeline_guide_refactored.md`
- `real_time_aws_dbt_architecture/docs/section_1_architecture.md`
- `real_time_aws_dbt_architecture/docs/terraform_section.md`

### real_time_aws_dbt_architecture/docs/dbt/
- `real_time_aws_dbt_architecture/docs/dbt/daily_avg_fare.sql`
- `real_time_aws_dbt_architecture/docs/dbt/no_negative_revenue.sql`
- `real_time_aws_dbt_architecture/docs/dbt/revenue_by_payment.sql`
- `real_time_aws_dbt_architecture/docs/dbt/sources.yml`
- `real_time_aws_dbt_architecture/docs/dbt/top_routes.sql`
- `real_time_aws_dbt_architecture/docs/dbt/total_revenue.sql`
- `real_time_aws_dbt_architecture/docs/dbt/vendor_test.yml`

### real_time_aws_dbt_architecture/docs/diagrams/
- `real_time_aws_dbt_architecture/docs/diagrams/.gitkeep`
- `real_time_aws_dbt_architecture/docs/diagrams/pipeline_architecture.drawio`

### real_time_aws_dbt_architecture/docs/resources/
- `real_time_aws_dbt_architecture/docs/resources/airflow_dag_example.py`
- `real_time_aws_dbt_architecture/docs/resources/emr_spark_job.py`
- `real_time_aws_dbt_architecture/docs/resources/extract_realtime_api_data.py`
- `real_time_aws_dbt_architecture/docs/resources/extract_static_dimensions.py`
- `real_time_aws_dbt_architecture/docs/resources/kafka_producer.py`
- `real_time_aws_dbt_architecture/docs/resources/step_function_and_event_bridge_config.md`

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
