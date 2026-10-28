select
    nullif(seller_id, '') as seller_id,
    nullif(seller_zip_code_prefix, '') as seller_zip_code_prefix,
    nullif(seller_city, '') as seller_city,
    nullif(seller_state, '') as seller_state
from {{ source('olist_raw', 'sellers') }}
