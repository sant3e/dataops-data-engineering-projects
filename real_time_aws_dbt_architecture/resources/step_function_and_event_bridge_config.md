# Step Functions & EventBridge Configuration Template

Templates for automating the EMR Spark job via Step Functions and triggering it via EventBridge.

---

## 1. Step Function — StartJobRun Arguments

Paste this JSON into the **Arguments** section of the `StartJobRun` action in the Step Functions state machine editor.

```json
{
  "ApplicationId": "<EMR_APPLICATION_ID>",
  "Name": "<JOB_NAME>",
  "ExecutionRoleArn": "<EMR_EXECUTION_ROLE_ARN>",
  "JobDriver": {
    "SparkSubmit": {
      "EntryPoint": "s3://<YOUR_BUCKET>/scripts/emr_spark_job.py",
      "EntryPointArguments": [],
      "SparkSubmitParameters": "--conf spark.executor.memory=2g --conf spark.executor.cores=2 --conf spark.driver.memory=2g"
    }
  }
}
```

### Where to find each value

| Placeholder | Where to get it |
|---|---|
| `<EMR_APPLICATION_ID>` | **EMR Console** → **Serverless** → **Applications** → click your application → **Application ID** in the details section (e.g. `00g50u89699vnp1d`) |
| `<JOB_NAME>` | Any descriptive name you choose (e.g. `EMR_Step_Function_job`) |
| `<EMR_EXECUTION_ROLE_ARN>` | **IAM Console** → **Roles** → search for `AmazonEMR-ExecutionRole` → copy the **ARN** (e.g. `arn:aws:iam::<account-id>:role/service-role/AmazonEMR-ExecutionRole-<id>`). This role was auto-created when you first submitted a batch job in EMR Studio and selected "Create new role". |
| `<YOUR_BUCKET>` | Your S3 bucket name (e.g. `ridestreamlakehouse-td`) |

### Spark Parameters Explained

| Parameter | Value | Purpose |
|---|---|---|
| `spark.executor.memory` | `2g` | Memory allocated to each Spark executor (worker) |
| `spark.executor.cores` | `2` | CPU cores per executor |
| `spark.driver.memory` | `2g` | Memory for the Spark driver (orchestrates the job) |

These are conservative values suitable for small datasets. For larger production workloads, increase accordingly.

---

## 2. PassRole IAM Policy

The Step Functions execution role needs permission to **pass** the EMR execution role to EMR Serverless. Without this, Step Functions gets `AccessDenied` when trying to start the job.

Create this as an **inline policy** on the Step Functions execution role, or as a standalone policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "<EMR_EXECUTION_ROLE_ARN>"
        }
    ]
}
```

| Placeholder | Where to get it |
|---|---|
| `<EMR_EXECUTION_ROLE_ARN>` | Same ARN as in section 1 above |

---

## 3. EventBridge Rule — S3 Trigger Pattern

This EventBridge rule triggers the Step Function automatically when new data lands in the `Refined/` folder (i.e. after the Glue RAW_TO_REFINED job completes).

```json
{
  "source": ["aws.s3"],
  "detail-type": ["Object Created"],
  "detail": {
    "bucket": {
      "name": ["<YOUR_BUCKET>"]
    },
    "object": {
      "key": [{
        "prefix": "Refined/"
      }]
    }
  }
}
```

### What each field means

| Field | Value | Purpose |
|---|---|---|
| `source` | `aws.s3` | Only match events emitted by the S3 service |
| `detail-type` | `Object Created` | Only match when a new object is created (not deleted, not modified) |
| `detail.bucket.name` | Your bucket name | Only match events from this specific bucket |
| `detail.object.key.prefix` | `Refined/` | Only match objects whose key starts with `Refined/` — so only refined data triggers the pipeline, not raw uploads or other files |

### Placeholders

| Placeholder | Where to get it |
|---|---|
| `<YOUR_BUCKET>` | Your S3 bucket name (e.g. `ridestreamlakehouse-td`) |

### How this works

```
1. Glue job writes refined CSV to s3://<bucket>/Refined/
2. S3 emits an "Object Created" event to EventBridge
3. EventBridge matches the event against this pattern (bucket name + key prefix)
4. EventBridge triggers the Step Function state machine
5. Step Function starts the EMR Spark job
6. EMR writes star schema Parquet to Business/processed/
```

This creates a fully automated pipeline: raw data → Glue refinement → EMR modelling, with no manual intervention.

### EventBridge IAM Role

EventBridge needs a role to invoke the Step Function. The Console offers to **create a new role** automatically. For production, create a dedicated role:

1. **IAM Console** → **Roles** → **Create role**
2. **Trusted entity:** AWS Service → **EventBridge**
3. **Attach policy:** `AWSStepFunctionsFullAccess` (or a scoped policy allowing `states:StartExecution` on your specific state machine ARN)
4. **Role name:** `EventBridge_StepFunction_Role`
5. Select **Use existing role** in the EventBridge target configuration instead of auto-create
