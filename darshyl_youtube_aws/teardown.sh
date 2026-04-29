#!/usr/bin/env bash
# YouTube Trending Data Pipeline — AWS teardown
# Account: 946509368226  Region: eu-north-1  Profile: aws-learn
#
# Removes every resource created by the walkthrough in aws_pipeline.md, in safe
# dependency order. Run section-by-section for a cautious teardown, or just
# `bash teardown.sh` to run the lot.
#
# `set -u` is on but `set -e` is NOT — a single "resource already gone" error
# must not abort the rest of the cleanup (the script is idempotent).

set -u

P="--profile aws-learn"
R="--region eu-north-1"
ACC=946509368226

# ─────────────────────────────────────────────────────────────────────
# 1. Stop the pipeline from being triggered (scheduler + state machine)
# ─────────────────────────────────────────────────────────────────────
aws scheduler delete-schedule $P $R --name yt-data-pipeline-12hourly-dev --group-name default

aws stepfunctions delete-state-machine $P $R \
  --state-machine-arn arn:aws:states:eu-north-1:${ACC}:stateMachine:yt-data-pipeline-orchestrator-dev

# ─────────────────────────────────────────────────────────────────────
# 2. Remove the S3 → Lambda trigger BEFORE deleting the Lambda
#    (empty notification config = no triggers)
# ─────────────────────────────────────────────────────────────────────
aws s3api put-bucket-notification-configuration $P \
  --bucket yt-data-pipeline-bronze-${ACC}-dev \
  --notification-configuration '{}'

# ─────────────────────────────────────────────────────────────────────
# 3. Lambda functions (3)
# ─────────────────────────────────────────────────────────────────────
for fn in yt-data-pipeline-json-to-parquet-dev \
          yt-data-pipeline-youtube-ingestion-dev \
          yt-data-pipeline-data-quality-dev; do
  aws lambda delete-function $P $R --function-name "$fn"
done

# ─────────────────────────────────────────────────────────────────────
# 4. Glue — jobs, crawlers, then databases (which cascade-delete tables)
# ─────────────────────────────────────────────────────────────────────
for job in yt-data-pipeline-bronze-to-silver-dev yt-data-pipeline-silver-to-gold-dev; do
  aws glue delete-job $P $R --job-name "$job"
done

for crawler in yt-data-pipeline-bronze-crawler-dev yt-data-pipeline-gold-crawler-dev; do
  aws glue delete-crawler $P $R --name "$crawler"
done

for db in yt_pipeline_bronze_dev yt_pipeline_silver_dev yt_pipeline_gold_dev; do
  aws glue delete-database $P $R --name "$db"
done

# ─────────────────────────────────────────────────────────────────────
# 5. Athena workgroup (recursive = also deletes named/saved queries)
# ─────────────────────────────────────────────────────────────────────
aws athena delete-work-group $P $R --work-group yt-pipeline-dev --recursive-delete-option

# ─────────────────────────────────────────────────────────────────────
# 6. Secrets Manager (--force-delete-without-recovery skips 7-30 day grace)
# ─────────────────────────────────────────────────────────────────────
aws secretsmanager delete-secret $P $R \
  --secret-id yt-data-pipeline/youtube-api-key-dev \
  --force-delete-without-recovery

# ─────────────────────────────────────────────────────────────────────
# 7. SNS (topic delete also removes its subscriptions)
# ─────────────────────────────────────────────────────────────────────
aws sns delete-topic $P $R --topic-arn arn:aws:sns:eu-north-1:${ACC}:yt-data-pipeline-alerts-dev

# ─────────────────────────────────────────────────────────────────────
# 8. IAM roles — must detach/delete policies before delete-role
# ─────────────────────────────────────────────────────────────────────
# Glue role
aws iam delete-role-policy $P --role-name yt-data-pipeline-glue-role-dev --policy-name yt-pipeline-glue-access
aws iam detach-role-policy $P --role-name yt-data-pipeline-glue-role-dev --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole
aws iam delete-role $P --role-name yt-data-pipeline-glue-role-dev

# Lambda role
aws iam delete-role-policy $P --role-name yt-data-pipeline-lambda-role-dev --policy-name yt-pipeline-lambda-access
aws iam delete-role-policy $P --role-name yt-data-pipeline-lambda-role-dev --policy-name yt-pipeline-youtube-secret-read
aws iam detach-role-policy $P --role-name yt-data-pipeline-lambda-role-dev --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam detach-role-policy $P --role-name yt-data-pipeline-lambda-role-dev --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicDurableExecutionRolePolicy
aws iam delete-role $P --role-name yt-data-pipeline-lambda-role-dev

# Scheduler role
aws iam delete-role-policy $P --role-name yt-data-pipeline-scheduler-role-dev --policy-name scheduler-invoke-stepfn-access
aws iam delete-role $P --role-name yt-data-pipeline-scheduler-role-dev

# Step Functions role
aws iam delete-role-policy $P --role-name yt-data-pipeline-step-function-role-dev --policy-name sfn-pipeline-access
aws iam detach-role-policy $P --role-name yt-data-pipeline-step-function-role-dev --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaRole
aws iam delete-role $P --role-name yt-data-pipeline-step-function-role-dev

# ─────────────────────────────────────────────────────────────────────
# 9. S3 buckets — empty then remove (buckets are un-versioned, so simple rm)
# ─────────────────────────────────────────────────────────────────────
# Glue auto-creates aws-glue-assets-<ACCOUNT>-<REGION> the first time a Glue
# job or crawler runs, to store Glue-generated PySpark scripts. It isn't named
# in the walkthrough but it IS left behind. Delete it too.
for b in yt-data-pipeline-bronze-${ACC}-dev \
         yt-data-pipeline-silver-${ACC}-dev \
         yt-data-pipeline-gold-${ACC}-dev \
         yt-data-pipeline-scripts-${ACC}-dev \
         yt-data-pipeline-athena-results-${ACC}-dev \
         aws-glue-assets-${ACC}-eu-north-1; do
  aws s3 rm "s3://$b" --recursive $P 2>/dev/null
  aws s3api delete-bucket $P --bucket "$b" $R 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 10. CloudWatch Log Groups
# ─────────────────────────────────────────────────────────────────────
# Lambda-specific groups — always safe to delete.
for lg in /aws/lambda/yt-data-pipeline-json-to-parquet-dev \
          /aws/lambda/yt-data-pipeline-youtube-ingestion-dev \
          /aws/lambda/yt-data-pipeline-data-quality-dev; do
  aws logs delete-log-group $P $R --log-group-name "$lg"
done

# Glue log groups — ACCOUNT-WIDE. Safe to delete only if this is your only Glue
# workload in account 946509368226. If you have other Glue jobs/crawlers there,
# comment out this loop — the storage cost is minor and they'll keep collecting
# logs from the other workloads.
for lg in /aws-glue/crawlers \
          /aws-glue/jobs/output \
          /aws-glue/jobs/error \
          /aws-glue/jobs/logs-v2 \
          /aws-glue/sessions/error; do
  aws logs delete-log-group $P $R --log-group-name "$lg"
done

echo
echo "Teardown complete. Verify with:"
echo "  aws s3api list-buckets $P --query 'Buckets[?starts_with(Name,\`yt-data-pipeline\`)].Name'"
echo "  aws iam list-roles $P --query 'Roles[?starts_with(RoleName,\`yt-data-pipeline\`)].RoleName'"
echo "  aws lambda list-functions $P $R --query 'Functions[?starts_with(FunctionName,\`yt-data-pipeline\`)].FunctionName'"
