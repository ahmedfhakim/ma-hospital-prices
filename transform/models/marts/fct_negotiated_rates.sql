-- Grain: one negotiated rate = hospital x item (all its codes) x setting x modifiers x payer x plan.
-- Only rows with a payer; gross / cash prices live on the item and are carried along.

with item_prices as (

    -- gross and cash prices sit on every row of an item (and on payer-less rows),
    -- so take them once per item
    select
        hospital_id, description, code_signature, setting, modifiers,
        max(gross_charge)       as gross_charge,
        max(discounted_cash)    as discounted_cash
    from {{ ref('int_charges__billing_code') }}
    group by all

),

item_prices_any_setting as (

    -- some files (e.g. BIDMC) put gross / cash on a "both" row and the payer rates on
    -- "outpatient" rows, so fall back to the same item's price under any setting
    select
        hospital_id, description, code_signature, modifiers,
        max(gross_charge)       as gross_charge,
        max(discounted_cash)    as discounted_cash
    from {{ ref('int_charges__billing_code') }}
    group by all

),

prices_by_billing_code as (

    -- last resort: some files (e.g. BIDMC) list list/cash prices on chargemaster lines
    -- and negotiated rates on separate items that share only the billing code
    select
        hospital_id, billing_code, billing_code_type,
        median(gross_charge)    as gross_charge,
        median(discounted_cash) as discounted_cash
    from {{ ref('int_charges__billing_code') }}
    where billing_code is not null and gross_charge is not null
    group by all

)

select
    md5(concat_ws('|', c.hospital_id, c.description, c.code_signature, c.setting,
                  c.modifiers, c.payer_name, c.plan_name))  as rate_key,
    c.hospital_id,
    c.billing_code,
    c.billing_code_type,
    c.description,
    c.setting,
    c.modifiers,
    p.payer_key,
    c.code_signature,

    coalesce(i.gross_charge, ia.gross_charge, bc.gross_charge)          as gross_charge,
    coalesce(i.discounted_cash, ia.discounted_cash, bc.discounted_cash) as discounted_cash,
    case
        when i.gross_charge is not null  then 'same item'
        when ia.gross_charge is not null then 'same item, other setting'
        when bc.gross_charge is not null then 'same billing code'
    end                                                                  as list_price_match,
    c.negotiated_dollar,
    c.negotiated_percentage,
    c.negotiated_algorithm,
    -- recompute with the matched list price, so %-of-charges rates also work when the
    -- list price came from a fallback match
    coalesce(
        c.negotiated_dollar,
        c.negotiated_percentage / 100.0
            * coalesce(i.gross_charge, ia.gross_charge, bc.gross_charge)
    )                                                                    as effective_rate,
    case
        when c.negotiated_dollar is not null then 'dollar'
        when c.negotiated_percentage is not null
         and coalesce(i.gross_charge, ia.gross_charge, bc.gross_charge) is not null
            then 'derived_from_percentage'
        when c.negotiated_algorithm is not null then 'algorithm_only'
    end                                                                  as rate_source,
    c.methodology,

    c.median_amount,
    c.p10_amount,
    c.p90_amount,
    c.allowed_count,

    s.billing_code is not null                              as is_shoppable

from {{ ref('int_charges__billing_code') }} as c
join {{ ref('int_payers__normalized') }} as p
    on  c.payer_name = p.payer_name
    and c.plan_name is not distinct from p.plan_name
left join item_prices as i
    on  c.hospital_id = i.hospital_id
    and c.description = i.description
    and c.code_signature = i.code_signature
    and c.setting is not distinct from i.setting
    and c.modifiers is not distinct from i.modifiers
left join item_prices_any_setting as ia
    on  c.hospital_id = ia.hospital_id
    and c.description = ia.description
    and c.code_signature = ia.code_signature
    and c.modifiers is not distinct from ia.modifiers
left join prices_by_billing_code as bc
    on  c.hospital_id = bc.hospital_id
    and c.billing_code = bc.billing_code
    and c.billing_code_type = bc.billing_code_type
left join {{ ref('dim_service') }} as s
    on  c.billing_code = s.billing_code
    and c.billing_code_type = s.billing_code_type
