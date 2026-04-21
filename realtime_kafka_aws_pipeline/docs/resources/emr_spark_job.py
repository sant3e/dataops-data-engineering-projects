"""
NYC Green Taxi — Dimensional Modelling (Star Schema) via PySpark on EMR
=======================================================================
Reads the refined CSV data from S3 and builds a star schema:
  - 3 dimension tables: dim_vendor, dim_location, dim_payment
  - 1 fact table: fact_trips (aggregated by vendor, payment, location, date)

The output is written as Parquet files to the Business/ folder in S3.

Star Schema Overview:
  fact_trips (center) references:
    → dim_vendor   (via vendor_key)
    → dim_location (via location_key)
    → dim_payment  (via payment_key)
    → trip_date    (date dimension, inline — no separate dim table)

Usage:
  Submitted as a PySpark job to EMR Serverless via Step Functions.

Note on fact table design:
  This script aggregates the fact table (groupBy + agg). In classical Kimball
  dimensional modelling, fact tables store the most granular data (one row per
  event/transaction) and aggregations happen downstream in marts or BI tools.
  The trainer chose to pre-aggregate here as a tutorial simplification. In a
  production system, you'd typically keep fact_trips at the individual trip
  grain and build aggregate tables on top.
"""

from pyspark.sql import SparkSession

# col: reference a column by name (used in expressions like col("pickup_datetime"))
# sum/avg/count: aggregation functions for the fact table
# to_date: extracts the date portion from a datetime string (e.g. "2026-04-16 11:48:15" → "2026-04-16")
# monotonically_increasing_id: generates unique integer IDs across partitions (used as surrogate keys)
from pyspark.sql.functions import col, sum as _sum, avg, count, to_date, monotonically_increasing_id

# --- Spark Session ---
# Entry point for all PySpark operations. EMR provides the cluster; we just name our app.
spark = SparkSession.builder.appName("TaxiETL").getOrCreate()

# --- I/O Paths ---
# UPDATE THESE for your environment:
input_path = "s3://ridestreamlakehouse-td/Refined/run-*"                   # Refined CSV from Glue job
dim_output = "s3://ridestreamlakehouse-td/Business/processed/dimensions/"   # Dimension tables output
fact_output = "s3://ridestreamlakehouse-td/Business/processed/facts/"       # Fact table output

# --- Read Refined Data ---
# Reads all CSV files matching the glob pattern. header=True uses the first row as column names.
# inferSchema=True lets Spark detect column types (int, double, string) instead of treating everything as string.
df = spark.read.csv(input_path, header=True, inferSchema=True)


# =============================================================================
# STEP 1: Dimension Tables
# =============================================================================
# Dimensions contain descriptive attributes. Each gets a surrogate key — an
# auto-generated integer that replaces the natural key (e.g. "Credit card" → 42).
# Surrogate keys make joins faster (integer comparison vs string) and decouple
# the warehouse from source system key changes.
#
# monotonically_increasing_id() generates unique 64-bit integers. They are
# guaranteed unique but NOT sequential (they encode partition ID + row number).
# Fine for surrogate keys; not suitable for ordering.
# =============================================================================

# --- dim_vendor ---
# One row per unique vendor_id (1 or 2 in our data).
# Columns: vendor_id, vendor_key (surrogate)
dim_vendor = (
    df.select("vendor_id").distinct()
      .withColumn("vendor_key", monotonically_increasing_id())
)
dim_vendor.write.mode("overwrite").parquet(dim_output + "dim_vendor/")

# --- dim_location ---
# One row per unique combination of pickup + dropoff borough and location.
# Columns: pickup_city, pickup_location, dropoff_city, dropoff_location, location_key (surrogate)
dim_location = (
    df.select("pickup_city", "pickup_location", "dropoff_city", "dropoff_location")
      .distinct()
      .withColumn("location_key", monotonically_increasing_id())
)
dim_location.write.mode("overwrite").parquet(dim_output + "dim_location/")

# --- dim_payment ---
# One row per unique payment type (Credit card, Cash, etc.).
# Columns: payment_type, payment_key (surrogate)
dim_payment = (
    df.select("payment_type").distinct()
      .withColumn("payment_key", monotonically_increasing_id())
)
dim_payment.write.mode("overwrite").parquet(dim_output + "dim_payment/")


# =============================================================================
# STEP 2: Fact Table
# =============================================================================
# The fact table links dimensions together and contains the measurable metrics
# (revenue, distance, fares, trip count). Each row represents an aggregated
# group of trips for a given vendor + payment + location + date combination.
# =============================================================================

# Add a trip_date column — extracts just the date from the full pickup_datetime timestamp.
# This gives us our time dimension for grouping/filtering by day.
df = df.withColumn("trip_date", to_date(col("pickup_datetime")))

# Join the main dataframe with each dimension table to replace natural keys
# with surrogate keys. Left joins ensure we keep all trips even if a dimension
# lookup fails (shouldn't happen with our data, but defensive practice).
fact_trips = (
    df
    # Join dim_vendor: match on vendor_id → get vendor_key
    .join(dim_vendor, "vendor_id", "left")

    # Join dim_payment: match on payment_type → get payment_key
    .join(dim_payment, "payment_type", "left")

    # Join dim_location: match on all 4 location columns → get location_key
    # Multi-column join because location is defined by the combination of
    # pickup borough + pickup neighborhood + dropoff borough + dropoff neighborhood
    .join(dim_location,
          (df.pickup_city == dim_location.pickup_city) &
          (df.pickup_location == dim_location.pickup_location) &
          (df.dropoff_city == dim_location.dropoff_city) &
          (df.dropoff_location == dim_location.dropoff_location),
          "left"
    )

    # Group by the surrogate keys + date — this is the grain of our fact table.
    # Each row = one vendor + payment method + location pair + date
    .groupBy("vendor_key", "payment_key", "location_key", "trip_date")

    # Aggregate the metrics for each group:
    .agg(
        count("*").alias("total_trips"),              # How many trips in this group
        _sum("total_amount").alias("total_revenue"),   # Sum of all fares
        avg("trip_distance").alias("avg_distance"),    # Average trip distance
        avg("fare_amount").alias("avg_fare"),          # Average base fare
        _sum("tolls_amount").alias("total_tolls")      # Sum of tolls (fixed: was tip_amount which doesn't exist in our data)
    )
)

# Write as Parquet — columnar format, compressed, fast for analytics queries.
# mode("overwrite") replaces any existing data from previous runs.
# partitionBy("trip_date") creates Hive-style partitions — each date gets its own
# subfolder (fact_trips/trip_date=2026-04-16/part-*.parquet). The Glue Crawler
# registers `trip_date` as a real partition column, so Athena can use partition
# pruning: a query with WHERE trip_date = '2026-04-16' scans only that one
# folder instead of the whole fact table.
fact_trips.write.mode("overwrite").partitionBy("trip_date").parquet(fact_output + "fact_trips/")

print("Dimensions and facts with surrogate keys written to S3")
