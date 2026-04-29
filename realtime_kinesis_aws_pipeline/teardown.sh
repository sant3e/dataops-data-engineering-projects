#!/usr/bin/env bash
# AQI Data (Kinesis + Firehose + Flink) pipeline — AWS teardown
# Profile: aws-learn    Region: eu-north-1    Account: <ACCOUNT_ID>  (substitute yours)
#
# Tears down every resource described in aqi_data_with_firehose_and_flink.md,
# in safe dependency order (triggers first, storage last). Pairs with the walkthrough.
#
# Run section-by-section for a cautious teardown, or just `bash teardown.sh` to run
# the lot. `set -u` is on but `set -e` is OFF — a single "resource already gone"
# error must not abort the rest of the cleanup. The script is idempotent.
#
# Before running: substitute <ACCOUNT_ID>, <AWS_PROFILE>, <REGION>, and <PIPELINE_BUCKET>
# with your actual values. The walkthrough creates these — retrieve them from the
# relevant AWS console pages or via `aws ... list-*` commands.

set -u

P="--profile aws-learn"         # <-- change to your profile
R="--region eu-north-1"         # <-- change to your region
ACC=<ACCOUNT_ID>                # e.g. 946509368226

# Discover the pipeline bucket by name prefix (or substitute literal).
PIPELINE_BUCKET=$(aws s3api list-buckets $P \
  --query 'Buckets[?starts_with(Name,`aqi-pipeline-bucket`)].Name | [0]' --output text 2>/dev/null)
[ "$PIPELINE_BUCKET" = "None" ] || [ -z "$PIPELINE_BUCKET" ] && PIPELINE_BUCKET="<PIPELINE_BUCKET>"
echo "Targeting bucket: $PIPELINE_BUCKET"

# ─────────────────────────────────────────────────────────────────────
# 1. Stop the pipeline triggers FIRST — nothing should be firing while
#    we tear things down (a scheduled invocation mid-teardown leaves
#    resources in a half-deleted state).
# ─────────────────────────────────────────────────────────────────────
aws scheduler update-schedule $P $R \
  --name aqi-kinesis-feed \
  --schedule-expression "rate(2 minutes)" \
  --flexible-time-window Mode=OFF \
  --target "Arn=arn:aws:lambda:eu-north-1:${ACC}:function:aqi_s3_to_kinesis,RoleArn=arn:aws:iam::${ACC}:role/aqi_eventbridge_scheduler_role" \
  --state DISABLED 2>/dev/null
aws scheduler delete-schedule $P $R --name aqi-kinesis-feed 2>/dev/null

