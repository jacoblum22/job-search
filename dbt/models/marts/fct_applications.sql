-- One row per tailored application packet, with its job and how far it got.
-- outcome is the latest one recorded, so each step below counts the packets that
-- reached it or went further.
with applications as (
    select * from {{ ref('stg_app__applications') }}
),

jobs as (
    select
        j.job_id,
        j.dedup_group_id,
        j.source,
        j.title,
        coalesce(a.canonical, j.company) as company,
        j.location_category,
        j.tier,
        -- the first time any board showed the job (a later board's copy can be the
        -- one the packet was made from)
        min(j.first_seen_at) over (partition by j.dedup_group_id) as first_seen_at
    from {{ ref('stg_app__jobs') }} as j
    left join {{ ref('company_aliases') }} as a on a.alias = j.company
)

select
    ap.job_id,
    j.dedup_group_id                                    as posting_id,
    j.source,
    j.title,
    j.company,
    j.location_category,
    j.tier                                              as tier_now,
    ap.tier_when_drafted,
    ap.score_when_drafted,
    ap.base_resume,
    ap.packet_status,
    ap.outcome,
    ap.is_flagged,
    -- the app stores the drafting day only (desktop local date), no time
    {{ date_in_zone('ap.created_at', 'UTC') }}            as drafted_on,
    ap.outcome_at,
    (ap.packet_status in ('approved', 'applied') or ap.outcome is not null) as reached_approved,
    (ap.packet_status = 'applied' or ap.outcome is not null)                as reached_applied,
    (ap.outcome in ('callback', 'interview', 'offer'))                       as reached_callback,
    (ap.outcome in ('interview', 'offer'))                                   as reached_interview,
    (ap.outcome = 'offer')                                                   as reached_offer,
    {{ dbt.datediff(date_in_zone('j.first_seen_at', 'America/Vancouver'),
                    date_in_zone('ap.created_at', 'UTC'), 'day') }}             as days_seen_to_drafted,
    {{ dbt.datediff(date_in_zone('ap.created_at', 'UTC'),
                    date_in_zone('ap.outcome_at', 'America/Vancouver'), 'day') }} as days_drafted_to_outcome
from applications as ap
join jobs as j using (job_id)
