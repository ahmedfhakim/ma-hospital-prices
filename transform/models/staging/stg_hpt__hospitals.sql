select
    hospital_id,
    hospital_name,
    {{ parse_flexible_date('last_updated_on') }}        as last_updated_on,  -- 2026-07-01 or 7/1/2026
    version                                             as schema_version,
    {{ array_first('type_2_npi') }}                     as type_2_npi,
    {{ array_length('type_2_npi') }}                    as npi_count,
    license_number,
    license_state,
    attestation_confirmed,
    source_file,
    source_format,
    row_count                                           as source_row_count,
    {{ parse_iso_timestamp('parsed_at') }}              as parsed_at

from {{ source('hpt', 'hospitals') }}
