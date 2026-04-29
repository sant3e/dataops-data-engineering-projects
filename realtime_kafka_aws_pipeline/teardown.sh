#!/usr/bin/env bash
# Taxi Riders (Kafka + Step Functions) pipeline — AWS teardown
# Profile: aws-learn   Region: eu-north-1   Account: 946509368226 (substitute yours)
#
# Tears down every resource described in taxi_riders_with_kafka_and_step_functions.md,
# in safe dependency order (triggers first, storage last). Pairs with the walkthrough's
# Step 18: Cleanup section.
#
# Run section-by-section for a cautious teardown, or just `bash teardown.sh` to run
# the lot. `set -u` is on but `set -e` is OFF — a single "resource already gone"
# error must not abort the rest of the cleanup. The script is idempotent.
#
# Before running: substitute <ACCOUNT_ID>, <MSK_CLUSTER_ARN>, <EMR_APPLICATION_ID>,
# <KAFKA_CLIENT_INSTANCE_ID>, <DBT_CLIENT_INSTANCE_ID>, <PIPELINE_BUCKET>,
# <DBT_BUCKET> with your actual values. The walkthrough creates these — retrieve
# them from the relevant AWS console pages or via `aws ... list-*` commands.

set -u

P="--profile aws-learn"
R="--region eu-north-1"
ACC=<ACCOUNT_ID>  # e.g. 946509368226

# ─────────────────────────────────────────────────────────────────────
# 1. Stop the pipeline triggers FIRST (nothing should be firing while we
#    tear things down — an EventBridge rule that fires mid-teardown leaves
#    the Step Function in a half-running state that's harder to kill.)
# ─────────────────────────────────────────────────────────────────────
aws events disable-rule    $P $R --name Refined_bucket_Upload
aws events remove-targets  $P $R --rule Refined_bucket_Upload --ids 1
aws events delete-rule     $P $R --name Refined_bucket_Upload

aws stepfunctions delete-state-machine $P $R \
  --state-machine-arn arn:aws:states:eu-north-1:${ACC}:stateMachine:EMR_Automation

# ─────────────────────────────────────────────────────────────────────
# 2. Stop & delete EMR Serverless (can't delete while STARTED — must stop
#    first, then poll for STOPPED state. Scale-to-zero auto-stop kicks in
#    after 15 min idle, but explicit stop is faster.)
# ─────────────────────────────────────────────────────────────────────
aws emr-serverless stop-application $P $R --application-id <EMR_APPLICATION_ID> 2>/dev/null

until [ "$(aws emr-serverless get-application $P $R --application-id <EMR_APPLICATION_ID> \
  --query 'application.state' --output text 2>/dev/null)" = "STOPPED" ] || \
   [ "$(aws emr-serverless get-application $P $R --application-id <EMR_APPLICATION_ID> \
  --query 'application.state' --output text 2>/dev/null)" = "" ]; do sleep 5; done

aws emr-serverless delete-application $P $R --application-id <EMR_APPLICATION_ID>

# ─────────────────────────────────────────────────────────────────────
# 3. Delete Glue jobs, crawlers, databases
# ─────────────────────────────────────────────────────────────────────
aws glue delete-job      $P $R --job-name RAW_TO_REFINED
aws glue delete-crawler  $P $R --name Business_Data_Crawler
aws glue delete-database $P $R --name athena-db
aws glue delete-database $P $R --name athena_dbt_db

# ─────────────────────────────────────────────────────────────────────
# 4. Delete Firehose + MSK cluster (Firehose FIRST — it consumes from MSK)
# ─────────────────────────────────────────────────────────────────────
aws firehose delete-delivery-stream $P $R --delivery-stream-name MSK_Batch

aws kafka delete-cluster-policy $P $R --cluster-arn <MSK_CLUSTER_ARN>
aws kafka delete-cluster        $P $R --cluster-arn <MSK_CLUSTER_ARN>
# MSK Serverless deletion takes several minutes.

# ─────────────────────────────────────────────────────────────────────
# 5. Terminate EC2 instances + delete key pair
# ─────────────────────────────────────────────────────────────────────
aws ec2 terminate-instances $P $R \
  --instance-ids <KAFKA_CLIENT_INSTANCE_ID> <DBT_CLIENT_INSTANCE_ID>

# Delete the key pair only if you don't want to reuse it for future labs
aws ec2 delete-key-pair $P $R --key-name kafka_access

# ─────────────────────────────────────────────────────────────────────
# 6. Empty and delete S3 buckets (un-versioned = simple rm --recursive)
# ─────────────────────────────────────────────────────────────────────
# Glue auto-creates aws-glue-assets-<ACCOUNT>-<REGION> the first time a Glue
# job runs, to store the generated PySpark script. It is not explicitly named
# in the walkthrough but it IS left behind. Delete it too.
for b in <PIPELINE_BUCKET> <DBT_BUCKET> aws-glue-assets-${ACC}-eu-north-1; do
  aws s3 rm "s3://$b" --recursive $P 2>/dev/null
  aws s3api delete-bucket --bucket "$b" $P $R 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 7. IAM — detach all policies (inline + managed) and delete each role.
#    Uses a helper that auto-discovers everything attached to the role —
#    robust against extra inline policies added during walkthrough debug.
#
#    Firehose, Step Functions, and EMR Execution roles have random suffixes
#    on Console-created variants; we resolve by name prefix.
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
delete_role_fully Kafka_Cluster_Access
delete_role_fully dbt_Athena_Access
delete_role_fully Glue_S3_msk_access
delete_role_fully Glue_Crawler_Role
delete_role_fully EventBridge_StepFunction_Role

