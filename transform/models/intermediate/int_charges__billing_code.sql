-- Each item can carry several codes (e.g. a revenue code + a CPT code).
-- Pick the one that identifies the service: CPT/HCPCS first, then MS-DRG.
-- Also derive one comparable dollar amount per rate.

with coded as (

    select
        *,
        coalesce(
            {{ first_code_of_type('codes', "'CPT', 'HCPCS'") }},
            {{ first_code_of_type('codes', "'MS-DRG'") }}
        ) as primary_code
    from {{ ref('stg_hpt__charges') }}

)

select
    hospital_id,
    description,
    codes,
    setting,
    modifiers,
    payer_name,
    plan_name,
    gross_charge,
    discounted_cash,
    min_charge,
    max_charge,
    negotiated_dollar,
    negotiated_percentage,
    negotiated_algorithm,
    methodology,
    median_amount,
    p10_amount,
    p90_amount,
    allowed_count,
    estimated_amount,

    case
        when primary_code.type = 'MS-DRG' then regexp_replace(primary_code.code, '^0+', '')  -- '0470' -> '470'
        else upper(primary_code.code)
    end                                     as billing_code,
    -- CPT codes are formally "HCPCS Level I", and some hospitals (e.g. BIDMC) label them
    -- HCPCS. Classify by the code's format instead of trusting the label: CPT is 5 digits
    -- (or 4 digits + a letter for Category II/III); HCPCS Level II starts with a letter.
    case
        when primary_code.type = 'HCPCS' and {{ regex_match('primary_code.code', '^[0-9]{4}[0-9A-Z]$') }}
            then 'CPT'
        else primary_code.type
    end                                     as billing_code_type,
    -- every code on the item, sorted: part of the grain, because the same description and
    -- billing code can have different rates per drug package (NDC) or chargemaster line (CDM)
    {{ code_signature('codes') }}           as code_signature,

    -- Some contracts are "X% of billed charges" instead of a dollar amount.
    -- Convert those so every rate can be compared, and keep track of which is which.
    coalesce(
        negotiated_dollar,
        negotiated_percentage / 100.0 * gross_charge
    )                                       as effective_rate,
    case
        when negotiated_dollar is not null then 'dollar'
        when negotiated_percentage is not null and gross_charge is not null then 'derived_from_percentage'
        when negotiated_algorithm is not null then 'algorithm_only'
    end                                     as rate_source

from coded
