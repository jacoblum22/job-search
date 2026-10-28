-- One row per saved setting. The two scrape summaries (aggregate:last_run and
-- aggregate:last_full_run) are JSON; their fields are pulled out, other rows leave them null.
with source as (
    select
        *,
        case when source like 'aggregate:%' then cursor_value::jsonb end as summary
    from {{ source('app', 'source_cursors') }}
)

select
    source                              as cursor_name,
    cursor_value,
    updated_at::timestamptz             as updated_at,
    (summary ->> 'started')::timestamptz    as run_started_at,
    (summary ->> 'finished')::timestamptz   as run_finished_at,
    summary ->> 'host'                  as run_host,
    (summary ->> 'full')::boolean       as run_was_full,
    (summary ->> 'fetched')::int        as jobs_fetched,
    (summary ->> 'new')::int            as jobs_new,
    (summary ->> 'minutes')::numeric    as run_minutes,
    summary -> 'tiers'                  as tier_counts,
    summary -> 'sources'                as source_counts
from source
