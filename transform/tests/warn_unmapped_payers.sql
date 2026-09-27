{{ config(severity = 'warn') }}
-- Payer names that didn't match any pattern in seeds/payer_patterns.csv.
-- When this warns, read the list and add patterns for the big ones.
select p.payer_name, p.plan_name, count(*) as rates
from {{ ref('fct_negotiated_rates') }} as f
join {{ ref('dim_payer') }} as p on f.payer_key = p.payer_key
where p.payer_group = 'Other'
group by 1, 2
