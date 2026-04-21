# Pipeline Documentation — Style Guide & Conventions

A reusable reference for writing step-by-step AWS/cloud pipeline documentation. Distilled from two aligned pipeline guides: the **real-time taxi rides pipeline** (MSK → Glue → EMR Serverless → Athena → dbt) and the **real-time AQI pipeline** (Kinesis → Firehose → Flink → CloudWatch → Grafana).

Use this guide when authoring a new pipeline document (or bringing an existing one into line). Every convention below has at least one reference implementation in the two production guides — cross-check against them if anything here is ambiguous.

---

## Document Structure

Every pipeline guide follows this single-h1 structure:

```
# Pipeline Name
**Topic:** One-line description

![Architecture diagram alt text](docs/diagrams/pipeline_architecture.svg)

[intro paragraph(s) + > Note callout]

## Data Flow — How the Pipeline Works in Production
## S3 Bucket Layout       (or equivalent — e.g., storage layout)
## AWS Services Used
## Component-by-Component Walkthrough
## [Optional comparison section, e.g., "Firehose vs Flink — Why We Use Both"]

## Step 1: [Descriptive title]
## Step 2: [Descriptive title]
...
## Step N: [Descriptive title]

## Troubleshooting
### [Service] Issues
#### [Specific symptom]

## Terraform Reference
### Provider
### 1. [Resource block name]
### 2. [Resource block name]
...
```

**Key rules:**

- **Single h1** — only the document title uses `#`. Everything else is h2 (`##`) or deeper. Never use "Section 1:", "Section 2:" prefixes on h1s — flat structure only.
- **No Table of Contents** — the flat h2 structure is short enough to scan in a rendered preview without a ToC.
- **Section order is fixed:** Architecture content first (Data Flow → S3 Bucket Layout → AWS Services Used → Component-by-Component Walkthrough), then the numbered Steps, then Troubleshooting, then Terraform Reference at the end.

---

## Title & Intro

```markdown
# Real-Time AQI Pipeline

**Topic:** Building a real-time data pipeline on AWS for Air Quality Index (AQI) data

![AQI real-time pipeline architecture showing Lambda, Kinesis, Firehose, Flink, S3, Glue, Athena, CloudWatch, SNS, and Grafana — two parallel workflows](docs/diagrams/pipeline_architecture.svg)

This pipeline ingests Air Quality Index (AQI) data and processes it in real-time using fully managed AWS services. Here's the end-to-end flow:

> **Note on source data:** This pipeline does not include an API ingestion step...
```

- **Title** is a simple `# Pipeline Name` — no centered `<div>`, no "Full Setup Guide" suffix.
- **Topic line** is `**Topic:**` followed by a single sentence summarizing what the pipeline does. This line lives between the title and the architecture diagram.
- **Architecture diagram** follows immediately as a markdown image reference. The alt text summarizes the data flow ("Lambda → Kinesis → Firehose → S3 → Athena, with Grafana monitoring") — not just "architecture diagram".
- **Intro paragraph** is one or two sentences describing what the pipeline does end-to-end.
- **`> **Note:**` callouts** follow the intro for anything a reader might assume incorrectly (e.g., "this pipeline doesn't include an API ingestion step — we start from CSVs in S3").

---

## Data Flow — How the Pipeline Works in Production

Always use this exact h2 title: `## Data Flow — How the Pipeline Works in Production`.

Present the flow as an **action-verb code block**, not a numbered prose list. Each step has an ALL-CAPS verb in a column, followed by the component and one-line summary, followed by arrow-indented sub-actions.

```
1. INGEST     Producer (Python on EC2) generates ride events continuously
                → publishes JSON messages to MSK Kafka topic

2. DELIVER    AWS Data Firehose (managed consumer) reads from MSK
                → buffers for 5 min or 5 MB
                → writes raw JSON to S3: <bucket>/<YYYY>/<MM>/<DD>/<HH>/

3. CLEAN      AWS Glue Job runs daily
                → reads raw JSON from S3
                → renames columns, drops unwanted fields, adds derived columns
                → writes cleaned CSV to S3: <bucket>/Refined/
```

**Formatting rules:**

- All content inside a single ```` ``` ```` code fence (no language tag — it's ASCII art).
- Verb column is aligned: content starts at **column 15** (left-pad the verb with spaces so `P` of "Producer" or `A` of "AWS" always begins at position 15).
- Arrow indent is **16 spaces** (so `→` sits at column 17). Use the Unicode arrow `→`, not ASCII `->`.
- Blank line between each numbered step.
- S3 paths use placeholder syntax: `<bucket>/<YYYY>/<MM>/<DD>/<HH>/`.
- Common verbs: `INGEST`, `DELIVER`, `CLEAN`, `ENRICH`, `AGGREGATE`, `MODEL`, `CATALOG`, `QUERY`, `MONITOR`, `VISUALIZE`. Pick the one that best describes the action — don't force "PROCESS" everywhere.

**For forked workflows**, use labeled sub-sections within the same code block:

```
1. INGEST     Lambda reads CSVs from S3
                → publishes records to Kinesis Data Stream: AQI_Stream

              ── AQI_Stream forks into two parallel workflows ──

