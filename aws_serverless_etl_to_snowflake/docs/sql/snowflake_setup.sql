-- ============================================================
-- CoinGecko ETL Pipeline — Snowflake Setup
-- ============================================================
-- Run these statements in order, top to bottom.
-- Each step builds on the previous one.
--
-- Naming:
--   Database:     COINGECKO_DB
--   Schema:       landing
--   Role:         COINGECKO_DEVELOPER
--   Integration:  S3_COINGECKO_INTEGRATION
--   Stage:        coingecko_stage
--   S3 Bucket:    coingecko-etl-bucket
-- ============================================================


-- ============================================================
-- STEP 1 — Create database, schema, and role
-- ============================================================

USE ROLE ACCOUNTADMIN;

-- 1a. Database
CREATE DATABASE IF NOT EXISTS COINGECKO_DB
    COMMENT = 'CoinGecko cryptocurrency ETL pipeline — landing zone for S3 ingestion';

-- 1b. Schema (all objects live here: tables, stage, pipes, file format)
CREATE SCHEMA IF NOT EXISTS COINGECKO_DB.landing
    COMMENT = 'Landing schema for raw ingested data from the CoinGecko ETL pipeline';

-- 1c. Role for pipeline operations
CREATE ROLE IF NOT EXISTS COINGECKO_DEVELOPER
    COMMENT = 'Owns pipeline objects: stage, file format, pipes, and landing tables';

-- 1d. Grant role privileges
GRANT USAGE ON DATABASE COINGECKO_DB TO ROLE COINGECKO_DEVELOPER;
GRANT USAGE ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;
GRANT CREATE TABLE ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;
GRANT CREATE PIPE ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;
GRANT CREATE STAGE ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;
GRANT CREATE FILE FORMAT ON SCHEMA COINGECKO_DB.landing TO ROLE COINGECKO_DEVELOPER;

-- Grant a warehouse so the role can execute queries
-- Replace COMPUTE_WH with your actual warehouse name
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE COINGECKO_DEVELOPER;

-- Assign the role to your user (replace with your username)
-- GRANT ROLE COINGECKO_DEVELOPER TO USER your_username;


-- ============================================================
-- STEP 2 — Create storage integration
-- ============================================================
-- The storage integration establishes trust between Snowflake
-- and AWS. It creates an IAM role ARN that you configure in AWS
-- to grant Snowflake access to the S3 bucket.
--
-- After creating, run DESC INTEGRATION to get:
--   STORAGE_AWS_IAM_USER_ARN  → the Snowflake IAM user
--   STORAGE_AWS_EXTERNAL_ID   → the external ID for the trust policy
-- Then update the AWS IAM role's trust policy with these values.

USE ROLE ACCOUNTADMIN;

CREATE OR REPLACE STORAGE INTEGRATION S3_COINGECKO_INTEGRATION
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'S3'
    ENABLED = TRUE
    STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::<ACCOUNT_ID>:role/coingecko_snowflake_role'
    STORAGE_ALLOWED_LOCATIONS = ('s3://coingecko-etl-bucket/');

-- Retrieve the values needed for AWS IAM trust policy
DESC INTEGRATION S3_COINGECKO_INTEGRATION;
-- Copy STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID
-- and configure them in the AWS IAM role trust policy.

-- Grant the integration to the pipeline role
GRANT USAGE ON INTEGRATION S3_COINGECKO_INTEGRATION TO ROLE COINGECKO_DEVELOPER;


-- ============================================================
-- STEP 3 — Create file format and external stage
-- ============================================================

USE ROLE COINGECKO_DEVELOPER;

-- 3a. CSV file format
-- PARSE_HEADER = TRUE reads the first row as column names.
-- FIELD_OPTIONALLY_ENCLOSED_BY handles quoted strings in CSVs.
CREATE OR REPLACE FILE FORMAT COINGECKO_DB.landing.ff_csv
    TYPE = CSV
    PARSE_HEADER = TRUE
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    COMMENT = 'CSV format with header parsing for CoinGecko pipeline output';

-- 3b. External stage pointing to the S3 bucket root
-- The stage references the storage integration for authentication.
-- Individual COPY INTO / pipe definitions use subpaths within the stage.
CREATE OR REPLACE STAGE COINGECKO_DB.landing.coingecko_stage
    STORAGE_INTEGRATION = S3_COINGECKO_INTEGRATION
    URL = 's3://coingecko-etl-bucket/'
    COMMENT = 'External stage for CoinGecko ETL pipeline — points to S3 bucket root';

-- Verify the stage can see the transformed data files
LIST @COINGECKO_DB.landing.coingecko_stage/transformed_data/;


-- ============================================================
-- STEP 4 — Create landing tables
-- ============================================================
-- These tables receive appended snapshots on every pipeline run.
-- Each run adds 50 rows per table (one row per coin).
-- The extracted_at column lets you filter by snapshot time.

