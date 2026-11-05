with expected as (
    select
        seller_id,
        seller_zip_code_prefix,
        seller_city,
        seller_state
    from {{ ref('stg_sellers') }}
),

actual as (
    select *
    from {{ ref('dim_sellers') }}
)

select coalesce(expected.seller_id, actual.seller_id) as seller_id
from expected
full outer join actual using (seller_id)
where expected.seller_id is null
    or actual.seller_id is null
    or expected.seller_zip_code_prefix
        is distinct from actual.seller_zip_code_prefix
    or expected.seller_city is distinct from actual.seller_city
    or expected.seller_state is distinct from actual.seller_state
