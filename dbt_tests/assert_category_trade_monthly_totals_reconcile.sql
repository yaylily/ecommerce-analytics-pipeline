with expected as (
    select
        count(*) as ordered_item_row_count,
        sum(price) as gross_item_value,
        sum(freight_value) as freight_amount,
        sum(item_side_amount) as item_side_amount,
        count(distinct (purchase_month, order_id, category_key))
            as category_order_association_count
    from {{ ref('fct_order_items') }}
    where order_status = 'delivered'
),

actual as (
    select
        sum(ordered_item_row_count) as ordered_item_row_count,
        sum(gross_item_value) as gross_item_value,
        sum(freight_amount) as freight_amount,
        sum(item_side_amount) as item_side_amount,
        sum(associated_order_count) as category_order_association_count
    from {{ ref('mart_category_trade_monthly') }}
)

select 1 as reconciliation_failure
from expected
cross join actual
where expected.ordered_item_row_count
        is distinct from actual.ordered_item_row_count
    or expected.gross_item_value is distinct from actual.gross_item_value
    or expected.freight_amount is distinct from actual.freight_amount
    or expected.item_side_amount is distinct from actual.item_side_amount
    or expected.category_order_association_count
        is distinct from actual.category_order_association_count
