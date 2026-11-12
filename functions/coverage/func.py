"""OCI FDK entrypoint. Invocation bodies cannot broaden configured permissions/scope."""
import io
import json
import os
from fdk import response
from oci_dashboards.coverage_runtime import run


def handler(ctx, data: io.BytesIO = None):
    result = run(json.loads(os.environ['COVERAGE_CONFIG']))
    return response.Response(ctx, response_data=json.dumps(result), headers={'Content-Type':'application/json'})
