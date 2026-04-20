## Terraform — All Resources

This section provides production-ready Terraform HCL for every AWS resource in the pipeline. In a corporate environment where developers lack Console permissions, hand these blocks to your DevOps or infrastructure team to provision the full stack. Note that interactive steps — Kafka library installation on EC2, dbt CLI setup, and manual script uploads — are not covered here and must be performed via the Console or SSH as described in the walkthrough sections above.

```hcl
variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-north-1"
}
```

### Provider

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.region
}
```

### 1. VPC + Networking

> Console: [Phase 1: Create the MSK Cluster](#phase-1-create-the-msk-cluster)

```hcl
resource "aws_vpc" "vpc_kafka" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "VPC_Kafka" }
}

resource "aws_subnet" "msk_subnet_a" {
  vpc_id            = aws_vpc.vpc_kafka.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "${var.region}a"
  tags = { Name = "msk_subnet_a" }
}

resource "aws_subnet" "msk_subnet_b" {
  vpc_id            = aws_vpc.vpc_kafka.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "${var.region}b"
  tags = { Name = "msk_subnet_b" }
}

resource "aws_security_group" "msk_sg" {
  name        = "msk_sg"
  description = "Security group for MSK Serverless and EC2"
  vpc_id      = aws_vpc.vpc_kafka.id

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["10.0.0.0/16"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "msk_sg" }
}

resource "aws_security_group" "ec2_sg" {
  name        = "ec2_sg"
  description = "SSH and HTTP access for Kafka client EC2"
  vpc_id      = aws_vpc.vpc_kafka.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "ec2_sg" }
}
```

### 2. EC2 Key Pair

> Console: [Phase 2: Create EC2 Instance (Kafka Client)](#phase-2-create-ec2-instance-kafka-client)

```hcl
resource "tls_private_key" "kafka_access" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "kafka_access" {
  key_name   = "kafka_access"
  public_key = tls_private_key.kafka_access.public_key_openssh
  tags = { Name = "kafka_access" }
}

output "kafka_private_key" {
  value     = tls_private_key.kafka_access.private_key_pem
  sensitive = true
}
```

### 3. S3 Bucket

> Console: [Phase 7: Create S3 Bucket and Firehose Stream](#phase-7-create-s3-bucket-and-firehose-stream-msk-s3)

```hcl
resource "aws_s3_bucket" "pipeline_bucket" {
  bucket = "ridestreamlakehouse-<UNIQUE_SUFFIX>"
  tags   = { Name = "ridestreamlakehouse-<UNIQUE_SUFFIX>" }
}

resource "aws_s3_object" "refined_folder" {
  bucket = aws_s3_bucket.pipeline_bucket.id
  key    = "Refined/"
}

resource "aws_s3_object" "business_folder" {
  bucket = aws_s3_bucket.pipeline_bucket.id
  key    = "Business/"
}

resource "aws_s3_object" "scripts_folder" {
  bucket = aws_s3_bucket.pipeline_bucket.id
  key    = "scripts/"
}

resource "aws_s3_object" "athena_results_folder" {
  bucket = aws_s3_bucket.pipeline_bucket.id
  key    = "athena-results/"
}
```

### 4. MSK Serverless Cluster

> Console: [Phase 1: Create the MSK Cluster](#phase-1-create-the-msk-cluster)

```hcl
resource "aws_msk_serverless_cluster" "msk" {
  cluster_name = "MSK"

  vpc_config {
    subnet_ids         = [aws_subnet.msk_subnet_a.id, aws_subnet.msk_subnet_b.id]
    security_group_ids = [aws_security_group.msk_sg.id]
  }

  client_authentication {
    sasl {
      iam {
        enabled = true
      }
    }
  }

  tags = { Name = "MSK" }
}
```

### 5. EC2 Instance (Kafka Client)

> Console: [Phase 2: Create EC2 Instance (Kafka Client)](#phase-2-create-ec2-instance-kafka-client)

```hcl
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "kafka_client" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.kafka_access.key_name
  subnet_id              = aws_subnet.msk_subnet_a.id
  vpc_security_group_ids = [aws_security_group.msk_sg.id, aws_security_group.ec2_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.kafka_instance_profile.name

  root_block_device {
    volume_size = 8
  }

  tags = { Name = "Kafka-Client" }
}
```

### 6. IAM — EC2 → MSK Access

> Console: [Phase 4: IAM Policy and Role for EC2 → MSK Access](#phase-4-iam-policy-and-role-for-ec2-msk-access)

```hcl
resource "aws_iam_policy" "access_to_kafka_cluster" {
  name        = "Access_to_Kafka_Cluster"
  description = "Allows EC2 to connect to MSK cluster and manage Kafka topics"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kafka-cluster:CreateTopic", "kafka-cluster:WriteData", "kafka-cluster:ReadData", "kafka-cluster:DescribeTopic"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kafka-cluster:DescribeGroup", "kafka-cluster:AlterGroup", "kafka-cluster:ReadData"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role" "kafka_cluster_access" {
  name = "Kafka_Cluster_Access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "kafka_policy_attach" {
  role       = aws_iam_role.kafka_cluster_access.name
  policy_arn = aws_iam_policy.access_to_kafka_cluster.arn
}

