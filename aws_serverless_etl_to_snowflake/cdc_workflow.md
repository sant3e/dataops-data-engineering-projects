# CDC Workflow: Streams, Tasks & MERGE Upsert

Snowflake-native Change Data Capture (CDC) layer that sits on top of the Snowpipe ingestion pipeline.

**Pattern:** Staging Table → Stream (tracks new rows) → Task (scheduled MERGE) → Final Table

```
Snowpipe loads CSV into STAGING tables
                │
             Streams
             (auto-track new inserts)
                │
             Tasks (run every 10 minutes)
             MERGE on unique key (id)
                │
             FINAL tables (source of truth — one row per coin, latest values)
```

---

## Prerequisites

Grant additional privileges to the pipeline role (add to Step 1d in `snowflake_setup.sql`):

```sql
USE ROLE ACCOUNTADMIN;

GRANT CREATE STREAM ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;
GRANT CREATE TASK ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;
GRANT EXECUTE TASK ON ACCOUNT TO ROLE COINGECKO_DEVELOPER;
```

---

## Step 1: Create Staging Tables

The existing landing tables become the **final** tables (source of truth).
Create matching staging tables as the new Snowpipe target.

```sql
USE ROLE COINGECKO_DEVELOPER;

CREATE OR REPLACE TABLE COINGECKO_DB.landing.coin_data_staging
    LIKE COINGECKO_DB.landing.coin_data;

CREATE OR REPLACE TABLE COINGECKO_DB.landing.market_data_staging
    LIKE COINGECKO_DB.landing.market_data;

CREATE OR REPLACE TABLE COINGECKO_DB.landing.price_data_staging
    LIKE COINGECKO_DB.landing.price_data;
```

Then update the Snowpipes to load into staging instead of final:

```sql
USE ROLE COINGECKO_DEVELOPER;

CREATE OR REPLACE PIPE COINGECKO_DB.landing.coin_data_pipe
    AUTO_INGEST = TRUE
    AS
    COPY INTO COINGECKO_DB.landing.coin_data_staging
        FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/coin_data/
        FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

CREATE OR REPLACE PIPE COINGECKO_DB.landing.market_data_pipe
    AUTO_INGEST = TRUE
    AS
    COPY INTO COINGECKO_DB.landing.market_data_staging
        FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/market_data/
        FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

CREATE OR REPLACE PIPE COINGECKO_DB.landing.price_data_pipe
    AUTO_INGEST = TRUE
    AS
    COPY INTO COINGECKO_DB.landing.price_data_staging
        FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/price_data/
        FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;
```

> After recreating the pipes, re-retrieve the SQS ARN with `DESC PIPE` — it may change.

---

## Step 2: Create Streams on Staging Tables

Streams automatically track new rows (inserts/updates/deletes) landing in a table. No polling needed — Snowflake manages the offset internally.

```sql
USE ROLE COINGECKO_DEVELOPER;

CREATE OR REPLACE STREAM COINGECKO_DB.landing.coin_data_stream
    ON TABLE COINGECKO_DB.landing.coin_data_staging;

CREATE OR REPLACE STREAM COINGECKO_DB.landing.market_data_stream
    ON TABLE COINGECKO_DB.landing.market_data_staging;

CREATE OR REPLACE STREAM COINGECKO_DB.landing.price_data_stream
    ON TABLE COINGECKO_DB.landing.price_data_staging;
```

Once created, each stream exposes three metadata columns on every row:
- `METADATA$ACTION` — INSERT, DELETE
- `METADATA$ISUPDATE` — TRUE if the row is part of an UPDATE
- `METADATA$ROW_ID` — Unique row identifier

---

## Step 3: Create Tasks with MERGE

Each task runs on a schedule but **only fires when its stream has new data** (zero-cost when idle). The MERGE uses `id` as the unique key — existing coins get updated, new coins get inserted.

