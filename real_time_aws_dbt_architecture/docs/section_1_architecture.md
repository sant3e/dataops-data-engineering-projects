# Section 1: Architecture

> **Last verified:** 2026-04-20

&nbsp;

## Contents

- [Architecture Overview](#architecture-overview)
- [Data Flow](#data-flow)
- [Component-by-Component Walkthrough](#component-by-component-walkthrough)
- [Services Used](#services-used)
- [S3 Bucket Structure](#s3-bucket-structure)

&nbsp;

This pipeline ingests real-time ride data via **Amazon MSK** (Kafka), transforms it through **Glue** and **EMR Serverless**, builds a star schema in **S3**, and serves analytical queries through **Athena** and **dbt**.

The pipeline uses:
- **Amazon MSK** — managed Kafka cluster for real-time event streaming
- **Amazon Data Firehose** — managed consumer that delivers raw JSON to S3
- **S3** — storage for all data layers (raw, refined, business, scripts)
- **EC2** — hosts Kafka CLI tools and the producer script
- **AWS Glue Job** — Visual ETL for column renames, drops, and derived fields
- **AWS Glue Crawler** — schema discovery and Glue Data Catalog registration
- **Glue Data Catalog** — centralized metadata store for Athena
- **EMR Serverless** — PySpark dimensional modelling (star schema)
- **Step Functions** — orchestrates the daily EMR pipeline
- **EventBridge** — triggers the pipeline on a schedule
- **Amazon Athena** — serverless SQL over S3 via Glue Catalog
- **dbt** — analytics engineering layer on top of Athena
- **IAM** — roles and policies for cross-service access

&nbsp;

## Architecture Overview

> **Diagram:** See [pipeline_architecture.drawio](diagrams/pipeline_architecture.drawio) for the full AWS architecture diagram with service icons and data flow arrows.

> **Star Schema:** ![Star schema ER diagram: fact_trips central fact table with FK relationships to dim_vendor, dim_payment, and dim_location](diagrams/star_schema.svg)

> **dbt Lineage:** ![dbt lineage flowchart: sources (dim_vendor, dim_payment, dim_location, facts) feed into 4 models (total_revenue, daily_avg_fare, revenue_by_payment, top_routes) validated by tests](diagrams/dbt_lineage.svg)

&nbsp;

## Data Flow

1. **EC2 Producer** (`kafka_producer.py`) generates continuous ride events (pickup, dropoff, fare, timestamps) and publishes JSON messages to an MSK Kafka topic
2. **Amazon Data Firehose** reads from the MSK topic, buffers records for 5 minutes or 5 MB (whichever comes first), and writes raw JSON to S3 under a time-partitioned path: `s3://ridestreamlakehouse-td/<YYYY>/<MM>/<DD>/<HH>/`
3. **AWS Glue** (Visual ETL job) reads the raw JSON from S3, renames columns, drops unwanted fields, adds derived columns, and writes cleaned CSV to `s3://ridestreamlakehouse-td/Refined/`
   - Trigger: **runs daily** (manual or scheduled)
4. **EMR Serverless** (PySpark job) reads the refined CSV, builds a star schema — 3 dimension tables (`dim_vendor`, `dim_location`, `dim_payment`) and 1 fact table (`fact_trips`) — and writes Parquet to `s3://ridestreamlakehouse-td/Business/processed/dimensions/` and `facts/`
   - Trigger: **Step Functions** orchestrates daily execution
   - Production: partitioned by `trip_date` for efficient querying
5. **Glue Crawler** scans the Parquet files in `Business/processed/`, discovers schemas, and registers tables in the Glue Data Catalog
6. **Amazon Athena** queries tables via the Glue Catalog using serverless SQL
   - **dbt** connects to Athena and builds analytical models (joins, aggregations, business logic)

&nbsp;

## Component-by-Component Walkthrough

Here's what each service does in the pipeline, in the order data touches it.

### What is MSK / Kafka?

**Amazon MSK (Managed Streaming for Apache Kafka)** is a fully managed Kafka cluster service. Kafka is a distributed streaming platform built around four core concepts:

- **Producer** — an application that publishes (writes) messages to Kafka. In this pipeline, the ride event generator running on EC2 is the producer. It sends ride data — pickup location, dropoff location, fare amount, timestamps — as JSON messages into a Kafka topic.
- **Topics** — named channels that organize messages by category. Think of a topic as a feed or stream. Producers write to a topic, consumers read from it (e.g., a `ride_events` topic). Topics are split into **partitions** for parallel processing and horizontal scalability.
- **Consumer** — an application that subscribes to and reads messages from topics. In this pipeline, Amazon Data Firehose acts as the managed consumer — it reads from the MSK topic and delivers records to S3. Consumers track their position (**offset**) in each partition so they can resume where they left off after a restart or failure.
- **Cluster** — a group of Kafka servers (**brokers**) working together. The cluster provides fault tolerance (data is replicated across brokers) and horizontal scalability (partitions are distributed across brokers). AWS MSK is a managed Kafka cluster — AWS handles broker provisioning, patching, and replication.

The **bootstrap server** is the initial connection endpoint that any client (producer or consumer) uses to discover the full cluster. When a client connects, it contacts the bootstrap server address, receives metadata about all brokers and which broker owns which topic partitions, and then connects directly to the appropriate brokers for reading or writing. Think of it as a phonebook — you call one number to get the directory of everyone else. In AWS MSK, the bootstrap server endpoint is found under **View client information** after the cluster is created.

This pipeline uses **MSK Serverless**, which auto-provisions and scales Kafka capacity on demand. There are no brokers to size, no storage to provision, and no ZooKeeper to manage — you create a cluster, get the bootstrap endpoint, and start producing.

> **Why MSK Serverless?** MSK Serverless vs MSK Provisioned — Serverless auto-scales broker capacity, eliminates operational overhead (no broker count decisions, no storage management, no ZooKeeper), and charges per throughput rather than per broker-hour. Provisioned MSK gives fixed capacity and lower per-GB cost at sustained high volume, but requires you to choose instance types, broker counts, and storage. For a tutorial pipeline with variable and intermittent load, Serverless eliminates operational complexity and avoids paying for idle brokers.

**EC2** (`kafka-client`) — Hosts the Kafka CLI tools and the producer script. EC2 is the workstation inside the VPC where you create Kafka topics (`kafka-topics.sh`), test produce/consume from the command line, and run `kafka_producer.py` to generate continuous ride events. The instance must be in the same VPC as the MSK cluster and have an IAM role that permits MSK access. Once data is flowing through Firehose to S3, the EC2 instance is no longer needed for the pipeline to operate — it is a setup and testing tool, not a runtime dependency.

**Amazon Data Firehose** (`ride-data-firehose`) — A fully managed delivery stream that acts as the Kafka consumer. Firehose reads from the MSK topic, buffers records, and writes raw JSON to S3 in micro-batches. It handles all the complexity of consuming from Kafka — offset tracking, retry on failure, backpressure — with zero application code. The output lands in a time-partitioned S3 path (`<YYYY>/<MM>/<DD>/<HH>/`) created automatically based on arrival time.

> **Why Firehose as managed consumer?** Firehose vs a custom Kafka consumer on EC2 — Firehose requires zero code, auto-scales with throughput, handles retries and delivery guarantees out of the box, and integrates natively with MSK as a source. A custom consumer gives more control over processing logic, batching behavior, and output format, but requires you to manage EC2 instances or containers, handle offset commits, and implement retry logic yourself. For a pipeline that simply needs reliable delivery of raw records to S3, Firehose eliminates an entire class of operational burden.

**S3** (`ridestreamlakehouse-td`) — The storage backbone of the entire pipeline. All data lives in a single bucket organized by prefix — raw JSON from Firehose, cleaned CSV from Glue, dimensional Parquet from EMR, PySpark scripts, and Athena query results. S3 serves as both the landing zone for raw ingestion and the permanent analytical store for transformed data. Every downstream service reads from and writes to S3.

**AWS Glue Job** (Visual ETL) — A managed ETL service that runs the first transformation step. The Visual ETL job reads raw JSON from the Firehose output path, renames columns to human-readable names, drops unwanted fields, and adds derived columns (e.g., trip duration calculations). The output is cleaned CSV written to the `Refined/` prefix. Visual ETL provides a drag-and-drop canvas for defining these transformations — no Spark or Python code to write or maintain.

> **Why Glue Visual ETL?** Glue Visual ETL vs a Glue script job vs Lambda — Visual ETL provides a drag-and-drop interface for simple transformations (column renames, drops, type casts, derived fields) without writing or maintaining any code. A Glue script job offers full PySpark flexibility but requires writing and testing Python code. Lambda could handle small-file transformations but has a 15-minute timeout and 10 GB memory limit that makes it unsuitable for growing datasets. For this pipeline's transformation needs — column renames, field drops, and a few derived columns — Visual ETL is sufficient and eliminates script maintenance entirely.

**EMR Serverless** — Runs the PySpark dimensional modelling job that transforms the cleaned CSV into a star schema. The job reads from `Refined/`, applies business logic to build 3 dimension tables (`dim_vendor`, `dim_location`, `dim_payment`) and 1 fact table (`fact_trips`), and writes Parquet to `Business/processed/`. EMR Serverless provisions Spark capacity on demand — you submit a job, it spins up the compute, runs the job, and releases the resources when done. No cluster to manage, no idle capacity to pay for.

> **Why EMR Serverless?** EMR Serverless vs EMR on EC2 vs Glue for Spark — EMR Serverless eliminates cluster management entirely. You submit a Spark job and AWS provisions the compute, scales it during execution, and releases it when the job finishes. Standard EMR on EC2 requires you to choose instance types, manage cluster lifecycle, and pay for idle time between jobs. Glue could run PySpark jobs too, but EMR gives you more control over Spark configuration and access to the full Spark ecosystem. For a daily batch job that runs for minutes and then has no work, Serverless's pay-per-execution model is the most cost-effective option.

**Step Functions** — Orchestrates the daily EMR pipeline. The state machine defines the execution sequence: submit the EMR Serverless job, poll for completion, handle success or failure. Step Functions provides built-in retry logic, timeout handling, and visual execution history. Without it, you would need a cron job or Lambda to submit the EMR job and another mechanism to check whether it finished successfully before triggering the downstream Glue Crawler.

**EventBridge** — Automates the full pipeline on a schedule. An EventBridge rule triggers the Step Functions state machine at a defined interval (e.g., daily), which in turn runs the EMR job, waits for completion, and kicks off the Glue Crawler. EventBridge is the clock that drives the pipeline — without it, you would need to start each run manually.

> **Why EventBridge?** EventBridge vs a direct Lambda trigger or cron — EventBridge decouples the schedule from the target. You can change the schedule, add multiple downstream targets, or apply event filtering without modifying any other resource. A CloudWatch Events cron rule would work for simple scheduling, but EventBridge offers richer event matching, cross-account event routing, and a cleaner integration with Step Functions. For a pipeline that needs reliable daily execution, EventBridge provides the scheduling layer with the least operational friction.

**Glue Crawler** — Scans the Parquet files written by EMR in `Business/processed/`, infers the schema (column names, types, partition structure), and registers the tables in the Glue Data Catalog. The crawler runs after each EMR job completes, ensuring the catalog always reflects the latest data. Without the crawler, you would need to manually define table schemas in the catalog every time the data structure changes.

**Glue Data Catalog** — The centralized metadata store that Athena reads from. It holds table definitions — column names, data types, partition keys, S3 locations — for every dataset the crawler has registered. When you run a query in Athena, it consults the Data Catalog to know where the data lives and what shape it has. The catalog is not a database — it stores no data itself, only metadata about data stored in S3.

**Amazon Athena** — A serverless SQL query engine that runs queries directly against S3 files using the schemas registered in the Glue Data Catalog. There is no infrastructure to manage and no data to load — you write SQL, Athena scans the relevant S3 files, and returns results. You pay per terabyte scanned, so Parquet's columnar format (which allows Athena to skip irrelevant columns) keeps costs low. Athena is the interactive query layer of the pipeline — useful for ad-hoc analysis, data validation, and feeding dbt models.

**dbt** — The analytics engineering layer. dbt connects to Athena as its query engine and builds analytical models — SQL transformations that join dimension and fact tables, compute aggregations, and produce business-ready datasets. Models are version-controlled, tested, and documented. dbt does not move data — it issues SQL statements against Athena, which in turn reads from and writes to S3. This separation means dbt handles the *what* (business logic) while Athena handles the *how* (query execution).

> **Tutorial vs our approach:** The trainer uses a dedicated EC2 instance to install and run dbt, keeping the entire pipeline within AWS. A local install or a container-based approach (e.g., Docker on a developer machine or ECS) would also work — dbt itself is a Python CLI tool that only needs network access to Athena. The dedicated EC2 was chosen for a consistent environment, straightforward access to AWS services without VPN/SSO complications, and reproducibility across different developer setups.

&nbsp;

## Services Used

| Service | Role in Pipeline |
|---|---|
| **S3** (`ridestreamlakehouse-td`) | Storage for all data layers — raw JSON, refined CSV, business Parquet, scripts, and Athena results |
| **EC2** (`kafka-client`) | Hosts Kafka CLI tools and the producer script for topic creation, testing, and event generation |
| **AWS Glue Job** (Visual ETL) | First transformation — renames columns, drops fields, adds derived columns, outputs CSV to `Refined/` |
| **AWS Glue Crawler** | Scans Parquet files in `Business/processed/`, discovers schemas, registers tables in Glue Data Catalog |
| **Glue Data Catalog** | Centralized metadata store — table definitions (columns, types, partitions, S3 locations) for Athena |
| **EMR Serverless** | Runs PySpark dimensional modelling — builds star schema (3 dimensions + 1 fact table) from refined CSV |
| **Amazon MSK** (Serverless) | Managed Kafka cluster for real-time ride event streaming from the EC2 producer |
| **Amazon Data Firehose** (`ride-data-firehose`) | Managed Kafka consumer — reads from MSK topic, buffers, writes raw JSON to S3 |
| **Step Functions** | Orchestrates the daily EMR pipeline — submit job, poll for completion, handle success/failure |
| **EventBridge** | Triggers the Step Functions state machine on a schedule (e.g., daily) to automate the pipeline |
| **Amazon Athena** | Serverless SQL query engine — queries S3 data via Glue Catalog, pay-per-scan pricing |
| **dbt** | Analytics engineering — builds analytical models (joins, aggregations, business logic) on top of Athena |
| **IAM** | Roles and policies for cross-service access — EC2-to-MSK, Firehose-to-S3, EMR execution role, Glue permissions |

&nbsp;

## S3 Bucket Structure

```
ridestreamlakehouse-td/
├── <YYYY>/<MM>/<DD>/<HH>/                            ← Raw JSON from Firehose (auto-partitioned by arrival time)
├── Refined/                                           ← Cleaned CSV from Glue Job
├── Business/
│   └── processed/
│       ├── dimensions/
│       │   ├── dim_vendor/       (parquet)            ← Vendor dimension table
│       │   ├── dim_location/     (parquet)            ← Location dimension table
│       │   └── dim_payment/      (parquet)            ← Payment type dimension table
│       └── facts/
│           └── fact_trips/       (parquet)            ← Trip fact table (partitioned by trip_date)
├── scripts/                                           ← PySpark scripts for EMR Serverless
└── athena-results/                                    ← Athena query output
```

> **Note on raw data path:** Firehose automatically creates the `<YYYY>/<MM>/<DD>/<HH>/` hierarchy based on arrival time. You do not create these folders manually.

> **Note on bucket naming:** S3 bucket names are globally unique across all AWS accounts worldwide. If your chosen name is taken, append a suffix.
