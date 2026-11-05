with item_rows (order_id, item_amount) as (
    values
        ('synthetic_order', 100::numeric),
        ('synthetic_order', 50::numeric)
),

payment_rows (order_id, payment_amount) as (
    values
        ('synthetic_order', 70::numeric),
        ('synthetic_order', 50::numeric),
        ('synthetic_order', 30::numeric)
),

source_totals as (
    select
        (select count(*) from item_rows) as item_row_count,
        (select count(*) from payment_rows) as payment_row_count,
        (select sum(item_amount) from item_rows) as item_amount,
        (select sum(payment_amount) from payment_rows) as payment_amount
),

unsafe_join as (
    select
        count(*) as joined_row_count,
        sum(item_amount) as item_amount,
        sum(payment_amount) as payment_amount
    from item_rows
    inner join payment_rows using (order_id)
),

item_summary as (
    select order_id, sum(item_amount) as item_amount
    from item_rows
    group by order_id
),

payment_summary as (
    select order_id, sum(payment_amount) as payment_amount
    from payment_rows
    group by order_id
),

safe_join as (
    select item_summary.item_amount, payment_summary.payment_amount
    from item_summary
    inner join payment_summary using (order_id)
)

select source_totals.*, unsafe_join.*, safe_join.*
from source_totals
cross join unsafe_join
cross join safe_join
where unsafe_join.joined_row_count
        <> source_totals.item_row_count * source_totals.payment_row_count
    or unsafe_join.item_amount <= source_totals.item_amount
    or unsafe_join.payment_amount <= source_totals.payment_amount
    or safe_join.item_amount is distinct from source_totals.item_amount
    or safe_join.payment_amount is distinct from source_totals.payment_amount
