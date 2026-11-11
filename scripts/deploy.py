#!/usr/bin/env python3
"""Single-tfvars repository entry point; preparation needs Terraform, not OCI access."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from oci_dashboards.deploy import main

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit('Deployment stopped: ' + type(error).__name__ + ': ' + str(error)) from error
