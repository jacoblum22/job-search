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
        {{ regex_replace_all("trim(replace(company, '&amp;', '&'))", '\s+', ' ') }} as company,
        location,
        location_category,
        url,
        status,
        tier,
        score,
        years_experience,
        length(description)             as description_length,
        -- Boards write the posted date in several formats (and some only write
        -- "Posted 30+ Days Ago"); read the ones that are dates, leave the rest null.
        case
            when {{ regex_found('posted_date', '^\d{4}-\d{2}-\d{2}') }}
                then left(posted_date, 10)::date
            when {{ regex_found('posted_date', '^\d{1,2}/\d{1,2}/\d{4}$') }}
                then {{ parse_date('posted_date', 'MM/DD/YYYY', 'MM/DD/YYYY') }}
            when {{ regex_found('posted_date', '^[A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4}') }}
                then {{ parse_date(regex_first('posted_date', '\d{1,2} [A-Za-z]{3} \d{4}'), 'DD Mon YYYY', 'DD MON YYYY') }}
            when {{ regex_found('posted_date', '^[A-Za-z]+ \d{1,2}, \d{4}$') }}
                then {{ parse_date('posted_date', 'FMMonth DD, YYYY', 'MMMM DD, YYYY') }}
            when {{ regex_found('posted_date', '^\d{13}$') }}
                then {{ epoch_ms_to_date('posted_date') }}
        end                             as posted_on,
        posted_date                     as posted_date_raw,
        first_seen::timestamptz         as first_seen_at,
        last_seen::timestamptz          as last_seen_at
    from source
)

select * from cleaned
