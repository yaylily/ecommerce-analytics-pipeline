with expected as (
    select
        order_id,
        count(*) as payment_row_count,
        sum(payment_value) as payment_side_amount,
        count(*) filter (where payment_value = 0)
            as zero_payment_value_row_count,
        count(*) filter (where payment_installments = 0)
            as zero_payment_installment_row_count,
        count(*) filter (where payment_value = 0) > 0
            as has_zero_payment_value,
        count(*) filter (where payment_installments = 0) > 0
            as has_zero_payment_installments
    from {{ ref('stg_payments') }}
    group by order_id
),

actual as (
    select *
    from {{ ref('int_order_payment_summary') }}
)

select coalesce(expected.order_id, actual.order_id) as order_id
from expected
full outer join actual using (order_id)
where expected.order_id is null
    or actual.order_id is null
    or expected.payment_row_count is distinct from actual.payment_row_count
    or expected.payment_side_amount is distinct from actual.payment_side_amount
    or expected.zero_payment_value_row_count
        is distinct from actual.zero_payment_value_row_count
    or expected.zero_payment_installment_row_count
        is distinct from actual.zero_payment_installment_row_count
    or expected.has_zero_payment_value
        is distinct from actual.has_zero_payment_value
    or expected.has_zero_payment_installments
        is distinct from actual.has_zero_payment_installments
