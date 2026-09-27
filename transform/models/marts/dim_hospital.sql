select
    hospital_id,
    hospital_name,
    type_2_npi,
    last_updated_on,
    schema_version,
    source_format,
    source_row_count,
    attestation_confirmed,
    parsed_at
from {{ ref('stg_hpt__hospitals') }}
