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
