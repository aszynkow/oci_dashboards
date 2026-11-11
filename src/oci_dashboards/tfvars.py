"""Read tfvars with Terraform's parser, isolated from providers, state and OCI.

The temporary module contains only this repository's variable declarations.
Terraform resolves HCL types/defaults; this module never evaluates user HCL in
our infrastructure module or runs init/plan/apply.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


DEFAULT_VARIABLES = Path(__file__).resolve().parents[2]/'terraform/variables.tf'


def load(path, *, variables_file=DEFAULT_VARIABLES, executable='terraform', overrides=None):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f'Tfvars file not found: {path}. Copy terraform/terraform.tfvars.example to terraform/terraform.tfvars and edit it first.')
    if not shutil.which(executable):
        raise ValueError('Terraform must be installed to parse tfvars. No OCI provider initialization is required.')
    declarations = Path(variables_file).read_text()
    # These names come from our checked-in declarations, not from parsing user HCL.
    names = re.findall(r'variable\s+"([A-Za-z_][A-Za-z0-9_]*)"', declarations)
    overrides = overrides or {}
    if set(overrides) - set(names):
        raise ValueError('Unsupported command-line variable override')
    expression = 'jsonencode({' + ','.join(f'{name}=var.{name}' for name in names) + '})\n'
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('TF_CLI_ARGS', 'TF_LOG'))
                   and (not key.startswith('TF_VAR_') or key[7:] in names)}
    with tempfile.TemporaryDirectory(prefix='oci-backup-tfvars-') as folder:
        scratch = Path(folder)
        (scratch/'variables.tf').write_text(declarations)
        environment.update(TF_INPUT='0', TF_IN_AUTOMATION='1', TF_WORKSPACE='default',
                           TF_DATA_DIR=str(scratch/'.terraform'))
        try:
            result = subprocess.run([executable, '-chdir=' + str(scratch), 'console', '-no-color',
                                     '-var-file=' + str(path)] +
                                    ['-var=' + key + '=' + (value if isinstance(value, str) else json.dumps(value)) for key, value in overrides.items()], input=expression, text=True,
                                    capture_output=True, env=environment, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Terraform timed out while reading tfvars in its isolated variable-only module') from exc
    if result.returncode or result.stderr.strip():
        # Report diagnostics without echoing HCL excerpts, which may contain secrets.
        if 'undeclared variable' in result.stderr.lower():
            raise ValueError('tfvars contains an undeclared variable; check names against terraform/terraform.tfvars.example')
        raise ValueError('Terraform rejected tfvars/environment syntax, types, missing required inputs or validations; check terraform/terraform.tfvars.example; region and tenancy may come from the selected OCI profile')
    try:
        # console prints the JSON string as a quoted HCL string; decode both layers.
        return json.loads(json.loads(result.stdout.strip()))
    except (ValueError, TypeError) as exc:
        raise ValueError('Unexpected Terraform console output while reading tfvars') from exc
