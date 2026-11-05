-- One row per tailored application packet (resume + cover letter).
with source as (
    select * from {{ source('app', 'applications') }}
),

cleaned as (
    select
        job_id,
        status                          as packet_status,
        outcome,
        tier                            as tier_when_drafted,
        score                           as score_when_drafted,
        base_id                         as base_resume,
        queue_rank,
        (flagged = 1)                   as is_flagged,
        created_at::timestamptz         as created_at,
        updated_at::timestamptz         as updated_at,
        outcome_at::timestamptz         as outcome_at
    from source
)

select * from cleaned