```sql
USE ROLE COINGECKO_DEVELOPER;

-- 3a. coin_data task
CREATE OR REPLACE TASK COINGECKO_DB.landing.merge_coin_data
    WAREHOUSE = 'COMPUTE_WH'
    SCHEDULE = '10 MINUTE'
    WHEN SYSTEM$STREAM_HAS_DATA('COINGECKO_DB.landing.coin_data_stream')
AS
    MERGE INTO COINGECKO_DB.landing.coin_data AS target
    USING COINGECKO_DB.landing.coin_data_stream AS source
    ON target.id = source.id
    WHEN MATCHED THEN UPDATE SET
        symbol          = source.symbol,
        name            = source.name,
        market_cap_tier = source.market_cap_tier,
        extracted_at    = source.extracted_at
    WHEN NOT MATCHED THEN INSERT (
        id, symbol, name, market_cap_tier, extracted_at
    ) VALUES (
        source.id, source.symbol, source.name,
        source.market_cap_tier, source.extracted_at
    );

-- 3b. market_data task
CREATE OR REPLACE TASK COINGECKO_DB.landing.merge_market_data
    WAREHOUSE = 'COMPUTE_WH'
    SCHEDULE = '10 MINUTE'
    WHEN SYSTEM$STREAM_HAS_DATA('COINGECKO_DB.landing.market_data_stream')
AS
    MERGE INTO COINGECKO_DB.landing.market_data AS target
    USING COINGECKO_DB.landing.market_data_stream AS source
    ON target.id = source.id
    WHEN MATCHED THEN UPDATE SET
        market_cap           = source.market_cap,
        total_volume         = source.total_volume,
        circulating_supply   = source.circulating_supply,
        volume_to_mcap_ratio = source.volume_to_mcap_ratio,
        extracted_at         = source.extracted_at
    WHEN NOT MATCHED THEN INSERT (
        id, market_cap, total_volume, circulating_supply,
        volume_to_mcap_ratio, extracted_at
    ) VALUES (
        source.id, source.market_cap, source.total_volume,
        source.circulating_supply, source.volume_to_mcap_ratio,
        source.extracted_at
    );

-- 3c. price_data task
CREATE OR REPLACE TASK COINGECKO_DB.landing.merge_price_data
    WAREHOUSE = 'COMPUTE_WH'
    SCHEDULE = '10 MINUTE'
    WHEN SYSTEM$STREAM_HAS_DATA('COINGECKO_DB.landing.price_data_stream')
AS
    MERGE INTO COINGECKO_DB.landing.price_data AS target
    USING COINGECKO_DB.landing.price_data_stream AS source
    ON target.id = source.id
    WHEN MATCHED THEN UPDATE SET
        current_price               = source.current_price,
        high_24h                    = source.high_24h,
        low_24h                     = source.low_24h,
        ath                         = source.ath,
        ath_date                    = source.ath_date,
        price_change_percentage_24h = source.price_change_percentage_24h,
        price_to_ath_ratio          = source.price_to_ath_ratio,
        daily_price_range           = source.daily_price_range,
        days_since_ath              = source.days_since_ath,
        last_updated                = source.last_updated,
        extracted_at                = source.extracted_at
    WHEN NOT MATCHED THEN INSERT (
        id, current_price, high_24h, low_24h, ath, ath_date,
        price_change_percentage_24h, price_to_ath_ratio,
        daily_price_range, days_since_ath, last_updated, extracted_at
    ) VALUES (
        source.id, source.current_price, source.high_24h, source.low_24h,
        source.ath, source.ath_date, source.price_change_percentage_24h,
        source.price_to_ath_ratio, source.daily_price_range,
        source.days_since_ath, source.last_updated, source.extracted_at
    );
```

Tasks are created in a **suspended** state — enable them explicitly:

```sql
ALTER TASK COINGECKO_DB.landing.merge_coin_data RESUME;
ALTER TASK COINGECKO_DB.landing.merge_market_data RESUME;
ALTER TASK COINGECKO_DB.landing.merge_price_data RESUME;
```

---

## Verification

