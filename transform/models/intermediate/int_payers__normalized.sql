-- Map every raw payer/plan pair to a carrier (payer_group) and an insurance type (product_line).
--
-- What real files taught us (Boston Medical Center, 2026):
--   * payer_name is the insurer PRODUCT ("AARP UHC MEDICARE COMPLETE [1203]"),
--     plan_name is often the hospital's CONTRACT ("BMC HB MEDICARE - NO IME"), and one
--     contract can cover several insurers. So match on payer_name first and only fall
--     back to plan_name when the payer name alone doesn't identify the carrier.
--   * Trailing "[1234]" are internal payer IDs -> stripped for display and matching.
--   * A leading "ZZZ" marks a retired payer in the billing system -> flagged, and
--     excluded from the dashboard marts.

with raw_payers as (

    select distinct payer_name, plan_name
    from {{ ref('stg_hpt__charges') }}
    where payer_name is not null

),

cleaned as (

    select
        payer_name,
        plan_name,
        regexp_replace(regexp_replace(payer_name, '\s*\[\d+\]\s*$', ''), '^ZZZ', '')  as payer_display_name,
        lower(payer_name) like 'zzz%'                                                  as is_retired_payer
    from raw_payers

),

candidates as (

    -- match_source 1 = matched on the insurer name, 2 = matched only on the contract/plan name
    select c.payer_name, c.plan_name, p.payer_group, p.product_line as product_line_override,
           p.priority, length(p.pattern) as specificity, 1 as match_source
    from cleaned as c
    join {{ ref('payer_patterns') }} as p on lower(c.payer_display_name) like p.pattern
    union all
    select c.payer_name, c.plan_name, p.payer_group, p.product_line,
           p.priority, length(p.pattern), 2
    from cleaned as c
    join {{ ref('payer_patterns') }} as p on lower(coalesce(c.plan_name, '')) like p.pattern

),

ranked as (

    select
        *,
        row_number() over (
            partition by payer_name, plan_name
            order by match_source, priority, specificity desc
        ) as rn
    from candidates

),

best as (

    select * from ranked where rn = 1

)

select
    {{ dbt.hash("c.payer_name || '|' || coalesce(c.plan_name, '')") }} as payer_key,
    c.payer_name,
    c.plan_name,
    c.payer_display_name,
    c.is_retired_payer,
    coalesce(b.payer_group, 'Other')                                as payer_group,
    b.match_source,
    case
        when b.product_line_override is not null then b.product_line_override
        -- an insurer can administer government coverage, e.g. "Optum / VA Government"
        -- (the VA's community care network) is not a commercial product
        when {{ regex_match("lower(coalesce(c.plan_name, ''))", '\\bva\\b|veteran|tricare') }}
            then 'Other government'
        when {{ regex_match('lower(c.payer_display_name)', 'medicaid|masshealth|\\baco\\b|\\bmco\\b|\\bmcd\\b') }}
            then 'Medicaid'
        when {{ regex_match('lower(c.payer_display_name)', 'medicare|\\bsco\\b|senior|wellcare|eternal') }}
            then 'Medicare Advantage'
        -- the payer name is ambiguous (e.g. "CCA", "FALLON"); the contract says what it is.
        -- Check "commercial" first: contracts are often priced as a % of Medicare/Medicaid,
        -- e.g. "FALLON COMMERCIAL (130% OF MEDICARE)" is a commercial contract.
        -- (Connector Care = the subsidized state marketplace, a commercial product.)
        when {{ regex_match("lower(coalesce(c.plan_name, ''))", 'commercial|connector|qhp') }} then 'Commercial'
        when {{ regex_match("lower(coalesce(c.plan_name, ''))", 'medicaid|masshealth') }} then 'Medicaid'
        when {{ regex_match("lower(coalesce(c.plan_name, ''))", 'medicare') }} then 'Medicare Advantage'
        else 'Commercial'
    end                                                             as product_line

from cleaned as c
left join best as b
    on  c.payer_name = b.payer_name
    and c.plan_name is not distinct from b.plan_name
