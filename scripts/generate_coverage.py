#!/usr/bin/env python3
"""Offline generation of coverage dashboard CLI/API artifacts, no cloud clients."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from oci_dashboards.coverage_dashboard import build
from oci_dashboards.management import api_payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/backup-coverage.example.json')
    parser.add_argument('--output',default='build/coverage-preview')
    parser.add_argument('--terraform',action='store_true')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())
    if args.terraform:
        config.update(dashboard_compartment_id='__BH_DASHBOARD_COMPARTMENT_ID__',telemetry_compartment_id='__BH_TELEMETRY_COMPARTMENT_ID__')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    payload=build(config)
    for name,data in [('backup-coverage.management.json',payload),('backup-coverage.management.api.json',api_payload(payload))]:
        (out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':main()
