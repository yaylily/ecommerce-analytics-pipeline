with orders as (
    select
        order_id,
        order_status
    from {{ ref('stg_orders') }}
),

item_summary as (
    select *
    from {{ ref('int_order_item_amount_summary') }}
),

payment_summary as (
    select *
    from {{ ref('int_order_payment_summary') }}
),

combined as (
    select
        orders.order_id,
        orders.order_status,
        item_summary.order_id is not null as has_order_items,
        payment_summary.order_id is not null as has_payments,
        item_summary.ordered_item_row_count,
        item_summary.gross_item_value,
        item_summary.freight_amount,
        item_summary.item_side_amount,
        payment_summary.payment_row_count,
        payment_summary.payment_side_amount,
        payment_summary.zero_payment_value_row_count,
        payment_summary.zero_payment_installment_row_count,
        payment_summary.has_zero_payment_value,
        payment_summary.has_zero_payment_installments
    from orders
    left join item_summary using (order_id)
    left join payment_summary using (order_id)
)

select
    order_id,
    order_status,
    has_order_items,
    has_payments,
    case
        when has_order_items and has_payments then 'both'
        when has_order_items then 'items_only'
        when has_payments then 'payments_only'
        else 'neither'
    end as amount_presence_status,
    ordered_item_row_count,
    gross_item_value,
    freight_amount,
    item_side_amount,
    payment_row_count,
    payment_side_amount,
    zero_payment_value_row_count,
    zero_payment_installment_row_count,
    has_zero_payment_value,
    has_zero_payment_installments,
    case
        when has_order_items and has_payments
            then payment_side_amount - item_side_amount
    end as payment_minus_item_amount,
    case
        when has_order_items and has_payments
            then abs(payment_side_amount - item_side_amount)
    end as absolute_amount_difference,
    case
        when not (has_order_items and has_payments) then 'not_comparable'
        when payment_side_amount = item_side_amount then 'equal'
        when payment_side_amount > item_side_amount then 'payment_side_greater'
        else 'item_side_greater'
    end as amount_comparison_status
from combined
