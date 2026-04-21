{{ config(materialized='table') }}

SELECT
    p.payment_type,
    SUM(f.total_revenue) AS revenue
FROM {{ source('taxi_source', 'facts') }} f
JOIN {{ source('taxi_source', 'dim_payment') }} p
    ON f.payment_key = p.payment_key
GROUP BY p.payment_type
ORDER BY revenue DESC
