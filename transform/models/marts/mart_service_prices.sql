-- What the dashboard reads.
-- Grain: shoppable service x hospital x payer group x product line.
-- Retired payers (ZZZ...) are excluded.

with rates as (

    select
        s.category,
        s.service_name,
        f.billing_code,
        h.hospital_name,
        p.payer_group,
        p.product_line,
        f.effective_rate,
        f.median_amount,
        f.gross_charge,
        f.discounted_cash,
        f.rate_source,
        f.methodology
    from {{ ref('fct_negotiated_rates') }} as f
    join {{ ref('dim_service') }}  as s using (billing_code, billing_code_type)
    join {{ ref('dim_hospital') }} as h using (hospital_id)
    join {{ ref('dim_payer') }}    as p using (payer_key)
    where f.effective_rate is not null
      and not p.is_retired_payer

),

aggregated as (

    select
        category, service_name, billing_code, hospital_name, payer_group, product_line,
        count(*)                                        as plan_rates,
        min(effective_rate)                             as min_rate,
        round(median(effective_rate), 2)                as median_rate,
        max(effective_rate)                             as max_rate,
        round(median(median_amount), 2)                 as median_actually_paid,  -- 2026 field
        max(gross_charge)                               as gross_charge,
        max(discounted_cash)                            as cash_price,
        -- contracts that pay a % of the hospital's list price (some files also state the
        -- resulting dollar amount, so check the methodology too, not just the rate source)
        bool_or(methodology like 'percent%' or rate_source = 'derived_from_percentage')
                                                        as includes_percentage_rates
    from rates
    group by all

)

select
    *,
    -- The standard hospital-price benchmark: the same hospital's traditional Medicare rate
    round(100.0 * median_rate / nullif(
        median(median_rate) filter (where product_line = 'Medicare (traditional)')
            over (partition by billing_code, hospital_name), 0)
    , 0)                                                as pct_of_medicare
from aggregated