Workflow A — Raw Archive

2. DELIVER    Firehose reads from AQI_Stream
                → writes raw JSON to S3

Workflow B — Enrichment + Monitoring

3. ENRICH     Flink reads from AQI_Stream
                → adds computed columns
                → writes enriched JSON to S3

...

Analytics & Observability (shared consumption)

8. QUERY      Athena queries tables through the Glue Data Catalog
```

End the section with a `**Why both?**` explanatory paragraph if the fork needs justification.

---

## S3 Bucket Layout

Placement: **immediately after the Data Flow code block** (before AWS Services Used).

Use either `## S3 Bucket Layout` (h2 sibling of Data Flow) or `### S3 Bucket Layout` (h3 nested under Data Flow) — whichever matches the rest of the document's flat/nested convention. Pick one and stay consistent.

**Pattern:** a single code block with an ASCII tree and right-aligned `←` annotations.

```
aqi-pipeline-bucket/
└── aqi_pipeline/
    ├── source_data/                                  ← AQI CSV files (uploaded manually from OpenAQ)
    ├── rawingestion/<YYYY>/<MM>/<DD>/<HH>/           ← Raw JSON from Firehose (auto-partitioned by arrival time)
    ├── flink_output/
    │   └── co-measurements/                          ← Enriched JSON from Flink
    └── athena-results/                               ← Athena query output
```

**Formatting rules:**

- Use box-drawing characters: `├── `, `└── `, `│   ` (not ASCII `|-` or `+-`).
- `←` arrows aligned to a consistent column (column 55 for flat trees, column 58 for trees nested under an outer prefix).
- Each `←` annotation describes what writes to that folder in one clause.
- **Right after the tree**, include two `> Note:` callouts when applicable:
  - Note on auto-partitioned paths (e.g., "Firehose automatically creates the `<YYYY>/<MM>/<DD>/<HH>/` hierarchy — you do not create these folders manually").
  - Note on bucket naming (e.g., "S3 bucket names are globally unique. If your chosen name is taken, append a suffix").

---

## AWS Services Used

Placement: **between S3 Bucket Layout and Component-by-Component Walkthrough**.

A compact 2-column table ordered **by the sequence data flows through the services** (NOT alphabetical and NOT by category).

```markdown
| Service | Role in Pipeline |
|---------|------------------|
| **S3** (`aqi-pipeline-bucket/aqi_pipeline/`) | Object storage for scalable data storage. Holds source CSVs, raw archive, Flink output, and Athena results |
| **Kinesis Data Streams** (`AQI_Stream`) | Real-time data streaming for high-throughput ingestion. Receives records from the producer Lambda and decouples producers from consumers |
| **Amazon Data Firehose** (`AQI_Batch`) | Fully managed service that loads streaming data into storage. Reads from `AQI_Stream` and delivers untransformed JSON to S3 |
| ... | ... |
```

**Formatting rules:**

- Service name in **bold**, followed by the resource name in `backticks in parentheses` if there's a specific named instance (e.g., `**MSK** (Managed Streaming for Kafka)`).
- Role column describes the service's function in one sentence — both the general service description and its specific role in this pipeline.
- Keep the description concise (one sentence). Longer explanations belong in Component-by-Component.

---

## Component-by-Component Walkthrough

A walkthrough of every service in the order data touches it, with enough depth to answer "why this service" and "what role does it play here".

```markdown
## Component-by-Component Walkthrough

Here's what each service does in the pipeline, in the order data touches it.

**S3 (Simple Storage Service)** — S3 is the object storage backbone of the entire pipeline. It holds everything — source CSVs, raw archives, enriched output, and query results. All data lives in a dedicated bucket organized under the `aqi_pipeline/` prefix (see the [S3 Bucket Layout](#s3-bucket-layout) tree above).

S3 plays two distinct roles in the pipeline:

- **Source** — the pipeline begins when a CSV file lands in `source_data/`. The producer Lambda reads from here...
- **Destination** — both workflows write their output back to S3...

> **Why one bucket?** Using a single bucket with prefixes instead of separate buckets keeps IAM simple — one bucket policy, one set of role permissions.

**Lambda (producer)** — A Lambda function picks up the S3 event, reads the CSV file, converts each row into a JSON record, and pushes those records into Kinesis...

> **Note:** The tutorial uses a local Python script for this step. We use a Lambda function instead because corporate SSO/VPN blocks local `boto3` connections to AWS.

**Apache Flink (stream processor)** — Flink is the brain of the pipeline. It reads records from `AQI_Stream` and runs two parallel jobs...

> **Why Flink instead of a Lambda for aggregations?** A Lambda *could* compute simple counts and averages per batch — and for low-volume pipelines that's fine. But Flink is a continuously running stream processor that maintains **state across records**...
```