# Auto-generated-suffix roles (resolved by name prefix)
delete_role_fully "$(aws iam list-roles $P --query 'Roles[?starts_with(RoleName,`StepFunctions-EMR_Automation`)].RoleName | [0]' --output text)"
delete_role_fully "$(aws iam list-roles $P --query 'Roles[?starts_with(RoleName,`AmazonEMR-ExecutionRole`)].RoleName | [0]' --output text)"
delete_role_fully "$(aws iam list-roles $P --query 'Roles[?starts_with(RoleName,`KinesisFirehoseServiceRole`)].RoleName | [0]' --output text)"

# Customer-managed policies we created standalone (not inline)
aws iam delete-policy $P --policy-arn arn:aws:iam::${ACC}:policy/Access_to_Kafka_Cluster 2>/dev/null
aws iam delete-policy $P --policy-arn arn:aws:iam::${ACC}:policy/dbt_Athena_Access        2>/dev/null
aws iam delete-policy $P --policy-arn arn:aws:iam::${ACC}:policy/PassRole                 2>/dev/null

# ─────────────────────────────────────────────────────────────────────
# 7b. Default VPC security group — revoke any CIDR-based ingress rules
#     we added (e.g. port 9098 from 172.31.0.0/16 or 0.0.0.0/0 for
#     Firehose MSK reachability during walkthrough debugging).
#     Leaves the default self-referencing rule intact.
#
#     Also delete/revoke any EventBridge-managed rule orphaned by the
#     deleted state machine (.sync with EMR Serverless creates one
#     named `StepFunctionsGetEventsForEMRServerlessJobRule`).
# ─────────────────────────────────────────────────────────────────────
DEFAULT_SG=$(aws ec2 describe-security-groups $P $R \
  --filters 'Name=vpc-id,Values='"$(aws ec2 describe-vpcs $P $R --filters 'Name=is-default,Values=true' --query 'Vpcs[0].VpcId' --output text)" \
  'Name=group-name,Values=default' --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
if [ -n "$DEFAULT_SG" ] && [ "$DEFAULT_SG" != "None" ]; then
  # Collect all CIDR-based rule IDs (i.e. NOT self-ref) and revoke them by ID
  for RID in $(aws ec2 describe-security-group-rules $P $R \
    --filters "Name=group-id,Values=$DEFAULT_SG" \
    --query 'SecurityGroupRules[?!ReferencedGroupInfo && IsEgress==`false`].SecurityGroupRuleId' --output text); do
    aws ec2 revoke-security-group-ingress $P $R \
      --group-id "$DEFAULT_SG" --security-group-rule-ids "$RID" 2>/dev/null
  done
fi

# Orphaned managed EventBridge rule created by Step Functions' emr-serverless:*.sync
for RULE in $(aws events list-rules $P $R --query 'Rules[?starts_with(Name,`StepFunctionsGetEventsForEMRServerless`)].Name' --output text); do
  for TID in $(aws events list-targets-by-rule $P $R --rule "$RULE" --query 'Targets[].Id' --output text); do
    aws events remove-targets $P $R --rule "$RULE" --ids "$TID" --force 2>/dev/null
  done
  aws events delete-rule $P $R --name "$RULE" --force 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 8. CloudWatch Log Groups — these keep accruing storage cost until deleted
# ─────────────────────────────────────────────────────────────────────
for lg in \
  /aws/kinesisfirehose/MSK_Batch \
  /aws-glue/jobs/output \
  /aws-glue/jobs/error \
  /aws-glue/jobs/logs-v2 \
  /aws-glue/crawlers \
  /aws/emr-serverless/applications/<EMR_APPLICATION_ID> \
  /aws/vendedlogs/states/EMR_Automation-Logs; do
  aws logs delete-log-group $P $R --log-group-name "$lg" 2>/dev/null
done

# ─────────────────────────────────────────────────────────────────────
# 9. Verification — every query should return empty
# ─────────────────────────────────────────────────────────────────────
echo
echo "=== Teardown verification ==="
echo "Buckets:"      ; aws s3api list-buckets $P --query 'Buckets[?starts_with(Name,`ridestreamlakehouse`) || starts_with(Name,`dbt-athena`)].Name'
echo "MSK clusters:" ; aws kafka list-clusters-v2 $P $R --query 'ClusterInfoList[?starts_with(ClusterName,`MSK`)].ClusterName'
echo "Glue jobs:"    ; aws glue get-jobs $P $R --query 'Jobs[?Name==`RAW_TO_REFINED`].Name'
echo "Crawlers:"     ; aws glue get-crawlers $P $R --query 'Crawlers[?Name==`Business_Data_Crawler`].Name'
echo "State machines:"; aws stepfunctions list-state-machines $P $R --query 'stateMachines[?name==`EMR_Automation`].name'
echo "EMR apps:"     ; aws emr-serverless list-applications $P $R --query 'applications[?name==`EMR_ETL`].name'
echo "Firehose:"     ; aws firehose list-delivery-streams $P $R --query 'DeliveryStreamNames'
echo "EC2:"          ; aws ec2 describe-instances $P $R \
  --filters 'Name=tag:Name,Values=Kafka-Client,dbt-client' \
  --query 'Reservations[].Instances[?State.Name!=`terminated`].InstanceId'
echo
echo "Teardown complete. If you applied via Terraform instead of the Console, run"
echo "\`terraform destroy\` instead of this script — it handles the dependency graph"
echo "automatically and doesn't need placeholder substitution."
