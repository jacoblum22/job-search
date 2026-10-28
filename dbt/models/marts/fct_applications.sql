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
    ap.created_at                                       as drafted_at,
    ap.outcome_at,
    (ap.packet_status in ('approved', 'applied') or ap.outcome is not null) as reached_approved,
    (ap.packet_status = 'applied' or ap.outcome is not null)                as reached_applied,
    (ap.outcome in ('callback', 'interview', 'offer'))                       as reached_callback,
    (ap.outcome in ('interview', 'offer'))                                   as reached_interview,
    (ap.outcome = 'offer')                                                   as reached_offer,
    extract(epoch from (ap.created_at - j.first_seen_at)) / 86400.0         as days_seen_to_drafted,
    extract(epoch from (ap.outcome_at - ap.created_at)) / 86400.0           as days_drafted_to_outcome
from applications as ap
join jobs as j using (job_id)
