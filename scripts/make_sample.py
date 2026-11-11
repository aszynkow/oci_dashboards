#!/usr/bin/env python3
"""Create synthetic native events locally; never connects to OCI or uploads logs."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from oci_dashboards.deploy import example_event
from oci_dashboards.events import COPY, summarize

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='build/sample-events.json')
args = parser.parse_args()
now = datetime.now(timezone.utc)
success = example_event()
success['eventTime'] = (now-timedelta(hours=2)).isoformat()
failure = deepcopy(success)
failure.update(eventID='SYNTHETIC-FAILURE', eventTime=(now-timedelta(hours=3)).isoformat())
failure['data']['additionalDetails'].update(status='operationFailed', errorMessage='Synthetic failure example')
copy = deepcopy(success)
copy.update(eventID='SYNTHETIC-COPY', eventType=COPY)
unknown = deepcopy(success)
unknown['eventID'] = 'SYNTHETIC-UNKNOWN'
unknown['data']['additionalDetails'].pop('status')
events = [success, failure, deepcopy(failure), copy, unknown]
path = Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({'data_mode':'synthetic', 'events':events,
                           'report':summarize(events,now.isoformat())},indent=2)+'\n')
print('Wrote synthetic events and offline reference summary to '+str(path))
