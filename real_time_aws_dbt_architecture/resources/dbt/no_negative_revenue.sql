-- Singular test: checks no fact rows have negative total_revenue
-- Returns rows with negative revenue — any returned rows = FAIL
SELECT *
FROM {{ source('taxi_source', 'facts') }} f
WHERE total_revenue < 0
