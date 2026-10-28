-- One row per posting per job board, renamed and typed. The long description and raw
-- source JSON stay out until a mart needs them.
with source as (
    select * from {{ source('app', 'jobs') }}
),

cleaned as (
    select
        id                              as job_id,
        source,
        external_id,
        dedup_group_id,
        title,
        -- trimmed, inner runs of spaces squashed, &amp; from HTML decoded
        regexp_replace(trim(replace(company, '&amp;', '&')), '\s+', ' ', 'g') as company,
        location,
        location_category,
        url,
        status,
        tier,
        score,
        years_experience,
        -- Boards write the posted date in several formats (and some only write
        -- "Posted 30+ Days Ago"); read the ones that are dates, leave the rest null.
        case
            when posted_date ~ '^\d{4}-\d{2}-\d{2}'
                then left(posted_date, 10)::date
            when posted_date ~ '^\d{1,2}/\d{1,2}/\d{4}$'
                then to_date(posted_date, 'MM/DD/YYYY')
            when posted_date ~ '^[A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4}'
                then to_date(substring(posted_date from '\d{1,2} [A-Za-z]{3} \d{4}'), 'DD Mon YYYY')
            when posted_date ~ '^[A-Za-z]+ \d{1,2}, \d{4}$'
                then to_date(posted_date, 'FMMonth DD, YYYY')
            when posted_date ~ '^\d{13}$'
                then to_timestamp(posted_date::bigint / 1000.0)::date
        end                             as posted_on,
        posted_date                     as posted_date_raw,
        first_seen::timestamptz         as first_seen_at,
        last_seen::timestamptz          as last_seen_at
    from source
)

select * from cleaned
