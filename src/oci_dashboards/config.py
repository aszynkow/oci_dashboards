"""Shared region and compartment configuration for backup dashboards."""
import json
import re
from pathlib import Path


def validate(config):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', config.get('scope_id', '')):
        raise ValueError('scope_id must contain 1..80 letters, digits, underscores or hyphens')
    for key in ('region', 'telemetry_compartment_id', 'dashboard_compartment_id'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError('Missing native event configuration: ' + key)
    if not re.fullmatch(r'[a-z][a-z0-9-]+', config['region']):
        raise ValueError('region must be an OCI region identifier')
    compartments = config.get('inventory_compartment_ids')
    if not isinstance(compartments, list) or not compartments or len(set(compartments)) != len(compartments):
        raise ValueError('inventory_compartment_ids must be a nonempty unique list of event source compartments')
    return config


def load(path):
    return validate(json.loads(Path(path).read_text()))
