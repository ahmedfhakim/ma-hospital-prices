-- Headline table: for each service, how far apart are commercial prices across hospitals?
-- Grain: shoppable service.

with hospital_level as (

    select
        category, service_name, billing_code, hospital_name,
        round(median(median_rate), 2) as commercial_median
    from {{ ref('mart_service_prices') }}
    where product_line = 'Commercial'
    group by all

)

select
    category,
    service_name,
    billing_code,
    count(*)                                                    as hospitals,
    min(commercial_median)                                      as lowest_hospital_median,
    max(commercial_median)                                      as highest_hospital_median,
    arg_min(hospital_name, commercial_median)                   as lowest_hospital,
    arg_max(hospital_name, commercial_median)                   as highest_hospital,
    round(max(commercial_median) / nullif(min(commercial_median), 0), 2) as high_to_low_ratio

from hospital_level
group by all
having count(*) >= 2
