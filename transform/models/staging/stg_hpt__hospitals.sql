select
    hospital_id,
    hospital_name,
    -- files use both 2026-07-01 and 7/1/2026
    coalesce(
        try_strptime(last_updated_on::varchar, '%Y-%m-%d'),
        try_strptime(last_updated_on::varchar, '%m/%d/%Y')
    )::date                                             as last_updated_on,
    version                                             as schema_version,
    type_2_npi[1]                                       as type_2_npi,
    len(type_2_npi)                                     as npi_count,
    license_number,
    license_state,
    attestation_confirmed,
    source_file,
    source_format,
    row_count                                           as source_row_count,
    parsed_at::timestamp                                as parsed_at

from {{ source('hpt', 'hospitals') }}