**Formatting rules:**

- Section opens with a one-line intro: *"Here's what each service does in the pipeline, in the order data touches it."*
- Each service is a **bold-name paragraph**: `**Service Name** — description sentence(s).`
- No h3 subheadings for each service — they're all equal-weight paragraphs.
- **Order:** follow data flow, not alphabetical.
- Each component paragraph is **2–4 sentences** explaining what the service is and what it does in THIS pipeline.
- **Optional callouts** after a component paragraph:
  - `> **Why X instead of Y?**` — when we chose one service over an obvious alternative.
  - `> **Note:**` — for tutorial deviations or important gotchas.
  - `> **"Real-time" vs "micro-batch":**` — clarify terminology when a service's marketing name is misleading.
- Cross-link back to other sections using markdown anchors (`see the [S3 Bucket Layout](#s3-bucket-layout) tree above`).

---

## Steps (Console Guide)

The bulk of the document. Every resource-creation action becomes one `## Step N:` section.

### Step title

```markdown
## Step 1: Create the MSK Cluster
```

- Always `## Step N:` (never "Phase N:" or "Section N:").
- Title describes **what you're creating** in the simplest verb form (`Create the MSK Cluster`, `Launch EC2 Instance`, `Install Kafka Libraries on EC2`).
- For complex steps that create multiple resources, the title names the primary one (`Create S3 Bucket and Firehose Stream (MSK → S3)`).

### Subsection order within a Step

**The action comes first**, followed by post-action steps, then context and explainers. This is a deliberate inversion of the tutorial-style "explain then do" pattern — readers get the instructions first and can scroll down for background if they want.

```markdown
## Step 1: Create the MSK Cluster

### Create the Cluster               ← 1. Action (descriptively named, NOT "Console Steps")

1. Click AWS Console → MSK → ...
...

Or via CLI:                          ← 2. CLI alternative
```bash
aws kafka create-cluster-v2 ...
```

### Get the Bootstrap Server Endpoint  ← 3. Post-action follow-up action

1. Click on the cluster name → ...

Or via CLI:
```bash
aws kafka get-bootstrap-brokers ...
```

### What is MSK?                      ← 4. Q&A / background (after all actions)

**Amazon Managed Streaming for Apache Kafka (MSK)** is...

### Prerequisites: VPC and Networking  ← 5. Prerequisite context (optional)

MSK Serverless requires a VPC with...
```

**Action subsection — descriptive title, never "Console Steps":**

| ❌ Generic | ✅ Descriptive |
|---|---|
| `### Console Steps` | `### Create the Cluster` |
| `### Steps` | `### Run the Producer` |
| `### Console Steps — Visual ETL` | `### Build the Visual ETL Job` |
| `### Console Steps` | `### Create the EventBridge Rule` |
| `### Console Steps` | `### Build the State Machine` |

The subsection title should say **what resource you're creating**, not that you're clicking buttons.

### CLI blocks

Every action with an AWS API equivalent gets a CLI block **immediately after** the numbered console steps (inside the same subsection).

```markdown
8. Wait for status to change from **Creating** to **Active** (takes a few minutes)

Or via CLI:
```bash
aws kafka create-cluster-v2 \
  --cluster-name MSK \
  --serverless 'VpcConfigs=[{SubnetIds=["<SUBNET_A>","<SUBNET_B>"],SecurityGroupIds=["<DEFAULT_SG_ID>"]}],ClientAuthentication={Sasl={Iam={Enabled=true}}}' \
  --region <YOUR_REGION>

# Poll cluster state until ACTIVE
aws kafka list-clusters-v2 \
  --cluster-name-filter MSK \
  --region <YOUR_REGION>
```
```

**CLI block rules:**

- Introduced by plain text `Or via CLI:` (no blockquote, no bold).
- Code fence: ```` ```bash ````.
- Use `<PLACEHOLDERS>` for user-specific values (`<YOUR_REGION>`, `<ACCOUNT_ID>`, `<SUBNET_ID>`).
- Include inline shell comments (`# Poll until ACTIVE`) for multi-command sequences that need explanation.
- For complex resources (Firehose, state machines), reference config JSON files: `--definition file://emr-automation.asl.json` — don't inline huge JSON in the bash block.
- When the action is inherently UI-only (Glue Visual ETL drag-and-drop, dbt docs web server, Grafana dashboard builder), **skip the CLI block** rather than forcing an awkward equivalent. Note the omission in prose.

### IAM policies inline

Console Steps for IAM role creation **include the JSON policy inline** (not just a reference to the Terraform section). Structured as:

