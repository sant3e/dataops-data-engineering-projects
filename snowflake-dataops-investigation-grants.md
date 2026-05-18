# Snowflake DataOps Investigation Role

This document summarizes broad, future-friendly Snowflake grants for a DataOps role intended to investigate account infrastructure, metadata, access, usage, and operational behavior without administering objects or reading business table data.

Role used in examples:

```sql
SNF_R_DATA_OPS
```

## 1. Broad Grants

| Query | Description |
|---|---|
| `GRANT RESOLVE ALL ON ACCOUNT TO ROLE SNF_R_DATA_OPS;` | Allows the role to resolve/discover objects across the account. This makes objects appear in matching `SHOW` command output even when the role does not otherwise have object privileges. Useful for inventory, access troubleshooting, and lineage visibility. Does not grant data access or object modification rights. |
| `GRANT DATABASE ROLE SNOWFLAKE.OBJECT_VIEWER TO ROLE SNF_R_DATA_OPS;` | Grants read access to object metadata views in `SNOWFLAKE.ACCOUNT_USAGE`, such as databases, schemas, tables, views, columns, stages, pipes, resource monitors, object dependencies, and related metadata. |
| `GRANT DATABASE ROLE SNOWFLAKE.SECURITY_VIEWER TO ROLE SNF_R_DATA_OPS;` | Grants read access to security-related `SNOWFLAKE.ACCOUNT_USAGE` views, such as users, roles, grants, login history, network policies, password policies, session policies, shares, secrets metadata, and security findings. |
| `GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE SNF_R_DATA_OPS;` | Grants read access to usage and operational history views in `SNOWFLAKE.ACCOUNT_USAGE`, such as warehouse metering/load, storage usage, data transfer, task history, pipe usage, copy/load history, serverless task/alert usage, and other historical usage metrics. This is the main account-level billing/credit-consumption visibility grant. |
| `GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER TO ROLE SNF_R_DATA_OPS;` | Grants read access to governance-related `SNOWFLAKE.ACCOUNT_USAGE` views, such as access history, query history, masking policies, row access policies, policy references, tags, classification history, query insights, and query attribution. |
| `GRANT MONITOR USAGE ON ACCOUNT TO ROLE SNF_R_DATA_OPS;` | Allows account-level usage and historical monitoring for databases and warehouses. Also makes `SHOW DATABASES` and `SHOW WAREHOUSES` return all databases and warehouses in the account, regardless of other grants. Complements `SNOWFLAKE.USAGE_VIEWER`. |
| `GRANT MONITOR EXECUTION ON ACCOUNT TO ROLE SNF_R_DATA_OPS;` | Allows monitoring task and pipe execution across the account. Useful for investigating ingestion and orchestration issues. Does not allow operating, pausing, resuming, or modifying those objects. |
| `GRANT MONITOR ROLE ON ACCOUNT TO ROLE SNF_R_DATA_OPS;` | Allows viewing roles in the account. Useful for understanding role inventory and access paths. Does not allow creating, granting, revoking, or modifying roles. |
| `GRANT MONITOR USER ON ACCOUNT TO ROLE SNF_R_DATA_OPS;` | Allows viewing users and their properties in the account. Useful for login/access investigations. Does not allow creating, altering, disabling, or managing users. |
| `GRANT VIEW LINEAGE ON ACCOUNT TO ROLE SNF_R_DATA_OPS;` | Allows viewing upstream and downstream lineage. Combined with `RESOLVE ALL`, this helps DataOps see lineage broadly across objects without needing object-specific grants. Does not grant access to the data in those objects. |

Billing note: these grants cover Snowflake account usage, credits, warehouse consumption, storage, and operational cost drivers. They do not grant organization-level invoice/currency views such as `SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` or `RATE_SHEET_DAILY`.

## 2. DataOps Investigation Examples

### Get a Broad Infrastructure Inventory

Use this at the start of an investigation when you need a quick account-wide view of core infrastructure objects.

```sql
USE ROLE SNF_R_DATA_OPS;

SHOW WAREHOUSES;
SHOW DATABASES;
SHOW SCHEMAS IN ACCOUNT;
SHOW TASKS IN ACCOUNT;
SHOW PIPES IN ACCOUNT;
```

For object counts by database and schema:

```sql
SELECT
  table_catalog,
  table_schema,
  COUNT(*) AS table_count
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
WHERE deleted IS NULL
GROUP BY table_catalog, table_schema
ORDER BY table_count DESC;
```

### Investigate a Warehouse Cost Spike

Use this when someone reports high credit usage or unexpected warehouse cost.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  warehouse_name,
  start_time,
  end_time,
  credits_used,
  credits_used_compute,
  credits_used_cloud_services
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY credits_used DESC;
```

Then correlate with query history:

```sql
SELECT
  warehouse_name,
  user_name,
  role_name,
  query_id,
  query_type,
  execution_status,
  start_time,
  total_elapsed_time,
  credits_used_cloud_services,
  query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND warehouse_name = 'WAREHOUSE_NAME_HERE'
ORDER BY total_elapsed_time DESC;
```

### Investigate Warehouse Queuing or Sizing Pressure

Use this when users report slow queries, queued queries, or when a warehouse might be undersized.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  start_time,
  end_time,
  warehouse_name,
  avg_running,
  avg_queued_load,
  avg_queued_provisioning,
  avg_blocked
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND (
    avg_queued_load > 0
    OR avg_queued_provisioning > 0
    OR avg_blocked > 0
  )
ORDER BY start_time DESC, avg_queued_load DESC;
```