```sql
-- Check streams have pending data
SELECT SYSTEM$STREAM_HAS_DATA('COINGECKO_DB.landing.coin_data_stream');
SELECT SYSTEM$STREAM_HAS_DATA('COINGECKO_DB.landing.market_data_stream');
SELECT SYSTEM$STREAM_HAS_DATA('COINGECKO_DB.landing.price_data_stream');

-- Check task states (should show "started")
SHOW TASKS IN COINGECKO_DB.LANDING;

-- Check task execution history (last hour)
SELECT *
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
    TASK_NAME => 'MERGE_COIN_DATA',
    SCHEDULED_TIME_RANGE_START => DATEADD('HOUR', -1, CURRENT_TIMESTAMP())
));

-- Compare row counts between staging and final
SELECT 'coin_data_staging' AS tbl, COUNT(*) AS rows FROM COINGECKO_DB.landing.coin_data_staging
UNION ALL
SELECT 'coin_data', COUNT(*) FROM COINGECKO_DB.landing.coin_data
UNION ALL
SELECT 'market_data_staging', COUNT(*) FROM COINGECKO_DB.landing.market_data_staging
UNION ALL
SELECT 'market_data', COUNT(*) FROM COINGECKO_DB.landing.market_data
UNION ALL
SELECT 'price_data_staging', COUNT(*) FROM COINGECKO_DB.landing.price_data_staging
UNION ALL
SELECT 'price_data', COUNT(*) FROM COINGECKO_DB.landing.price_data;
```

---

## How Corrections Work

| Scenario | What happens |
|----------|-------------|
| New file uploaded (new coin IDs) | Snowpipe → staging → Stream → Task MERGE → **INSERT** into final |
| Corrected file uploaded (existing coin IDs, different filename) | Snowpipe → staging → Stream → Task MERGE → **UPDATE** in final |
| Same filename re-uploaded | Snowpipe **ignores it** (tracks loaded files for 14 days). Delete from S3 first, re-upload with a different name |

### Correction workflow:

1. Upload corrected file with a **different name** (e.g. `coin_data_20250115_corrected.csv`)
2. Snowpipe auto-ingests it into staging via SQS
3. Stream detects the new rows
4. Task fires within 10 minutes
5. MERGE matches on `id` → existing coins get **updated**, new coins get **inserted**
6. Final table reflects corrected data — no duplicates, no manual intervention

---

## Cleanup / Teardown

Run in this order (tasks must be suspended before they can be dropped):

```sql
USE ROLE COINGECKO_DEVELOPER;

-- Suspend and drop tasks
ALTER TASK COINGECKO_DB.landing.merge_coin_data SUSPEND;
ALTER TASK COINGECKO_DB.landing.merge_market_data SUSPEND;
ALTER TASK COINGECKO_DB.landing.merge_price_data SUSPEND;

DROP TASK COINGECKO_DB.landing.merge_coin_data;
DROP TASK COINGECKO_DB.landing.merge_market_data;
DROP TASK COINGECKO_DB.landing.merge_price_data;

-- Drop streams
DROP STREAM COINGECKO_DB.landing.coin_data_stream;
DROP STREAM COINGECKO_DB.landing.market_data_stream;
DROP STREAM COINGECKO_DB.landing.price_data_stream;

-- Drop pipes
DROP PIPE COINGECKO_DB.landing.coin_data_pipe;
DROP PIPE COINGECKO_DB.landing.market_data_pipe;
DROP PIPE COINGECKO_DB.landing.price_data_pipe;

-- Drop staging tables
DROP TABLE COINGECKO_DB.landing.coin_data_staging;
DROP TABLE COINGECKO_DB.landing.market_data_staging;
DROP TABLE COINGECKO_DB.landing.price_data_staging;

-- Drop final tables
DROP TABLE COINGECKO_DB.landing.coin_data;
DROP TABLE COINGECKO_DB.landing.market_data;
DROP TABLE COINGECKO_DB.landing.price_data;

-- Drop stage and file format
DROP STAGE COINGECKO_DB.landing.coingecko_stage;
DROP FILE FORMAT COINGECKO_DB.landing.ff_csv;

-- Drop storage integration (requires ACCOUNTADMIN)
USE ROLE ACCOUNTADMIN;
DROP INTEGRATION S3_COINGECKO_INTEGRATION;
```

Then in AWS: remove the S3 event notification and delete the IAM role (`coingecko_snowflake_role`).