# Delete the Kinesis→Lambda event-source mapping (monitor trigger)
for UUID in $(aws lambda list-event-source-mappings $P $R \
  --function-name Logs_to_Cloud_Watch \
  --query 'EventSourceMappings[].UUID' --output text 2>/dev/null); do
    aws lambda delete-event-source-mapping $P $R --uuid "$UUID" 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 2. Stop & delete Flink Studio Notebook (can't delete while RUNNING —
#    must stop first, then poll for READY state, then delete).
# ─────────────────────────────────────────────────────────────────────
aws kinesisanalyticsv2 stop-application $P $R \
  --application-name AQI_Analytics --force 2>/dev/null

# Wait up to 3 min for application to reach a deletable state
for _ in $(seq 1 36); do
  STATUS=$(aws kinesisanalyticsv2 describe-application $P $R \
    --application-name AQI_Analytics \
    --query 'ApplicationDetail.ApplicationStatus' --output text 2>/dev/null)
  [ -z "$STATUS" ] || [ "$STATUS" = "None" ] && break
  [ "$STATUS" = "READY" ] && break
  sleep 5
done

CREATE_TS=$(aws kinesisanalyticsv2 describe-application $P $R \
  --application-name AQI_Analytics \
  --query 'ApplicationDetail.CreateTimestamp' --output text 2>/dev/null)
[ -n "$CREATE_TS" ] && [ "$CREATE_TS" != "None" ] && \
  aws kinesisanalyticsv2 delete-application $P $R \
    --application-name AQI_Analytics --create-timestamp "$CREATE_TS" 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# 3. Delete Lambda functions + Firehose + Kinesis streams
#    (Firehose FIRST — it consumes from AQI_Stream)
# ─────────────────────────────────────────────────────────────────────
aws firehose delete-delivery-stream $P $R --delivery-stream-name AQI_Batch 2>/dev/null

aws lambda delete-function $P $R --function-name aqi_s3_to_kinesis 2>/dev/null
aws lambda delete-function $P $R --function-name Logs_to_Cloud_Watch 2>/dev/null

aws kinesis delete-stream $P $R --stream-name AQI_Stream --enforce-consumer-deletion 2>/dev/null
aws kinesis delete-stream $P $R --stream-name AQI_Logs  --enforce-consumer-deletion 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# 4. Delete Glue crawlers + databases
# ─────────────────────────────────────────────────────────────────────
aws glue delete-crawler  $P $R --name Raw_Crawler 2>/dev/null
aws glue delete-crawler  $P $R --name aqi_measurements_crawler 2>/dev/null
aws glue delete-database $P $R --name aqi_db 2>/dev/null
aws glue delete-database $P $R --name aqi_pipeline_db 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# 5. Delete Grafana workspace (if you created one per Step 11)
# ─────────────────────────────────────────────────────────────────────
for WSID in $(aws grafana list-workspaces $P $R \
  --query "workspaces[?name=='AQI_Logs_Dashboard'].id" --output text 2>/dev/null); do
    aws grafana delete-workspace $P $R --workspace-id "$WSID" 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 6. SNS — delete subscriptions (email confirmations create a UUID-suffixed
#    subscription ARN) then the topic itself.
# ─────────────────────────────────────────────────────────────────────
TOPIC_ARN=$(aws sns list-topics $P $R \
  --query 'Topics[?contains(TopicArn,`:Records_SNS`)].TopicArn | [0]' --output text 2>/dev/null)
if [ -n "$TOPIC_ARN" ] && [ "$TOPIC_ARN" != "None" ]; then
  for SUB_ARN in $(aws sns list-subscriptions-by-topic $P $R --topic-arn "$TOPIC_ARN" \
    --query 'Subscriptions[?SubscriptionArn!=`PendingConfirmation`].SubscriptionArn' --output text 2>/dev/null); do
      aws sns unsubscribe $P $R --subscription-arn "$SUB_ARN" 2>/dev/null
  done
  aws sns delete-topic $P $R --topic-arn "$TOPIC_ARN" 2>/dev/null
fi

# ─────────────────────────────────────────────────────────────────────
# 7. CloudWatch Log Groups — keep accruing storage cost until deleted
# ─────────────────────────────────────────────────────────────────────
for lg in \
  /aws/lambda/Logs_to_Cloud_Watch \
  /aws/lambda/aqi_s3_to_kinesis \
  /aws/kinesis-analytics/AQI_Analytics \
  /aws-glue/crawlers; do
    aws logs delete-log-group $P $R --log-group-name "$lg" 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 8. Empty and delete the S3 bucket (un-versioned = simple rm --recursive)
# ─────────────────────────────────────────────────────────────────────
if [ -n "$PIPELINE_BUCKET" ] && [ "$PIPELINE_BUCKET" != "<PIPELINE_BUCKET>" ]; then
  aws s3 rm "s3://$PIPELINE_BUCKET" --recursive $P 2>/dev/null
  aws s3api delete-bucket --bucket "$PIPELINE_BUCKET" $P $R 2>/dev/null
fi

# ─────────────────────────────────────────────────────────────────────
# 9. IAM — detach all policies (inline + managed) and delete each role.
#    Uses a helper that auto-discovers everything attached to the role —
#    robust against extra inline policies added during walkthrough debug.
#
#    Firehose Console-created roles have random suffixes; we resolve by prefix.
# ─────────────────────────────────────────────────────────────────────
delete_role_fully() {
  local role="$1"
  [ -z "$role" ] || [ "$role" = "None" ] && return 0

  # Remove instance-profile membership if any
  for ip in $(aws iam list-instance-profiles-for-role $P --role-name "$role" \
    --query 'InstanceProfiles[].InstanceProfileName' --output text 2>/dev/null); do
      aws iam remove-role-from-instance-profile $P --instance-profile-name "$ip" --role-name "$role" 2>/dev/null
      aws iam delete-instance-profile           $P --instance-profile-name "$ip" 2>/dev/null
  done

  # Delete every inline policy
  for pname in $(aws iam list-role-policies $P --role-name "$role" \
    --query 'PolicyNames' --output text 2>/dev/null); do
      aws iam delete-role-policy $P --role-name "$role" --policy-name "$pname" 2>/dev/null
  done

  # Detach every managed policy
  for parn in $(aws iam list-attached-role-policies $P --role-name "$role" \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
      aws iam detach-role-policy $P --role-name "$role" --policy-arn "$parn" 2>/dev/null
  done

  aws iam delete-role $P --role-name "$role" 2>/dev/null
}

# Named roles (exact names from the walkthrough)
delete_role_fully aqi_lambda_execution_role
delete_role_fully aqi_eventbridge_scheduler_role
delete_role_fully aqi-glue-crawler-role
delete_role_fully kinesis-analytics-AQI_Analytics
delete_role_fully KinesisFirehoseServiceRole-AQI_Batch
delete_role_fully AQI-Grafana-Role

# Console-created Firehose role with random suffix (if that path was used)
delete_role_fully "$(aws iam list-roles $P \
  --query 'Roles[?starts_with(RoleName,`KinesisFirehoseServiceRole-AQI_Batch-`)].RoleName | [0]' --output text)"

# Auto-generated Grafana service role (SERVICE_MANAGED permission type)
delete_role_fully "$(aws iam list-roles $P \
  --query 'Roles[?starts_with(RoleName,`AmazonGrafanaServiceRole-`)].RoleName | [0]' --output text)"

# ─────────────────────────────────────────────────────────────────────
# 10. Verification — every query should return empty
# ─────────────────────────────────────────────────────────────────────
echo
echo "=== Teardown verification ==="
echo "Buckets:"       ; aws s3api list-buckets $P --query 'Buckets[?starts_with(Name,`aqi-pipeline-bucket`)].Name'
echo "Kinesis:"       ; aws kinesis list-streams $P $R --query 'StreamNames[?starts_with(@,`AQI_`)]'
echo "Firehose:"      ; aws firehose list-delivery-streams $P $R --query 'DeliveryStreamNames'
echo "Lambdas:"       ; aws lambda list-functions $P $R --query 'Functions[?contains(FunctionName,`aqi`) || contains(FunctionName,`Logs_to`)].FunctionName'
echo "Glue DBs:"      ; aws glue get-databases $P $R --query 'DatabaseList[?contains(Name,`aqi`)].Name'
echo "Flink apps:"    ; aws kinesisanalyticsv2 list-applications $P $R --query 'ApplicationSummaries[?ApplicationName==`AQI_Analytics`].ApplicationName'
echo "Schedules:"     ; aws scheduler list-schedules $P $R --query 'Schedules[?Name==`aqi-kinesis-feed`].Name'
echo "Log groups:"    ; aws logs describe-log-groups $P $R --log-group-name-prefix /aws/lambda/Logs_to --query 'logGroups[].logGroupName'
echo "SNS topics:"    ; aws sns list-topics $P $R --query 'Topics[?contains(TopicArn,`Records_SNS`)].TopicArn'
echo
echo "Teardown complete. If you applied via Terraform instead of the Console/CLI,"
echo "run \`terraform destroy\` instead of this script — it handles the dependency"
echo "graph automatically and doesn't need placeholder substitution."
