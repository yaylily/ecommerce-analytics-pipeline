select
    nullif(customer_id, '') as customer_id,
    nullif(customer_unique_id, '') as customer_unique_id,
    nullif(customer_zip_code_prefix, '') as customer_zip_code_prefix,
    nullif(customer_city, '') as customer_city,
    nullif(customer_state, '') as customer_state
from {{ source('olist_raw', 'customers') }}
