with audit as (
    select *
    from {{ ref('audit_order_amount_reconciliation') }}
),

expected as (
    select
        orders.order_id,
        orders.order_status,
        item_summary.order_id is not null as has_order_items,
        payment_summary.order_id is not null as has_payments,
        case
            when item_summary.order_id is not null
                and payment_summary.order_id is not null then 'both'
            when item_summary.order_id is not null then 'items_only'
            when payment_summary.order_id is not null then 'payments_only'
            else 'neither'
        end as amount_presence_status,
        item_summary.ordered_item_row_count,
        item_summary.gross_item_value,
        item_summary.freight_amount,
        item_summary.item_side_amount,
        payment_summary.payment_row_count,
        payment_summary.payment_side_amount,
        payment_summary.zero_payment_value_row_count,
        payment_summary.zero_payment_installment_row_count,
        payment_summary.has_zero_payment_value,
        payment_summary.has_zero_payment_installments,
        case
            when item_summary.order_id is not null
                and payment_summary.order_id is not null
                then payment_summary.payment_side_amount
                    - item_summary.item_side_amount
        end as payment_minus_item_amount,
        case
            when item_summary.order_id is not null
                and payment_summary.order_id is not null
                then abs(
                    payment_summary.payment_side_amount
                    - item_summary.item_side_amount
                )
        end as absolute_amount_difference,
        case
            when item_summary.order_id is null
                or payment_summary.order_id is null then 'not_comparable'
            when payment_summary.payment_side_amount
                = item_summary.item_side_amount then 'equal'
            when payment_summary.payment_side_amount
                > item_summary.item_side_amount then 'payment_side_greater'
            else 'item_side_greater'
        end as amount_comparison_status
    from {{ ref('stg_orders') }} as orders
    left join {{ ref('int_order_item_amount_summary') }} as item_summary
        using (order_id)
    left join {{ ref('int_order_payment_summary') }} as payment_summary
        using (order_id)
)

select audit.order_id
from audit
inner join expected using (order_id)
where audit.has_order_items is distinct from expected.has_order_items
    or audit.order_status is distinct from expected.order_status
    or audit.has_payments is distinct from expected.has_payments
    or audit.amount_presence_status
        is distinct from expected.amount_presence_status
    or audit.ordered_item_row_count
        is distinct from expected.ordered_item_row_count
    or audit.gross_item_value is distinct from expected.gross_item_value
    or audit.freight_amount is distinct from expected.freight_amount
    or audit.item_side_amount is distinct from expected.item_side_amount
    or audit.payment_row_count is distinct from expected.payment_row_count
    or audit.payment_side_amount is distinct from expected.payment_side_amount
    or audit.zero_payment_value_row_count
        is distinct from expected.zero_payment_value_row_count
    or audit.zero_payment_installment_row_count
        is distinct from expected.zero_payment_installment_row_count
    or audit.has_zero_payment_value
        is distinct from expected.has_zero_payment_value
    or audit.has_zero_payment_installments
        is distinct from expected.has_zero_payment_installments
    or audit.payment_minus_item_amount
        is distinct from expected.payment_minus_item_amount
    or audit.absolute_amount_difference
        is distinct from expected.absolute_amount_difference
    or audit.amount_comparison_status
        is distinct from expected.amount_comparison_status
