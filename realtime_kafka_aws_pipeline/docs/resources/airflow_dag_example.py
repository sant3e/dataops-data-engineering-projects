import os

from airflow import DAG
from airflow.models import Variable
from airflow.providers.amazon.aws.operators.emr import EmrServerlessStartJobOperator
from airflow.utils.dates import days_ago

# --- Configuration ---
# Values are read from Airflow Variables (preferred) with a fallback to env vars,
# so nothing account-specific or region-specific is hardcoded in source. Set these
# once in Airflow Admin → Variables (or export them in your worker environment):
#
#   EMR_SERVERLESS_APP_ID   — application ID (e.g. 00abc123def456)
#                             aws emr-serverless list-applications \
#                               --query 'applications[?name==`EMR_ETL`].id'
#   JOB_ROLE_ARN            — EMR execution role ARN
#                             arn:aws:iam::<ACCOUNT_ID>:role/<ROLE_NAME>
#   S3_SCRIPT_PATH          — s3://<YOUR_BUCKET>/scripts/emr_spark_job.py
#   S3_OUTPUT_PATH          — s3://<YOUR_BUCKET>/Business/
#   S3_LOGS_PATH            — s3://<YOUR_BUCKET>/emr-logs/
#
# If any required value is missing, the DAG fails fast at parse time.

def _cfg(key: str) -> str:
    value = Variable.get(key, default_var=os.environ.get(key))
    if not value:
        raise ValueError(
            f"Missing configuration: set Airflow Variable or env var {key}. "
            f"See the header comment in this DAG for details."
        )
    return value

EMR_SERVERLESS_APP_ID = _cfg("EMR_SERVERLESS_APP_ID")
JOB_ROLE_ARN          = _cfg("JOB_ROLE_ARN")
S3_SCRIPT_PATH        = _cfg("S3_SCRIPT_PATH")
S3_OUTPUT_PATH        = _cfg("S3_OUTPUT_PATH")
S3_LOGS_PATH          = _cfg("S3_LOGS_PATH")

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
}

with DAG(
    dag_id="emr_serverless_taxi_etl",
    default_args=default_args,
    description="Run EMR Serverless Spark Job for Taxi ETL",
    schedule_interval="@daily",   # set to None for manual-only
    start_date=days_ago(1),
    catchup=False,
    tags=["emr", "spark", "etl"],
) as dag:

    run_emr_etl = EmrServerlessStartJobOperator(
        task_id="run_taxi_etl",
        application_id=EMR_SERVERLESS_APP_ID,
        execution_role_arn=JOB_ROLE_ARN,
        job_driver={
            "sparkSubmit": {
                "entryPoint": S3_SCRIPT_PATH,
                "entryPointArguments": [
                    "--output_path", S3_OUTPUT_PATH,
                ],
            }
        },
        configuration_overrides={
            "monitoringConfiguration": {
                "s3MonitoringConfiguration": {
                    "logUri": S3_LOGS_PATH,
                }
            }
        },
    )

    run_emr_etl
