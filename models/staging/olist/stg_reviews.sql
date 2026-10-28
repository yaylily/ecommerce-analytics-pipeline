select
    nullif(review_id, '') as review_id,
    nullif(order_id, '') as order_id,
    cast(nullif(review_score, '') as integer) as review_score,
    nullif(review_comment_title, '') as review_comment_title,
    nullif(review_comment_message, '') as review_comment_message,
    cast(nullif(review_creation_date, '') as timestamp without time zone)
        as review_creation_date,
    cast(nullif(review_answer_timestamp, '') as timestamp without time zone)
        as review_answer_timestamp
from {{ source('olist_raw', 'reviews') }}