USE ROLE COINGECKO_DEVELOPER;

-- 4a. coin_data — coin identity and market cap tier classification
CREATE OR REPLACE TABLE COINGECKO_DB.landing.coin_data (
    id              VARCHAR,        -- e.g. "bitcoin"
    symbol          VARCHAR,        -- e.g. "BTC"
    name            VARCHAR,        -- e.g. "Bitcoin"
    market_cap_tier VARCHAR,        -- Small / Mid / Large / Mega
    extracted_at    TIMESTAMP_NTZ   -- when the pipeline ran
);

-- 4b. market_data — market size and liquidity metrics
CREATE OR REPLACE TABLE COINGECKO_DB.landing.market_data (
    id                   VARCHAR,        -- join key to coin_data
    market_cap           NUMBER(38, 2),
    total_volume         NUMBER(38, 2),
    circulating_supply   NUMBER(38, 2),
    volume_to_mcap_ratio FLOAT,          -- liquidity indicator
    extracted_at         TIMESTAMP_NTZ
);

-- 4c. price_data — detailed price information and performance metrics
CREATE OR REPLACE TABLE COINGECKO_DB.landing.price_data (
    id                           VARCHAR,        -- join key to coin_data
    current_price                FLOAT,
    high_24h                     FLOAT,
    low_24h                      FLOAT,
    ath                          FLOAT,          -- all-time high price
    ath_date                     TIMESTAMP_TZ,
    price_change_percentage_24h  FLOAT,
    price_to_ath_ratio           FLOAT,          -- 1.0 = at ATH
    daily_price_range            FLOAT,          -- high_24h - low_24h
    days_since_ath               INTEGER,
    last_updated                 TIMESTAMP_TZ,
    extracted_at                 TIMESTAMP_NTZ
);


-- ============================================================
-- STEP 5 — Create Snowpipes (one per CSV subfolder)
-- ============================================================
-- AUTO_INGEST = TRUE means Snowpipe listens to the SQS queue
-- and automatically loads files as soon as they land in S3.
-- MATCH_BY_COLUMN_NAME ensures CSV headers map to table columns
-- regardless of column order in the file.
--
-- All pipes are created under COINGECKO_DEVELOPER so the pipe
-- owner matches the stage owner. If they differ, Snowpipe throws:
-- "Insufficient privileges to operate on stage 'COINGECKO_STAGE'"

USE ROLE COINGECKO_DEVELOPER;

-- 5a. coin_data pipe
CREATE OR REPLACE PIPE COINGECKO_DB.landing.coin_data_pipe
    AUTO_INGEST = TRUE
    AS
    COPY INTO COINGECKO_DB.landing.coin_data
        FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/coin_data/
        FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

-- 5b. market_data pipe
CREATE OR REPLACE PIPE COINGECKO_DB.landing.market_data_pipe
    AUTO_INGEST = TRUE
    AS
    COPY INTO COINGECKO_DB.landing.market_data
        FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/market_data/
        FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

-- 5c. price_data pipe
CREATE OR REPLACE PIPE COINGECKO_DB.landing.price_data_pipe
    AUTO_INGEST = TRUE
    AS
    COPY INTO COINGECKO_DB.landing.price_data
        FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/price_data/
        FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;


-- ============================================================
-- STEP 6 — Get SQS ARN for S3 event notification
-- ============================================================
-- Each pipe generates a notification_channel ARN.
-- All 3 pipes share the same SQS ARN (one queue per Snowflake account).
-- Snowflake routes messages to the correct pipe based on file path.
--
-- Use this ARN to configure the S3 event notification in AWS:
--   Bucket:      coingecko-etl-bucket
--   Prefix:      transformed_data/
--   Suffix:      .csv
--   Destination: SQS → paste the ARN from the query below

DESC PIPE COINGECKO_DB.landing.coin_data_pipe;
DESC PIPE COINGECKO_DB.landing.market_data_pipe;
DESC PIPE COINGECKO_DB.landing.price_data_pipe;

-- The notification_channel value looks like:
-- arn:aws:sqs:<region>:<snowflake-account-id>:sf-snowpipe-<unique-id>


-- ============================================================
-- STEP 7 — Verify pipe status
-- ============================================================
-- Confirm all pipes are running and the stage owner matches
-- the pipe owner (both should be COINGECKO_DEVELOPER).

SHOW STAGES IN SCHEMA COINGECKO_DB.landing;
SHOW PIPES IN SCHEMA COINGECKO_DB.landing;

-- Healthy pipe status:
-- {"executionState":"RUNNING","pendingFileCount":0}

SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.coin_data_pipe');
SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.market_data_pipe');
SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.price_data_pipe');