resource "aws_iam_instance_profile" "kafka_instance_profile" {
  name = "Kafka_Cluster_Access"
  role = aws_iam_role.kafka_cluster_access.name
}
```

### 7. IAM + Firehose Stream

> Console: [Phase 7: Create S3 Bucket and Firehose Stream](#phase-7-create-s3-bucket-and-firehose-stream-msk-s3)

```hcl
resource "aws_iam_role" "firehose_role" {
  name = "KinesisFirehoseServiceRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "firehose_s3" {
  role       = aws_iam_role.firehose_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "firehose_msk" {
  role       = aws_iam_role.firehose_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonMSKFullAccess"
}

resource "aws_kinesis_firehose_delivery_stream" "msk_batch" {
  name        = "MSK_Batch"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_role.arn
    bucket_arn = aws_s3_bucket.pipeline_bucket.arn
    buffering_size     = 5
    buffering_interval = 300
  }

  msk_source_configuration {
    authentication_configuration {
      connectivity = "PRIVATE"
      role_arn     = aws_iam_role.firehose_role.arn
    }
    msk_cluster_arn = aws_msk_serverless_cluster.msk.arn
    topic_name      = "realtimeridedata"
  }
}
```

### 8. IAM + Glue ETL Job

> Console: [Phase 8: AWS Glue — Transform Raw Data to Refined](#phase-8-aws-glue-transform-raw-data-to-refined)

```hcl
resource "aws_iam_role" "glue_etl_role" {
  name = "Glue_S3_msk_access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_etl_s3" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "glue_etl_console" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSGlueConsoleFullAccess"
}

resource "aws_iam_role_policy_attachment" "glue_etl_service" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.pipeline_bucket.id
  key    = "scripts/RAW_TO_REFINED.py"
  source = "${path.module}/scripts/RAW_TO_REFINED.py"
  etag   = filemd5("${path.module}/scripts/RAW_TO_REFINED.py")
}

resource "aws_glue_job" "raw_to_refined" {
  name     = "RAW_TO_REFINED"
  role_arn = aws_iam_role.glue_etl_role.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.pipeline_bucket.id}/scripts/RAW_TO_REFINED.py"
    python_version  = "3"
  }

  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  max_retries       = 0
  timeout           = 480
}
```

### 9. EMR Serverless

> Console: [Phase 9: EMR Serverless — Dimensional Modelling](#phase-9-emr-serverless-dimensional-modelling-star-schema)

```hcl
resource "aws_s3_object" "emr_script" {
  bucket = aws_s3_bucket.pipeline_bucket.id
  key    = "scripts/emr_spark_job.py"
  source = "${path.module}/scripts/emr_spark_job.py"
  etag   = filemd5("${path.module}/scripts/emr_spark_job.py")
}

resource "aws_emrserverless_application" "emr_etl" {
  name          = "EMR_ETL"
  release_label = "emr-7.7.0"
  type          = "SPARK"

  tags = { Name = "EMR_ETL" }
}
```

> **Note:** EMR Serverless job runs are submitted via CLI or Step Functions, not Terraform. Terraform creates the application; job submission is orchestrated separately.

### 10. IAM + Glue Crawler + Glue Database

> Console: [Phase 10: Glue Crawler and Athena — Catalog and Query](#phase-10-glue-crawler-and-athena-catalog-and-query)

```hcl
resource "aws_iam_role" "glue_crawler_role" {
  name = "Glue_Crawler_Role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "crawler_service" {
  role       = aws_iam_role.glue_crawler_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy_attachment" "crawler_s3" {
  role       = aws_iam_role.glue_crawler_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_glue_catalog_database" "athena_db" {
  name = "athena-db"
}

