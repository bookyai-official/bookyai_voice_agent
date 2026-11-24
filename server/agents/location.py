"""Shared live location instructions and tool contracts for voice and text agents."""
from copy import deepcopy

LOCATION_AGENT_RULES = "Location and timezone rules (override generic address-collection scripts):\n- Before collecting an address, checking availability, or booking, call get_service_location_options for the selected service. Use its current settings even if older scripts say every customer needs an address.\n- Each base service has exactly one appointment location type. Use the returned location_type automatically; never ask the customer to choose a location type.\n- onsite: collect and confirm the address where the service is needed, including street address and country code. Ask for postal code when coverage requires it. Store access instructions separately. A contact's home address is not automatically the service address.\n- business: do not collect a customer address. Use the returned business premises; ask for a branch only if there are several. Submit its business_location_id; never invent or replace its address.\n- virtual: do not collect a physical address or ask the customer for a meeting link. The business supplies the link. Never invent one. After booking, use meeting_status and meeting_url returned by the backend; pending means the link will follow.\n- Interpret requested times in the client's local timezone and use the same client timezone for availability and booking; the backend converts these times to UTC. Use browser/session or known client timezone metadata automatically. Do not ask the customer to select a timezone, and never substitute a business or branch timezone. If client timezone metadata is unavailable, use the client's known city/region in client_location (or the service address for a client visit); ask for their city/country only if that context is missing. Never derive timezone from a meeting URL or access instructions.\n- Recheck location options if the service changes. Confirm the selected service, location, date, time, and timezone before creating the booking."

LOCATION_PROPERTIES = {'client_location': {'type': 'string', 'maxLength': 4000, 'description': 'Client city/region and country only if automatic timezone metadata is unavailable; never the business address.'},
 'location_type': {'type': 'string',
                   'enum': ['onsite', 'business', 'virtual'],
                   'description': 'Use the fixed location_type returned by '
                                  'get_service_location_options.'},
 'service_address': {'type': 'object',
                     'description': 'Only for onsite appointments, where the service is needed.',
                     'properties': {'line1': {'type': 'string', 'maxLength': 1000},
                                    'line2': {'type': 'string', 'maxLength': 1000},
                                    'city': {'type': 'string', 'maxLength': 1000},
                                    'region': {'type': 'string', 'maxLength': 1000},
                                    'postal_code': {'type': 'string', 'maxLength': 1000},
                                    'country_code': {'type': 'string', 'maxLength': 1000}},
                     'required': ['line1', 'country_code'],
                     'additionalProperties': False},
 'business_location_id': {'type': 'string',
                          'description': 'Only for business appointments. Use the premises ID '
                                         'returned by get_service_location_options.'},
 'location_instructions': {'type': 'string',
                           'maxLength': 4000,
                           'description': 'Optional access or entrance instructions; not the '
                                          'address or joining link.'},
 'timezone': {'type': 'string',
              'description': 'Client IANA timezone from automatic browser/session metadata or known client locality. Use consistently for availability and booking; never ask the client to select a timezone.'}}

def upgrade_location_schema(schema):
    schema = deepcopy(schema)
    fields = schema.setdefault('properties', {})
    obsolete = ('address', 'city', 'state', 'zip_code', 'location_details', 'customer_address')
    for name in obsolete:
        fields.pop(name, None)
    fields.update(deepcopy(LOCATION_PROPERTIES))
    if 'required' in schema:
        schema['required'] = [name for name in schema['required'] if name not in obsolete]
    return schema
