#!/usr/bin/env bash
# Upload Kaggle YouTube trending dataset to the S3 Bronze bucket.
#
# Derives the Bronze bucket name from your AWS account ID:
#   yt-data-pipeline-bronze-<ACCOUNT_ID>-dev
# (matching the naming convention from Step 1.1 of aws_pipeline.md)

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BRONZE_BUCKET="yt-data-pipeline-bronze-${ACCOUNT_ID}-dev"

echo "Uploading Kaggle dataset to s3://${BRONZE_BUCKET}/youtube/..."

# Upload JSON category reference files, partitioned by region (Hive-style)
aws s3 cp CA_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=ca/
aws s3 cp DE_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=de/
aws s3 cp FR_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=fr/
aws s3 cp GB_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=gb/
aws s3 cp IN_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=in/
aws s3 cp JP_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=jp/
aws s3 cp KR_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=kr/
aws s3 cp MX_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=mx/
aws s3 cp RU_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=ru/
aws s3 cp US_category_id.json s3://${BRONZE_BUCKET}/youtube/raw_statistics_reference_data/region=us/

# Upload CSV statistics files, partitioned by region (Hive-style)
aws s3 cp CAvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=ca/
aws s3 cp DEvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=de/
aws s3 cp FRvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=fr/
aws s3 cp GBvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=gb/
aws s3 cp INvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=in/
aws s3 cp JPvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=jp/
aws s3 cp KRvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=kr/
aws s3 cp MXvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=mx/
aws s3 cp RUvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=ru/
aws s3 cp USvideos.csv s3://${BRONZE_BUCKET}/youtube/raw_statistics/region=us/

echo "Done."