```markdown
### Create the Policy and Role

1. AWS Console → IAM → Policies → Create policy
2. Switch to **JSON** tab, paste:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"],
            "Resource": "*"
        }
    ]
}
```
3. **Name:** `Access_to_Kafka_Cluster`
4. Click **Create policy**
...
```

For prerequisite IAM roles that were created earlier (e.g., the Lambda execution role created via Terraform ahead of time):

```markdown
### 3.1 — Prerequisite: Lambda Execution Role

The Lambda function needs the `aqi_lambda_execution_role` IAM role...

**Trust policy** — allows Lambda to assume this role:

```json
{
    "Version": "2012-10-17",
    "Statement": [ { "Effect": "Allow", "Principal": { "Service": "lambda.amazonaws.com" }, "Action": "sts:AssumeRole" } ]
}
```

**Inline policy** (`lambda-aqi-producer-access`) — grants the runtime permissions:

```json
{ ... }
```

> Terraform: [4. Lambda Execution Role](#4-lambda-execution-role)
```

Always label the JSON block clearly: `**Trust policy** — ...` and `**Inline policy** (\`policy-name\`) — ...`.

### Terraform cross-reference

Every Step ends with a callout linking to the equivalent Terraform block:

```markdown
> Terraform: [4. Lambda Execution Role](#4-lambda-execution-role)
```

- Prefix word: `> Terraform:` (blockquote, word followed by colon).
- Link text: the Terraform block's numbered name.
- Link anchor: the slugified heading (e.g., `#4-lambda-execution-role`).
- When a Step touches multiple Terraform blocks, list them on one line separated by `·`: `> Terraform: [11. Step Functions State Machine](#11-step-functions-state-machine) · [12. EventBridge Rule](#12-eventbridge-rule)`.

### Q&A and background

After all action subsections, include optional background:

- `### What is X?` — one-paragraph explanation of the service. **Only include if not already covered in Component-by-Component Walkthrough** (see Deduplication below).
- `### Why X?` — explains why we chose this service for this step.
- `### What is an IAM Policy?` / `### What is an IAM Role?` — generic concept explainers for readers new to AWS.
- `### Prerequisites: X` — what must exist before running the Step.
- `### Alternatives to X` — operational alternatives (e.g., "Alternatives to EC2 for running dbt" — CI/CD, dbt Cloud, Docker).

**Deduplication:** Do NOT repeat Component-by-Component content inside Step Q&A. If "What is MSK?" is already a component paragraph, don't repeat it in Step 1 — the walkthrough is the single source of truth for service descriptions.

---

## File References

When a Step requires pasting a script or config, **reference the file from the `docs/` folder** instead of inlining the content.

```markdown
Paste the contents of [`docs/resources/kafka_producer.py`](docs/resources/kafka_producer.py) into the editor.
**Before saving**, update `topicname`, `BROKERS`, and `region` at the top of the script with your values.
```

```markdown
### Create sources.yml

Navigate to the models directory and create the file by copying the tracked version:

```bash
cd ~/dbt_athena/models/
vi sources.yml   # paste the content from docs/dbt/sources.yml, then :wq
```

The source definitions live in [`docs/dbt/sources.yml`](docs/dbt/sources.yml) — copy that file's content verbatim into the editor.
```

**Rules:**

- Use markdown inline links: `[path/to/file.ext](path/to/file.ext)`.
- Paths are **relative to the markdown file**. If the guide is at `project/guide.md` and the file is at `project/docs/dbt/sources.yml`, the link is `docs/dbt/sources.yml`.
- When multiple files are referenced in one subsection (e.g., several dbt models), use a **table**:

```markdown
| Model file | Purpose | Source |
|---|---|---|
| `total_revenue.sql` | Revenue by vendor | [`docs/dbt/total_revenue.sql`](docs/dbt/total_revenue.sql) |
| `daily_avg_fare.sql` | Daily average fare trend | [`docs/dbt/daily_avg_fare.sql`](docs/dbt/daily_avg_fare.sql) |
```

- **Never duplicate file content** inline in the guide. If the file exists in `docs/`, reference it. If the content doesn't exist as a file, either (a) create the file, or (b) justify why it's inline (e.g., a 3-line config snippet that's not worth its own file).

---

## docs/ Folder Layout

Every pipeline guide has a sibling `docs/` directory organized by **file format**, not by purpose:

```
pipeline_project/
├── pipeline_setup.md                        ← the main guide
└── docs/
    ├── diagrams/                            ← all image assets
    │   ├── pipeline_architecture.svg
    │   ├── pipeline_architecture.drawio     ← editable source
    │   ├── pipeline_architecture.png        ← bitmap fallback
    │   └── star_schema.svg
    ├── resources/                           ← Python, Bash, reference .md
    │   ├── kafka_producer.py
    │   ├── emr_spark_job.py
    │   └── step_function_and_event_bridge_config.md
    └── dbt/                                 ← dbt-specific SQL + YAML
        ├── sources.yml
        ├── total_revenue.sql
        └── vendor_test.yml
```

**Folder conventions:**

- `docs/diagrams/` — all image assets (SVG, PNG, drawio sources). Keep the editable `.drawio` alongside the exported `.svg`/`.png`.
- `docs/resources/` — Python scripts, shell scripts, and reference markdown (e.g., templates for Step Functions state machines).
- `docs/dbt/` — dbt-specific files: `.sql` (models + singular tests), `.yml` (sources + generic test definitions).
- If the pipeline uses a general SQL layer (Snowflake setup, Redshift DDLs, Athena DDLs as standalone files), use `docs/sql/` instead of `docs/dbt/`.
- If the pipeline has multiple script languages (Python + PySpark + bash), keep them co-located in `docs/resources/` — don't split by language unless there are 5+ files of a single type.

**Naming:**

- Filenames describe what the file contains or does: `kafka_producer.py`, `emr_spark_job.py`, `sources.yml`, `vendor_test.yml`.
- No generic names (`script1.py`, `models.sql`).
- Diagram filenames describe the diagram: `pipeline_architecture.svg`, `star_schema.svg`, `dbt_lineage.svg`.

---

## Troubleshooting

Placement: **between the last Step and the Terraform Reference section** (for pipelines where this reads well), OR nested inside the relevant Step when the issue is specific to one phase.

Structure:

```markdown
## Troubleshooting

Common issues you may hit during setup, grouped by component. Start with the group that matches the error you're seeing.

### Flink Issues

#### Flink source table shows no data

1. Verify Kinesis stream has data: **Kinesis → AQI_Stream → Monitoring** — check `IncomingRecords`
2. Re-run the producer Lambda to push more records
3. Check `scan.stream.initpos = 'TRIM_HORIZON'` — if set to `LATEST`, only new records are read

#### Flink S3 sink doesn't produce files

1. Checkpointing must be enabled — verify `SET 'execution.checkpointing.interval' = '10 s'` was run
2. Wait at least 30 seconds (the rollover interval)
3. Check the Flink notebook role has S3 write permissions

### Firehose Issues
...
```

**Rules:**

- `## Troubleshooting` (h2) — a single section with all issues.
- `### [Component] Issues` (h3) — one per service with problems to document.
- `#### [Specific symptom]` (h4) — the issue title as the user would search for it (copy the exact error message where relevant).
- Each issue is a **numbered fix list** (steps the user can execute), not prose.
- **No duplicates of Step content.** If a workaround is already in Step 2, don't repeat it here — either move it to Troubleshooting and link from the Step, or leave it in the Step and skip the Troubleshooting entry.
- **Hierarchy is h2 → h3 → h4** to keep each issue discoverable but visually subordinate to the broader Troubleshooting section.

---

## Terraform Reference

Every guide closes with a `## Terraform Reference` section. This is the **single source of truth for infrastructure-as-code** — console Steps and Terraform are two views of the same architecture.

### Section title

Always: `## Terraform Reference` (not "Terraform Configurations", not "Terraform — All Resources", not "IaC").

### Section intro

Two paragraphs + one callout + one lead-in sentence, in this order:

```markdown
## Terraform Reference

This section provides a complete, copy-pasteable Terraform configuration that reproduces every AWS resource built through the console guide above. You can use it in two ways: **(a)** hand the entire file to your DevOps team so they can provision the pipeline in a repeatable, auditable manner, or **(b)** run it yourself in a sandbox account where you have admin rights, then point your team at the state file for production promotion.

**DevOps handoff workflow:** Because the corporate AWS account restricts direct IAM and infrastructure creation, the recommended workflow is to commit these Terraform files to your team's infra repository, open a merge request tagged `pipeline-infra`, and let DevOps review, plan, and apply. IAM-related blocks are flagged below so reviewers know which resources require elevated privileges. All other resources (S3 objects, Kinesis streams, Lambda functions, Glue, CloudWatch, SNS, EventBridge) can typically be applied by a developer role with scoped permissions.

> **Order matters:** Apply these resources in the order listed. Later resources reference earlier ones (e.g., the MSK cluster references the subnets and security group; the Step Functions state machine references the EMR execution role). Terraform handles the dependency graph automatically, but if you apply blocks selectively, follow the ordering below.

Before any `resource` blocks, your `.tf` file needs the standard provider preamble. This tells Terraform which cloud provider plugins to download and which region to target:

### Provider
```

Word-for-word, the two paragraphs and the callout are reusable across pipelines — you only need to tweak the list of IAM block names in the DevOps-handoff paragraph and the example resources in the Order-matters callout.

### Provider block

Always a distinct `### Provider` h3 subsection. Region is a literal string with an inline comment:

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-2"  # Change to your region
}
```

### Numbered resource blocks

Each resource (or group of tightly-coupled resources) becomes a numbered h3. Numbering reflects **dependency order** — the order you'd apply blocks if doing it by hand.

| Pattern | When to use | Examples |
|---|---|---|
| `### N. [Resource Name]` | A single resource type | `1. S3 Bucket`, `3. Kinesis Data Streams`, `4. Lambda Execution Role` |
| `### N. IAM + [Resource]` | IAM + the resource it's for, in one block | `7. IAM + Firehose Stream`, `8. IAM + Glue ETL Job` |
| `### N. IAM + X + Y` | Multiple grouped resources | `10. IAM + Glue Crawler + Glue Database` |
| `### N. IAM — [Purpose]` | IAM role that describes a cross-service permission grant | `6. IAM — EC2 → MSK Access` |
| `### N. [X] → [Y] Trigger` | Wiring/trigger resources | `20. Kinesis → Lambda Trigger` |

**Separator rules:**

- `—` (em-dash) for purpose descriptions: `IAM — EC2 → MSK Access` means "IAM for the purpose of EC2 accessing MSK".
- `+` (plus) for grouped resources in the same block: `IAM + Firehose Stream` means "this block creates both the IAM role AND the Firehose stream".
- `→` (arrow) for directional relationships: `Kinesis → Lambda Trigger` means "a trigger that connects Kinesis to Lambda".

### Block structure

Each numbered block follows this pattern:

```markdown
### 7. IAM + Firehose Stream

Creates the IAM role that the Firehose delivery stream assumes, plus the delivery stream itself. The trust policy allows `firehose.amazonaws.com` to assume this role. The inline policy grants scoped access to read from `AQI_Stream` and write to the `rawingestion/` prefix in S3. **Note:** Because this creates an IAM role, it must be provisioned by your DevOps team per corporate policy. Corresponds to **Step 4** in the console guide.

```hcl
resource "aws_iam_role" "firehose_role" {
  ...
}

resource "aws_kinesis_firehose_delivery_stream" "aqi_batch" {
  ...
}
```
```

**Required elements per block:**

1. **Descriptive intro paragraph** — what the block creates, what permissions it grants, which console Step it corresponds to.
2. **IAM flag** — if the block creates IAM resources, note this explicitly ("Because this creates an IAM role, it must be provisioned by your DevOps team").
3. **Console Step cross-reference** — `Corresponds to **Step N** in the console guide` (hyperlink optional since it's a forward reference).
4. **One HCL code block** — complete, copy-pasteable.
5. **Optional post-block notes** — about auto-created AWS resources, IAM trust policy gotchas, terraform output hints.

### Parameterization (what NOT to do)

**Do not include a Parameterization Note table.** We deliberately moved away from this pattern.

Instead:

1. **Use Terraform internal references** wherever possible. A resource's attributes (`arn`, `id`, `bucket`, `name`) are accessed via `aws_resource_type.name.attribute`:

```hcl
# ✅ GOOD — internal reference, updates automatically when the resource changes
Resource = aws_s3_bucket.pipeline_bucket.arn

# ❌ BAD — literal string, stays stale if bucket name changes
Resource = "arn:aws:s3:::aqi-pipeline-bucket"
```

2. **Use visually-obvious `<PLACEHOLDERS>`** for values that must be provided by the user (bucket suffix, email, account ID when absolutely necessary):

```hcl
bucket = "aqi-pipeline-bucket-<UNIQUE_SUFFIX>"  # S3 bucket names are globally unique
endpoint = "<YOUR_EMAIL>"                      # Replace with your notification email
```

3. **Use inline comments** to tell the reader what to change:

```hcl
provider "aws" {
  region = "eu-west-2"  # Change to your region
}
```

4. **Use region-agnostic wildcards** in ARN patterns instead of hardcoding the region:

```hcl
# ✅ GOOD — wildcard, works regardless of deployment region
Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/my_fn"

# ❌ BAD — region baked in
Resource = "arn:aws:logs:eu-west-2:*:log-group:/aws/lambda/my_fn"
```

5. **Drop region suffixes from role names.** Don't name a role `KinesisFirehoseServiceRole-MyStream-eu-west-2` — name it `KinesisFirehoseServiceRole-MyStream`. The role is regional by virtue of being in a regional API call; embedding the region in the name just creates one more thing to update when switching regions.

6. **Close with a one-line reminder callout** (instead of a 20-row table):

```markdown
> **Before `terraform apply`:** Replace the two placeholders in the blocks above — `<UNIQUE_SUFFIX>` (S3 bucket name suffix, since bucket names are globally unique) and `<YOUR_EMAIL>` (SNS email subscription) — and update the provider `region` if you're deploying outside `eu-west-2`. Every other AWS resource reference is resolved automatically by Terraform at plan time. Run `terraform validate` for a syntax-only check and `terraform plan` to preview the graph before applying.
```

### Terraform block ordering

The numbered sequence in the Terraform Reference roughly mirrors the console Steps, but two rules override strict step-order:

1. **IAM roles come before the resources that use them.** If Step 4 creates an IAM role for the Lambda in Step 5, the Terraform block for the role is numbered *before* the Lambda block.
2. **Shared prerequisites come first.** S3 bucket (#1), Kinesis streams (#3), and other shared resources are numbered early because later blocks reference them.

---

## Content Principles

| Principle | Rule |
|---|---|
| **Single source of truth** | If content exists as a file in `docs/`, reference the file — don't copy it into the guide. If the same concept appears in multiple sections (Component walkthrough AND a Step Q&A), pick one and link from the other. |
| **Action before context** | Within a Step, the action subsection comes first. Background (`What is X?`, `Why X?`) comes after the action so readers can execute quickly and learn later. |
| **Verify against source code** | Schema documentation must match the code that produces the data. Column lists, resource names, and ARNs should be copy-pasted from the actual Terraform or scripts, not re-typed from memory. |
| **No fictional fields** | If the code doesn't produce a column, the docs don't list it. |
| **Terraform internal references over literals** | Inside Terraform blocks, prefer `aws_s3_bucket.X.arn` over `"arn:aws:s3:::..."`. This eliminates drift. |
| **Visible placeholders** | Values a user must change use `<PLACEHOLDER>` syntax so they're visually obvious. Inline comments explain what to substitute. |
| **Descriptive names** | Step titles, Terraform block titles, file names — all describe what they contain or create. No `Console Steps`, `Resource`, `Script1`. |
| **Explain deviations** | When the guide deviates from a vendor tutorial or common practice, explain why in a callout: `> **Tutorial vs our approach:** ...` |
| **Callouts for non-obvious decisions** | Use `> **Why X instead of Y?**` for architectural choices a reader might question. |
| **External references** | AWS docs, Snowflake docs, framework docs — link with descriptive text (not bare URLs), prefer permanent links. |

---

## Callout Styles

| Callout | When to use | Example |
|---|---|---|
| `> **Note:** ...` | Important info the reader shouldn't miss | `> **Note:** Firehose only reads new messages from the point it was created.` |
| `> **Why X?**` or `> **Why X instead of Y?**` | Architectural decisions | `> **Why Kafka instead of Kinesis?** MSK is the right fit when your team already has Kafka expertise...` |
| `> **Tutorial vs our approach:** ...` | Documenting deviations from a source tutorial | `> **Tutorial vs our approach:** The trainer uses a local Python script. We use a Lambda function instead because corporate SSO/VPN blocks local boto3 connections.` |
| `> **⚠️ Critical:** ...` or `> **⚠️ TODO:** ...` | Warnings and open items | `> **⚠️ Glue Version:** AWS Glue versions 0.9 and 1.0 reached End of Life on March 31, 2026.` |
| `> **💰 Cost note:** ...` | Billing-relevant info | `> **💰 Cost note:** MSK Serverless charges ~$0.75/hour even when idle.` |
| `> Terraform: [N. Block](#anchor)` | End-of-Step Terraform cross-reference | `> Terraform: [4. Lambda Execution Role](#4-lambda-execution-role)` |
| `Or via CLI:` (plain text, not blockquote) | Introduces a CLI alternative block | Used after numbered console steps, before a `` ```bash `` block |

---

## Formatting Conventions

- **Code fences with language tags:** `` ```bash ``, `` ```hcl ``, `` ```json ``, `` ```sql ``, `` ```yaml ``, `` ```python ``. Language-tagged fences enable syntax highlighting in most renderers.
- **Bare fences** (no language tag) only for ASCII diagrams (Data Flow verb blocks, S3 Bucket Layout trees). These render as plain monospace, which is what we want.
- **Horizontal rules** (`---`) to separate Steps. Not required between subsections within a Step.
- **Inline code** (backticks) for: resource names, file paths, bucket names, role names, CLI commands, config keys, environment variables, IAM actions.
- **Bold** (`**text**`) for: service names in Component-by-Component paragraphs, key terms on first use, UI elements being referenced (`click **Create cluster**`).
- **Italic** only for *emphasis* — sparingly.
- **Tables** for: configuration fields (`| Field | Value | Purpose |`), comparison matrices (`| Aspect | Option A | Option B |`), file references (`| File | Purpose | Source |`).
- **`&nbsp;`** is acceptable as a visual spacer between major sections if the rendered preview benefits from extra whitespace (used in AQI). Taxi uses plain blank lines. Either is fine — just be consistent within a document.

---

## Diagram Conventions

- All diagrams live in `docs/diagrams/` (NOT at project root).
- Keep the editable `.drawio` source alongside the exported `.svg`/`.png`.
- Reference from the guide: `![descriptive alt text](docs/diagrams/filename.svg)`.
- Architecture diagram is the **first image in the document**, immediately after the `**Topic:**` line.
- **Alt text describes the data flow**, not just names the diagram: `"Taxi ride pipeline architecture showing MSK Kafka, EC2 producer, Data Firehose, S3 raw/refined/business layers, Glue ETL, EMR Serverless Spark, Step Functions + EventBridge automation, Athena, and dbt"`.
- Avoid conveying meaning through color alone — shapes, labels, and topology should carry the information too.
- Diagram topology must match the actual architecture (branching for parallel paths, triggers beside targets, data sources at top).

---

## What Not To Do

| Don't | Because |
|---|---|
| Don't duplicate file content in the guide | The file is the source of truth — reference it, don't copy-paste it into `docs/`. |
| Don't use "Console Steps" as a subsection title | Use `Create the X` / `Launch the X` / `Build the X` — descriptive verb phrases. |
| Don't write "Phase N:" or "Section N:" for Step headings | Always `Step N:`. |
| Don't include a Parameterization Note table at the end of the Terraform section | Use Terraform internal references + `<PLACEHOLDER>` tokens + inline comments. |
| Don't hardcode AWS account IDs in Terraform blocks | Use `data.aws_caller_identity.current.account_id` or the resource's own `.arn` attribute. |
| Don't hardcode regions inside IAM policy ARNs | Use wildcards (`arn:aws:logs:*:*:log-group:/aws/lambda/X`) or Terraform references. |
| Don't nest triggers under the event producer | Triggers go with the thing they invoke. S3 → Lambda: the trigger belongs in the Lambda's component walkthrough, not S3's. |
| Don't write JSON policies only in the Terraform section | For console IAM steps that require pasting JSON, include the JSON inline in the Step too. |
| Don't repeat troubleshooting items already covered in Steps | Either move the workaround to Troubleshooting and link from the Step, or keep it in the Step and skip the Troubleshooting entry. |
| Don't use ASCII flow diagrams when a numbered list covers the same info | The Data Flow action-verb code block IS the ASCII flow — don't add a separate mermaid/ASCII diagram alongside it. |
| Don't use generic filenames | `script1.py` → `emr_spark_job.py`. `diagram1.svg` → `pipeline_architecture.svg`. |
| Don't use line count as a quality metric | A 2000-line guide isn't better than a 1500-line guide — coverage and clarity are what matter. |
| Don't assume schema from documentation | Verify column names, types, and ARNs against the source code. |

---

## Authoring Checklist (quick reference)

Run through this list before considering a pipeline guide "done":

- [ ] `# Title` line is singular (no centered `<div>`, no "Full Setup Guide" suffix).
- [ ] `**Topic:**` one-liner present between title and architecture SVG.
- [ ] Architecture SVG in `docs/diagrams/`, referenced from top of guide.
- [ ] Alt text on the SVG describes the data flow, not just "architecture".
- [ ] Data Flow uses the action-verb code block pattern (INGEST, DELIVER, etc.).
- [ ] S3 Bucket Layout tree sits immediately below Data Flow.
- [ ] AWS Services Used table sits between S3 Bucket Layout and Component Walkthrough.
- [ ] Component-by-Component Walkthrough covers every service in data-flow order.
- [ ] Each Step is titled `## Step N: [verb phrase]`.
- [ ] Action subsection inside each Step has a descriptive name (not "Console Steps").
- [ ] Action subsection comes first in each Step; Q&A/context comes after.
- [ ] CLI alternatives (`Or via CLI:` + ```bash block) appear after each console action where applicable.
- [ ] IAM policy JSON is inline in console IAM Steps.
- [ ] Every Step ends with `> Terraform: [N. Block Name](#anchor)`.
- [ ] File references use relative paths to `docs/resources/`, `docs/dbt/`, etc.
- [ ] No inline code duplicating content that exists in `docs/`.
- [ ] Troubleshooting section uses h3-per-component, h4-per-symptom hierarchy.
- [ ] `## Terraform Reference` section present, with the standard 2-paragraph + Order-matters intro.
- [ ] `### Provider` subsection present with inline `# Change to your region` comment.
- [ ] Terraform blocks are numbered sequentially, use descriptive names (`IAM + X`, `IAM — X`, `X → Y`).
- [ ] No Parameterization Note table — replaced with Terraform internal references + visible `<PLACEHOLDERS>`.
- [ ] Closing callout lists only the true user-facing placeholders (typically `<UNIQUE_SUFFIX>`, `<YOUR_EMAIL>`).
- [ ] Single h1 (`#`) in the document — everything else is `##` or deeper.
- [ ] No broken anchor links (verify with `terraform validate` equivalent for markdown — opening the rendered preview and clicking each callout link).
