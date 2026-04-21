import json
import boto3
import base64
import time
from datetime import datetime, timezone

# ──────────────────────────────────────────────
# Configuration — adapted for our eu-west-2 deployment
# ──────────────────────────────────────────────
logs_client = boto3.client("logs", region_name="eu-west-2")
sns_client = boto3.client("sns", region_name="eu-west-2")

LOG_GROUP = "/aws/lambda/Logs_to_Cloud_Watch"
LOG_STREAM = "AQI_Logs_Stream"

# ⚠️ Replace <ACCOUNT_ID> with your actual AWS account ID
SNS_TOPIC_ARN = "arn:aws:sns:eu-west-2:<ACCOUNT_ID>:Records_SNS"


def ensure_log_stream():
    """Create log group and stream if they don't already exist."""
    try:
        logs_client.create_log_group(logGroupName=LOG_GROUP)
    except logs_client.exceptions.ResourceAlreadyExistsException:
        pass

    try:
        logs_client.create_log_stream(
            logGroupName=LOG_GROUP, logStreamName=LOG_STREAM
        )
    except logs_client.exceptions.ResourceAlreadyExistsException:
        pass


def lambda_handler(event, context):
    """
    Triggered by Kinesis AQI_Logs stream.
    Reads windowed aggregate records, pushes them to CloudWatch Logs,
    and sends an SNS notification summary.
    """
    ensure_log_stream()

    log_events = []
    record_count = 0

    # Case 1: No Records at all (manual test invocation with empty event)
    if "Records" not in event or not event["Records"]:
        log_events.append({
            "timestamp": int(time.time() * 1000),
            "message": json.dumps({
                "window_end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "record_count": 0
            })
        })
    else:
        # Case 2: Records from Kinesis trigger
        for record in event["Records"]:
            payload = base64.b64decode(record["kinesis"]["data"]).decode("utf-8")
            try:
                data = json.loads(payload)
            except Exception:
                data = {"raw": payload}

            log_events.append({
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(data)
            })
            record_count += 1

    # Push to CloudWatch Logs
    if log_events:
        try:
            logs_client.put_log_events(
                logGroupName=LOG_GROUP,
                logStreamName=LOG_STREAM,
                logEvents=log_events
            )
        except logs_client.exceptions.InvalidSequenceTokenException as e:
            expected = e.response["expectedSequenceToken"]
            logs_client.put_log_events(
                logGroupName=LOG_GROUP,
                logStreamName=LOG_STREAM,
                logEvents=log_events,
                sequenceToken=expected
            )

    # Send SNS summary notification
    message = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "records_received": record_count,
        "log_group": LOG_GROUP,
        "log_stream": LOG_STREAM
    }

    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject="AQI Logs Update",
        Message=json.dumps(message, indent=2)
    )

    return {
        "statusCode": 200,
        "body": f"Pushed {record_count} records to CloudWatch and sent SNS notification"
    }
