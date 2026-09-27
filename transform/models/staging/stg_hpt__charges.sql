select
    hospital_id,
    trim(description)                       as description,
    codes,
    lower(trim(setting))                    as setting,
    modifiers,
    trim(payer_name)                        as payer_name,
    trim(plan_name)                         as plan_name,

    gross_charge,
    discounted_cash,
    min_charge,
    max_charge,

    negotiated_dollar,
    negotiated_percentage,
    negotiated_algorithm,
    lower(trim(methodology))                as methodology,

    -- 2026 (v3) fields: what the hospital was actually paid over the past year
    median_amount,
    p10_amount,
    p90_amount,
    allowed_count,

    estimated_amount                        -- v2 only

from {{ source('hpt', 'charges') }}
where description is not null
