select
    order_id,
    count(*) as ordered_item_row_count,
    sum(price) as gross_item_value,
    sum(freight_value) as freight_amount,
    sum(price + freight_value) as item_side_amount
from {{ ref('stg_order_items') }}
group by order_id
