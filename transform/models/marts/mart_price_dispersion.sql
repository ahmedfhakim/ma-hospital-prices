-- Headline table: for each service, how far apart are commercial prices across hospitals?
-- Grain: shoppable service.

with hospital_level as (

    select
        category, service_name, billing_code, hospital_name,
        round({{ median('median_rate') }}, 2) as commercial_median
    from {{ ref('mart_service_prices') }}
    where product_line = 'Commercial'
    group by category, service_name, billing_code, hospital_name

)

select
    category,
    service_name,
    billing_code,
    count(*)                                                    as hospitals,
    min(commercial_median)                                      as lowest_hospital_median,
    max(commercial_median)                                      as highest_hospital_median,
    min_by(hospital_name, commercial_median)                    as lowest_hospital,
    max_by(hospital_name, commercial_median)                    as highest_hospital,
    round(max(commercial_median) / nullif(min(commercial_median), 0), 2) as high_to_low_ratio

from hospital_level
group by category, service_name, billing_code
having count(*) >= 2