Then inspect the queries that waited:

```sql
SELECT
  warehouse_name,
  user_name,
  role_name,
  query_id,
  query_type,
  start_time,
  total_elapsed_time,
  queued_overload_time,
  queued_provisioning_time,
  transaction_blocked_time,
  query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND warehouse_name = 'WAREHOUSE_NAME_HERE'
  AND (
    queued_overload_time > 0
    OR queued_provisioning_time > 0
    OR transaction_blocked_time > 0
  )
ORDER BY start_time DESC;
```

### Investigate Storage Growth

Use this when storage costs increase or a database appears to be growing unexpectedly.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  usage_date,
  database_name,
  average_database_bytes,
  average_failsafe_bytes
FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
WHERE usage_date >= DATEADD(day, -30, CURRENT_DATE())
ORDER BY usage_date DESC, average_database_bytes DESC;
```

Drill into table-level storage:

```sql
SELECT
  table_catalog,
  table_schema,
  table_name,
  active_bytes,
  time_travel_bytes,
  failsafe_bytes,
  retained_for_clone_bytes
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
ORDER BY active_bytes DESC;
```

### Investigate Failed or Delayed Tasks

Use this when a scheduled job is late, skipped, or failing.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  database_name,
  schema_name,
  name AS task_name,
  state,
  scheduled_time,
  completed_time,
  error_code,
  error_message,
  query_id
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD(day, -3, CURRENT_TIMESTAMP())
ORDER BY scheduled_time DESC;
```

Find the task definition and owner:

```sql
SELECT
  database_name,
  schema_name,
  name,
  owner,
  state,
  warehouse,
  schedule,
  predecessors,
  condition,
  definition
FROM SNOWFLAKE.ACCOUNT_USAGE.TASKS
WHERE deleted IS NULL
ORDER BY database_name, schema_name, name;
```

### Investigate Warehouse Resume, Suspend, Resize, or Cluster Events

Use this when a warehouse appears to resume too often, suspend unexpectedly, resize, or scale clusters.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  timestamp,
  warehouse_name,
  cluster_number,
  event_name,
  event_reason,
  event_state,
  user_name,
  role_name,
  query_id,
  size,
  cluster_count,
  warehouse_type
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
WHERE timestamp >= DATEADD(day, -14, CURRENT_TIMESTAMP())
ORDER BY timestamp DESC;
```

### Investigate Snowpipe or Load Issues

Use this when files are not loading or ingestion volume changes unexpectedly.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  pipe_name,
  start_time,
  end_time,
  credits_used,
  bytes_inserted,
  files_inserted
FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY start_time DESC;
```

Check load history:

```sql
SELECT
  schema_name,
  table_name,
  file_name,
  last_load_time,
  status,
  row_count,
  row_parsed,
  error_count,
  first_error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.LOAD_HISTORY
WHERE last_load_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY last_load_time DESC;
```

### Investigate Query Failures or Runtime Errors by Warehouse

Use this when jobs are failing, dashboards are timing out, or a warehouse has many unsuccessful queries.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  warehouse_name,
  user_name,
  role_name,
  query_id,
  query_type,
  execution_status,
  start_time,
  total_elapsed_time,
  error_code,
  error_message,
  query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND warehouse_name = 'WAREHOUSE_NAME_HERE'
  AND execution_status != 'SUCCESS'
ORDER BY start_time DESC;
```

For slow successful queries, sort by runtime:

```sql
SELECT
  warehouse_name,
  user_name,
  role_name,
  query_id,
  query_type,
  start_time,
  total_elapsed_time,
  execution_time,
  compilation_time,
  bytes_scanned,
  rows_produced,
  query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND warehouse_name = 'WAREHOUSE_NAME_HERE'
  AND execution_status = 'SUCCESS'
ORDER BY total_elapsed_time DESC;
```

### Investigate Lineage Before Changing or Deprecating an Object

Use this when a table, view, or pipeline object might be changed and you need to understand downstream impact.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  referencing_database,
  referencing_schema,
  referencing_object_name,
  referencing_object_domain,
  referenced_database,
  referenced_schema,
  referenced_object_name,
  referenced_object_domain
FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
WHERE referenced_database = 'DATABASE_NAME_HERE'
  AND referenced_schema = 'SCHEMA_NAME_HERE'
  AND referenced_object_name = 'OBJECT_NAME_HERE'
ORDER BY referencing_database, referencing_schema, referencing_object_name;
```

In Snowsight, use the Lineage tab with `SNF_R_DATA_OPS` to inspect upstream and downstream relationships visually.

### Investigate Cross-Region or Cross-Cloud Data Transfer

Use this when data transfer costs increase or when you need to understand unload, replication, external access, or cross-region traffic.

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  start_time,
  end_time,
  source_cloud,
  source_region,
  target_cloud,
  target_region,
  transfer_type,
  bytes_transferred::NUMBER AS bytes_transferred
FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
ORDER BY start_time DESC, bytes_transferred DESC;
```

Summarize by transfer route:

```sql
USE ROLE SNF_R_DATA_OPS;

SELECT
  source_cloud,
  source_region,
  target_cloud,
  target_region,
  transfer_type,
  SUM(bytes_transferred::NUMBER) AS total_bytes_transferred
FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY
  source_cloud,
  source_region,
  target_cloud,
  target_region,
  transfer_type
ORDER BY total_bytes_transferred DESC;
```
