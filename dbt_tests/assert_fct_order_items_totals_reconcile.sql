with expected as (
    select
        count(*) as row_count,
        count(distinct (order_id, order_item_id)) as distinct_key_count,
        sum(price) as gross_item_value,
        sum(freight_value) as freight_amount,
        sum(price + freight_value) as item_side_amount
    from {{ ref('stg_order_items') }}
),

actual as (
    select
        count(*) as row_count,
        count(distinct (order_id, order_item_id)) as distinct_key_count,
        sum(price) as gross_item_value,
        sum(freight_value) as freight_amount,
        sum(item_side_amount) as item_side_amount
    from {{ ref('fct_order_items') }}
)

select 1 as reconciliation_failure
from expected
cross join actual
where expected.row_count is distinct from actual.row_count
    or expected.distinct_key_count is distinct from actual.distinct_key_count
    or expected.gross_item_value is distinct from actual.gross_item_value
    or expected.freight_amount is distinct from actual.freight_amount
    or expected.item_side_amount is distinct from actual.item_side_amount