-- ============================================================
-- STEP 8 — Force-load files already in S3
-- ============================================================
-- Snowpipe AUTO_INGEST only picks up NEW files created after
-- the pipe was created. Files already sitting in S3 must be
-- loaded manually using FORCE = TRUE to bypass the "already
-- loaded" check. After this one-time load, AUTO_INGEST handles
-- all future files automatically.

USE ROLE COINGECKO_DEVELOPER;

COPY INTO COINGECKO_DB.landing.coin_data
    FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/coin_data/
    FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
    FORCE = TRUE;

COPY INTO COINGECKO_DB.landing.market_data
    FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/market_data/
    FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
    FORCE = TRUE;

COPY INTO COINGECKO_DB.landing.price_data
    FROM @COINGECKO_DB.landing.coingecko_stage/transformed_data/price_data/
    FILE_FORMAT = (FORMAT_NAME = 'COINGECKO_DB.landing.ff_csv')
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
    FORCE = TRUE;


-- ============================================================
-- STEP 9 — Verify data loaded
-- ============================================================

-- Check copy history for errors
SELECT *
FROM TABLE(COINGECKO_DB.information_schema.copy_history(
    TABLE_NAME => 'coin_data',
    START_TIME => DATEADD(minutes, -15, CURRENT_TIMESTAMP())
))
ORDER BY last_load_time DESC;

-- Row counts (50 rows per pipeline run)
SELECT COUNT(*) FROM COINGECKO_DB.landing.coin_data;
SELECT COUNT(*) FROM COINGECKO_DB.landing.market_data;
SELECT COUNT(*) FROM COINGECKO_DB.landing.price_data;

-- Latest snapshot: top 10 coins with full details across all 3 tables
-- Join key: id + extracted_at (ensures rows from the same snapshot are joined)
SELECT
    c.id,
    c.name,
    c.symbol,
    c.market_cap_tier,
    m.market_cap,
    m.total_volume,
    p.current_price,
    p.price_change_percentage_24h,
    p.price_to_ath_ratio,
    p.days_since_ath,
    c.extracted_at
FROM COINGECKO_DB.landing.coin_data c
JOIN COINGECKO_DB.landing.market_data m
    ON c.id = m.id AND c.extracted_at = m.extracted_at
JOIN COINGECKO_DB.landing.price_data p
    ON c.id = p.id AND c.extracted_at = p.extracted_at
WHERE c.extracted_at = (SELECT MAX(extracted_at) FROM COINGECKO_DB.landing.coin_data)
ORDER BY m.market_cap DESC
LIMIT 10;


-- ============================================================
-- PAUSE — Stop ingestion when not in use
-- ============================================================
-- Snowpipe charges per file loaded (not for idle listening).
-- Pausing pipes stops ingestion without dropping them.
-- Remember to also disable the EventBridge scheduler in AWS
-- to stop new files from being generated into S3.
--
-- Cost note:
--   - Idle pipes = no credits consumed
--   - Each pipeline run loads 3 CSVs ≈ 0.18 Snowflake credits
--   - Main cost driver is the EventBridge schedule, not the pipes

USE ROLE COINGECKO_DEVELOPER;

ALTER PIPE COINGECKO_DB.landing.coin_data_pipe SET PIPE_EXECUTION_PAUSED = TRUE;
ALTER PIPE COINGECKO_DB.landing.market_data_pipe SET PIPE_EXECUTION_PAUSED = TRUE;
ALTER PIPE COINGECKO_DB.landing.price_data_pipe SET PIPE_EXECUTION_PAUSED = TRUE;

-- Verify paused
SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.coin_data_pipe');
-- Expected: {"executionState":"PAUSED",...}


-- ============================================================
-- RESUME — Restart ingestion
-- ============================================================
-- After resuming, run ALTER PIPE REFRESH to catch up on any
-- files that landed in S3 while the pipes were paused.

USE ROLE COINGECKO_DEVELOPER;

ALTER PIPE COINGECKO_DB.landing.coin_data_pipe SET PIPE_EXECUTION_PAUSED = FALSE;
ALTER PIPE COINGECKO_DB.landing.market_data_pipe SET PIPE_EXECUTION_PAUSED = FALSE;
ALTER PIPE COINGECKO_DB.landing.price_data_pipe SET PIPE_EXECUTION_PAUSED = FALSE;

-- Catch up on files that arrived while paused
ALTER PIPE COINGECKO_DB.landing.coin_data_pipe REFRESH;
ALTER PIPE COINGECKO_DB.landing.market_data_pipe REFRESH;
ALTER PIPE COINGECKO_DB.landing.price_data_pipe REFRESH;

-- Verify running
SELECT SYSTEM$PIPE_STATUS('COINGECKO_DB.landing.coin_data_pipe');
-- Expected: {"executionState":"RUNNING","pendingFileCount":0}
