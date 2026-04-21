{{ config(materialized='table') }}

SELECT
    l.pickup_location,
    l.dropoff_location,
    SUM(f.total_revenue) AS revenue,
    SUM(f.total_trips) AS trips
FROM {{ source('taxi_source', 'facts') }} f
JOIN {{ source('taxi_source', 'dim_location') }} l
    ON f.location_key = l.location_key
GROUP BY l.pickup_location, l.dropoff_location
ORDER BY revenue DESC
LIMIT 10
