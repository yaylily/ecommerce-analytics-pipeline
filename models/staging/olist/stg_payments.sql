select
    nullif(order_id, '') as order_id,
    cast(nullif(payment_sequential, '') as integer) as payment_sequential,
    nullif(payment_type, '') as payment_type,
    cast(nullif(payment_installments, '') as integer) as payment_installments,
    cast(nullif(payment_value, '') as numeric) as payment_value
from {{ source('olist_raw', 'payments') }}
