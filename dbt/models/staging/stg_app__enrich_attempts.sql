-- One row per posting the scraper tried to fetch a full description for (the latest try).
with source as (
    select * from {{ source('app', 'enrich_attempts') }}
)

select
    source,
    external_id,
    attempted_at::timestamptz           as attempted_at,
    ok                                  as result_code,
    case ok
        when 1 then 'fetched'
        when 0 then 'http_failed'       -- queued for the Chrome task
        when -1 then 'browser_failed'   -- retried after 3 days
    end                                 as result
from source
