{{ config(materialized='table') }}

SELECT
    f.trip_date,
    AVG(f.avg_fare) AS avg_daily_fare
FROM {{ source('taxi_source', 'facts') }} f
GROUP BY f.trip_date
ORDER BY f.trip_date
