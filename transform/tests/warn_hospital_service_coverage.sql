{{ config(severity = 'warn') }}
-- Every hospital should publish rates for most of the shoppable services.
-- Low coverage usually means codes are in an unexpected format, not that the
-- hospital doesn't offer the service -- so it's a parsing problem to investigate.
select
    h.hospital_id,
    count(distinct f.billing_code) as shoppable_services_found,
    (select count(*) from {{ ref('dim_service') }}) as shoppable_services_total
from {{ ref('dim_hospital') }} as h
left join {{ ref('fct_negotiated_rates') }} as f
    on f.hospital_id = h.hospital_id and f.is_shoppable
group by 1
having count(distinct f.billing_code) < 0.5 * (select count(*) from {{ ref('dim_service') }})
