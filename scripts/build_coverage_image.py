#!/usr/bin/env python3
"""Standalone coverage image build; deploy.py can orchestrate this automatically."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from oci_dashboards.registry_deploy import source_hash,docker_ready,engine_ready,build_image,build_push


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True,help='Regional OCIR image URI and version tag')
    p.add_argument('--push',action='store_true')
    p.add_argument('--docker-context',help='Per-command context, for example colima')
    p.add_argument('--start-colima',action='store_true',help='Start Colima only if Docker is unavailable')
    args=p.parse_args()
    if args.image.startswith('-') or '/' not in args.image or ':' not in args.image or any(c.isspace() for c in args.image):
        p.error('Use an OCIR registry/namespace/repository:version URI')
    options={'context':args.docker_context,'start_colima':args.start_colima}
    fingerprint=source_hash()
    if args.push:
        prefix=docker_ready(args.image.split('/',1)[0],**options)
        digest=build_push(args.image,fingerprint,prefix=prefix)
        print('Published '+args.image.rsplit(':',1)[0]+'@'+digest)
    else:
        prefix=engine_ready(**options)
        build_image(args.image,fingerprint,prefix=prefix)
        print('Built '+args.image+' locally; no image pushed.')


if __name__=='__main__':main()
