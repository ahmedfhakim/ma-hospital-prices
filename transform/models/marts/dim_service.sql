-- The services this project compares: a curated set of common "shoppable" services.
select
    billing_code,
    code_type               as billing_code_type,
    service_name,
    category
from {{ ref('shoppable_services') }}
