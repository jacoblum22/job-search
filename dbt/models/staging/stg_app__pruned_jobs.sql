-- One row per posting the cleanup deleted (only its board and the board's id survive).
with source as (
    select * from {{ source('app', 'pruned_jobs') }}
)

select
    source,
    external_id,
    pruned_at::timestamptz              as pruned_at
from source
