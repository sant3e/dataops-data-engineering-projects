#!/usr/bin/env bash
# CoinGecko ETL (AWS-only / Athena variant) pipeline — AWS teardown
# Profile: aws-learn    Region: eu-north-1    Account: <ACCOUNT_ID>  (substitute yours)
#
# Tears down every resource described in crypto_data_aws_to_snowpipe_ingestion.md
# (AWS components only — skipping Snowflake-specific resources) and
# crypto_data_aws_to_athena_ingestion.md, in safe dependency order.
#
# Run section-by-section for a cautious teardown, or just `bash teardown.sh` to run
# the lot. `set -u` is on but `set -e` is OFF — a single "resource already gone"
# error must not abort the rest of the cleanup. The script is idempotent.
#
# Before running: substitute <ACCOUNT_ID>, <AWS_PROFILE>, <REGION>, and <PIPELINE_BUCKET>
# with your actual values. The walkthroughs create these — retrieve them via
# `aws ... list-*` commands.
#
# If you ALSO provisioned Snowflake-side resources (the Snowpipe variant), this script
# will additionally clean up `coingecko_snowflake_role`. Snowflake objects (database,
# schema, pipe, storage integration) must be dropped via SQL in Snowsight separately.

set -u

P="--profile aws-learn"          # <-- change to your profile
R="--region eu-north-1"          # <-- change to your region
ACC=<ACCOUNT_ID>                 # e.g. 946509368226

# Discover the pipeline bucket by name prefix.
PIPELINE_BUCKET=$(aws s3api list-buckets $P \
  --query 'Buckets[?starts_with(Name,`coingecko-etl-bucket`)].Name | [0]' --output text 2>/dev/null)
[ "$PIPELINE_BUCKET" = "None" ] || [ -z "$PIPELINE_BUCKET" ] && PIPELINE_BUCKET="<PIPELINE_BUCKET>"
echo "Targeting bucket: $PIPELINE_BUCKET"

# ─────────────────────────────────────────────────────────────────────
# 1. Stop the pipeline triggers FIRST — nothing should fire while tearing down.
# ─────────────────────────────────────────────────────────────────────
aws scheduler update-schedule $P $R \
  --name coingecko-extract-every-5-minutes \
  --schedule-expression "rate(5 minutes)" \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "{\"Arn\":\"arn:aws:lambda:eu-north-1:${ACC}:function:coingecko_api_data_extract\",\"RoleArn\":\"arn:aws:iam::${ACC}:role/coingecko-scheduler-invoke-role\"}" \
  --state DISABLED 2>/dev/null
aws scheduler delete-schedule $P $R --name coingecko-extract-every-5-minutes 2>/dev/null

# Remove the S3 → Lambda notification config (removes all notifications on the bucket)
if [ -n "$PIPELINE_BUCKET" ] && [ "$PIPELINE_BUCKET" != "<PIPELINE_BUCKET>" ]; then
  aws s3api put-bucket-notification-configuration \
    --bucket "$PIPELINE_BUCKET" \
    --notification-configuration '{}' \
    $P 2>/dev/null
fi

# ─────────────────────────────────────────────────────────────────────
# 2. Delete Lambda functions (the associated Lambda permission + event source
#    mappings are removed with the function automatically).
# ─────────────────────────────────────────────────────────────────────
aws lambda delete-function $P $R --function-name coingecko_api_data_extract 2>/dev/null
aws lambda delete-function $P $R --function-name coingecko_api_data_transform 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# 3. Delete Glue Crawler (if created) + Glue Database + tables.
#    Deleting the database removes its tables automatically.
# ─────────────────────────────────────────────────────────────────────
aws glue delete-crawler  $P $R --name coingecko_data_crawler 2>/dev/null
aws glue delete-database $P $R --name coingecko_db 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# 4. CloudWatch Log Groups — keep accruing storage cost until deleted.
# ─────────────────────────────────────────────────────────────────────
for lg in \
  /aws/lambda/coingecko_api_data_extract \
  /aws/lambda/coingecko_api_data_transform; do
    aws logs delete-log-group $P $R --log-group-name "$lg" 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 5. Empty and delete the S3 bucket (un-versioned = simple rm --recursive).
