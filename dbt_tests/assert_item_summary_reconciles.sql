with expected as (
    select
        order_id,
        count(*) as ordered_item_row_count,
        sum(price) as gross_item_value,
        sum(freight_value) as freight_amount,
        sum(price + freight_value) as item_side_amount
    from {{ ref('stg_order_items') }}
    group by order_id
),

actual as (
    select *
    from {{ ref('int_order_item_amount_summary') }}
)

select coalesce(expected.order_id, actual.order_id) as order_id
from expected
full outer join actual using (order_id)
where expected.order_id is null
    or actual.order_id is null
    or expected.ordered_item_row_count
        is distinct from actual.ordered_item_row_count
    or expected.gross_item_value is distinct from actual.gross_item_value
    or expected.freight_amount is distinct from actual.freight_amount
    or expected.item_side_amount is distinct from actual.item_side_amount
