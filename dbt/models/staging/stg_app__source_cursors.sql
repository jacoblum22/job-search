-- One row per saved setting. The two scrape summaries (aggregate:last_run and
-- aggregate:last_full_run) are JSON; their fields are pulled out, other rows leave them null.
with source as (
    select
        *,
        case when source like 'aggregate:%' then {{ parse_json('cursor_value') }} end as summary
    from {{ source('app', 'source_cursors') }}
)

select
    source                              as cursor_name,
    cursor_value,
    updated_at::timestamptz             as updated_at,
    {{ json_text('summary', 'started') }}::timestamptz    as run_started_at,
    {{ json_text('summary', 'finished') }}::timestamptz   as run_finished_at,
    {{ json_text('summary', 'host') }}                  as run_host,
    {{ json_text('summary', 'full') }}::boolean       as run_was_full,
    {{ json_text('summary', 'fetched') }}::int        as jobs_fetched,
    {{ json_text('summary', 'new') }}::int            as jobs_new,
    {{ json_text('summary', 'minutes') }}::numeric(10, 2) as run_minutes,
    {{ json_field('summary', 'tiers') }}                  as tier_counts,
    {{ json_field('summary', 'sources') }}                as source_counts
from source
