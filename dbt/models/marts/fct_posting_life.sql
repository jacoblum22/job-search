-- One row per posting per board that the snapshot has ever seen, including ones
-- the cleanup has since deleted. History starts on the snapshot's first prod run
-- (Oct 28 2026): postings deleted before then are gone.
with versions as (
    select
        *,
        row_number() over (
            partition by source, external_id order by dbt_valid_from desc
        ) as newest_first,
        count(*) over (partition by source, external_id) as version_count,
        -- the same tidying staging does, so names match the seed
        {{ regex_replace_all("trim(replace(company, '&amp;', '&'))", '\s+', ' ') }} as company_tidy
    from {{ ref('jobs_snapshot') }}
),

latest as (
    select * from versions where newest_first = 1
)

select
    l.source || ':' || l.external_id                    as posting_board_id,
    l.source,
    l.external_id,
    l.id                                                as job_id,
    l.dedup_group_id                                    as posting_id,
    l.title,
    coalesce(a.canonical, l.company_tidy)               as company,
    l.location_category,
    l.tier                                              as last_tier,
    l.score                                             as last_score,
    l.status                                            as last_status,
    l.first_seen::timestamptz                           as first_seen_at,
    {{ date_in_zone('l.first_seen::timestamptz', 'UTC') }} as first_seen_on,
    l.last_seen::timestamptz                            as last_seen_at,
    -- set when the posting left the app's table (the cleanup deleted it)
    l.dbt_valid_to                                      as removed_at,
    (l.dbt_valid_to is null)                            as is_open,
    {{ days_between('l.first_seen::timestamptz',
                    'coalesce(l.dbt_valid_to::timestamptz, current_timestamp)') }} as days_listed,
    l.version_count - 1                                 as change_count
from latest as l
left join {{ ref('company_aliases') }} as a on a.alias = l.company_tidy
