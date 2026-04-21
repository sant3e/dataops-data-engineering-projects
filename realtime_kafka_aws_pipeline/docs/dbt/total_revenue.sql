{{ config(materialized='table') }}

SELECT
    v.vendor_id,
    SUM(f.total_revenue) AS revenue
FROM {{ source('taxi_source', 'facts') }} f
JOIN {{ source('taxi_source', 'dim_vendor') }} v
    ON f.vendor_key = v.vendor_key
GROUP BY v.vendor_id
ORDER BY revenue DESC