resource "aws_glue_crawler" "business_crawler" {
  name          = "Business_Data_Crawler"
  role          = aws_iam_role.glue_crawler_role.arn
  database_name = aws_glue_catalog_database.athena_db.name

  s3_target {
    path = "s3://${aws_s3_bucket.pipeline_bucket.id}/Business/processed/"
  }
}
```

### 11. Step Functions State Machine

> Console: [Phase 11: Step Functions — Automate the EMR Spark Job](#phase-11-step-functions-automate-the-emr-spark-job)

```hcl
# --- IAM Role for Step Functions ---
resource "aws_iam_role" "step_functions_role" {
  name = "StepFunctions-EMR_Automation"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# PassRole — allows Step Functions to pass the EMR execution role to EMR Serverless
resource "aws_iam_policy" "pass_role" {
  name = "PassRole"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "iam:PassRole"
      Resource = aws_iam_role.emr_execution_role.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sfn_pass_role" {
  role       = aws_iam_role.step_functions_role.name
  policy_arn = aws_iam_policy.pass_role.arn
}

resource "aws_iam_role_policy_attachment" "sfn_emr_full" {
  role       = aws_iam_role.step_functions_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEMRFullAccessPolicy_v2"
}

# --- EMR Execution Role (if not auto-created via Console) ---
resource "aws_iam_role" "emr_execution_role" {
  name = "AmazonEMR-ExecutionRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "ServerlessTrustPolicy"
      Effect    = "Allow"
      Principal = { Service = "emr-serverless.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringLike = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          "aws:SourceArn"     = "arn:aws:emr-serverless:${var.region}:${data.aws_caller_identity.current.account_id}:/applications/*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "emr_exec_s3" {
  role       = aws_iam_role.emr_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "emr_exec_glue" {
  role       = aws_iam_role.emr_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSGlueConsoleFullAccess"
}

data "aws_caller_identity" "current" {}

# --- State Machine ---
resource "aws_sfn_state_machine" "emr_automation" {
  name     = "EMR_Automation"
  role_arn = aws_iam_role.step_functions_role.arn

  definition = jsonencode({
    Comment = "Triggers EMR Spark job for dimensional modelling"
    StartAt = "StartJobRun"
    States = {
      StartJobRun = {
        Type     = "Task"
        Resource = "arn:aws:states:::emr-serverless:startJobRun.sync"
        Parameters = {
          "ApplicationId" = aws_emrserverless_application.emr_etl.id
          "Name"          = "EMR_Step_Function_job"
          "ExecutionRoleArn" = aws_iam_role.emr_execution_role.arn
          "JobDriver" = {
            "SparkSubmit" = {
              "EntryPoint"            = "s3://${aws_s3_bucket.pipeline_bucket.id}/scripts/emr_spark_job.py"
              "EntryPointArguments"   = []
              "SparkSubmitParameters" = "--conf spark.executor.memory=2g --conf spark.executor.cores=2 --conf spark.driver.memory=2g"
            }
          }
        }
        End = true
      }
    }
  })
}
```

> **Note on EMR Execution Role trust policy:** The `aws:SourceArn` condition uses a wildcard (`/applications/*`) instead of a specific application ID. This prevents the trust policy from breaking if the EMR application is recreated. In a locked-down production environment, scope this to the specific application ARN.

### 12. EventBridge Rule

> Console: [Phase 12: EventBridge — Automate the Full Pipeline](#phase-12-eventbridge-automate-the-full-pipeline)

```hcl
# --- IAM Role for EventBridge ---
resource "aws_iam_role" "eventbridge_sfn_role" {
  name = "EventBridge_StepFunction_Role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_invoke_sfn" {
  name = "InvokeStepFunction"
  role = aws_iam_role.eventbridge_sfn_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.emr_automation.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eventbridge_s3" {
  role       = aws_iam_role.eventbridge_sfn_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

# --- Enable EventBridge notifications on the S3 bucket ---
resource "aws_s3_bucket_notification" "eventbridge_notification" {
  bucket      = aws_s3_bucket.pipeline_bucket.id
  eventbridge = true
}

# --- EventBridge Rule ---
resource "aws_cloudwatch_event_rule" "refined_upload" {
  name        = "Refined_bucket_Upload"
  description = "Triggers EMR automation when new refined data lands in S3"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = {
        name = [aws_s3_bucket.pipeline_bucket.id]
      }
      object = {
        key = [{
          prefix = "Refined/"
        }]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "sfn_target" {
  rule      = aws_cloudwatch_event_rule.refined_upload.name
  target_id = "EMR_Automation"
  arn       = aws_sfn_state_machine.emr_automation.arn
  role_arn  = aws_iam_role.eventbridge_sfn_role.arn
}
```

### 13. EC2 Instance (dbt Client)

> Console: [Phase 13: EC2 Instance for dbt](#phase-13-ec2-instance-for-dbt)

```hcl
resource "aws_instance" "dbt_client" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t3.micro"
  key_name               = aws_key_pair.kafka_access.key_name
  subnet_id              = aws_subnet.msk_subnet_a.id
  vpc_security_group_ids = [aws_security_group.msk_sg.id, aws_security_group.ec2_sg.id]

  root_block_device {
    volume_size = 8
  }

  tags = { Name = "dbt-client" }
}
```

---

### Parameterization Note

The Terraform blocks above use the following variables and placeholders. Replace them with values appropriate for your environment before running `terraform apply`.

| Variable / Placeholder | Type | Default | Where Used | Description |
|---|---|---|---|---|
| `var.region` | `string` | *(see `variable "region"` declaration above)* | Provider block, subnet availability zones (Block 1), EMR trust policy ARN (Block 11) | AWS region to deploy into |
| `<UNIQUE_SUFFIX>` | placeholder | *(none — you must replace)* | S3 bucket name and tag (Block 3) | Unique suffix to make the S3 bucket name globally unique |
| `data.aws_caller_identity.current.account_id` | data source | *(resolved at plan time)* | EMR trust policy `aws:SourceAccount` condition (Block 11) | Your AWS account ID — resolved automatically by Terraform |

