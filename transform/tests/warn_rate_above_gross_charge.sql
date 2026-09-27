{{ config(severity = 'warn') }}
-- A negotiated rate above the hospital's own list price is unusual and often a unit error.
-- Only fee-schedule rates are comparable: per diem and case rates cover a whole day or
-- stay, so they are legitimately higher than one line item's list price.
-- (First real run, BMC: 124k warnings, 95% of them per diem / case / "other" rates.)
select hospital_id, billing_code, description, payer_key, effective_rate, gross_charge
from {{ ref('fct_negotiated_rates') }}
where methodology = 'fee schedule'
  and effective_rate > gross_charge * 1.05
