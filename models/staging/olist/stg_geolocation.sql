select
    nullif(geolocation_zip_code_prefix, '') as geolocation_zip_code_prefix,
    nullif(geolocation_lat, '') as geolocation_lat,
    nullif(geolocation_lng, '') as geolocation_lng,
    nullif(geolocation_city, '') as geolocation_city,
    nullif(geolocation_state, '') as geolocation_state
from {{ source('olist_raw', 'geolocation') }}
