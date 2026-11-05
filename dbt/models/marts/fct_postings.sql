-- One row per posting open today, with the same job on several boards merged into
-- one row (the app's dedup group). Mirrors how the dashboard groups rows: the copy
-- with the longest description supplies the details, the strongest status wins
-- (applied > dismissed > expired > new), and the earliest date any board gives is
-- the posted date (else the day it was first seen).
with jobs as (
    select
        j.*,
        coalesce(a.canonical, j.company) as company_name,
        row_number() over (
            partition by j.dedup_group_id
            -- ties: the newest copy, as the dashboard's newest-first order does
            order by j.description_length desc nulls last, j.first_seen_at desc, j.job_id desc
        ) as copy_rank
    from {{ ref('stg_app__jobs') }} as j
    left join {{ ref('company_aliases') }} as a on a.alias = j.company
),

groups as (
    select
        dedup_group_id,
        count(*)                                        as board_count,
        {{ join_distinct('source', ', ') }}         as boards,
        min(first_seen_at)                              as first_seen_at,
        max(last_seen_at)                               as last_seen_at,
        min(posted_on)                                  as earliest_posted_on,
        max(case status
                when 'applied' then 3
                when 'dismissed' then 2
                when 'expired' then 1
                else 0
            end)                                        as status_rank,
        max(years_experience)                           as any_years_experience
    from jobs
    group by dedup_group_id
),

applications as (
    select distinct j.dedup_group_id
    from {{ ref('stg_app__applications') }} as a
    join {{ ref('stg_app__jobs') }} as j using (job_id)
)

select
    p.dedup_group_id                                    as posting_id,
    p.job_id                                            as primary_job_id,
    p.title,
    p.company_name                                      as company,
    p.company                                           as company_as_posted,
    p.location,
    p.location_category,
    p.tier,
    p.score,
    coalesce(p.years_experience, g.any_years_experience) as years_experience,
    case g.status_rank
        when 3 then 'applied'
        when 2 then 'dismissed'
        when 1 then 'expired'
        else 'new'
    end                                                 as status,
    coalesce(g.earliest_posted_on, {{ date_in_zone('g.first_seen_at', 'UTC') }}) as posted_on,
    (g.earliest_posted_on is not null)                  as posted_date_given,
    {{ date_in_zone('g.first_seen_at', 'UTC') }}          as first_seen_on,
    g.first_seen_at,
    g.last_seen_at,
    g.board_count,
    g.boards,
    (ap.dedup_group_id is not null)                     as has_application
from jobs as p
join groups as g using (dedup_group_id)
left join applications as ap using (dedup_group_id)
where p.copy_rank = 1