#    Also flushes Athena query results in athena-results/.
# ─────────────────────────────────────────────────────────────────────
if [ -n "$PIPELINE_BUCKET" ] && [ "$PIPELINE_BUCKET" != "<PIPELINE_BUCKET>" ]; then
  aws s3 rm "s3://$PIPELINE_BUCKET" --recursive $P 2>/dev/null
  aws s3api delete-bucket --bucket "$PIPELINE_BUCKET" $P $R 2>/dev/null
fi

# ─────────────────────────────────────────────────────────────────────
# 6. IAM — detach all policies (inline + managed) and delete each role.
# ─────────────────────────────────────────────────────────────────────
delete_role_fully() {
  local role="$1"
  [ -z "$role" ] || [ "$role" = "None" ] && return 0

  for ip in $(aws iam list-instance-profiles-for-role $P --role-name "$role" \
    --query 'InstanceProfiles[].InstanceProfileName' --output text 2>/dev/null); do
      aws iam remove-role-from-instance-profile $P --instance-profile-name "$ip" --role-name "$role" 2>/dev/null
      aws iam delete-instance-profile           $P --instance-profile-name "$ip" 2>/dev/null
  done

  for pname in $(aws iam list-role-policies $P --role-name "$role" \
    --query 'PolicyNames' --output text 2>/dev/null); do
      aws iam delete-role-policy $P --role-name "$role" --policy-name "$pname" 2>/dev/null
  done

  for parn in $(aws iam list-attached-role-policies $P --role-name "$role" \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
      aws iam detach-role-policy $P --role-name "$role" --policy-arn "$parn" 2>/dev/null
  done

  aws iam delete-role $P --role-name "$role" 2>/dev/null
}

# Named roles from the walkthroughs
delete_role_fully coingecko_lambda_role
delete_role_fully coingecko-scheduler-invoke-role
delete_role_fully coingecko-glue-crawler-role
# Snowflake-only (only created if you ran the Snowpipe path)
delete_role_fully coingecko_snowflake_role

# ─────────────────────────────────────────────────────────────────────
# 7. Verification — every query should return empty.
# ─────────────────────────────────────────────────────────────────────
echo
echo "=== Teardown verification ==="
echo "Buckets:"       ; aws s3api list-buckets $P --query 'Buckets[?starts_with(Name,`coingecko-etl-bucket`)].Name'
echo "Lambdas:"       ; aws lambda list-functions $P $R --query 'Functions[?contains(FunctionName,`coingecko`)].FunctionName'
echo "Glue DBs:"      ; aws glue get-databases $P $R --query 'DatabaseList[?contains(Name,`coingecko`)].Name'
echo "Crawlers:"      ; aws glue get-crawlers $P $R --query 'Crawlers[?contains(Name,`coingecko`)].Name'
echo "Schedules:"     ; aws scheduler list-schedules $P $R --query 'Schedules[?contains(Name,`coingecko`)].Name'
echo "Log groups:"    ; aws logs describe-log-groups $P $R --log-group-name-prefix /aws/lambda/coingecko --query 'logGroups[].logGroupName'
echo "IAM roles:"     ; aws iam list-roles $P --query 'Roles[?contains(RoleName,`coingecko`)].RoleName'
echo
echo "Teardown complete. If you applied via Terraform instead of the Console/CLI,"
echo "run \`terraform destroy\` instead of this script."
echo
echo "Note: If you ran the Snowpipe variant, Snowflake objects (database, pipes,"
echo "storage integration) must be dropped via SQL in Snowsight separately —"
echo "this script only tears down AWS resources."
