"""Private, atomic per-image progress journal; no credentials or raw errors."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
PHASES = {'intent', 'building', 'built', 'pushing', 'pushed', 'published'}


class ImageCheckpoint:
    def __init__(self, output, identity):
        self.identity = identity
        key = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.path = Path(output)/'image-checkpoints'/(key+'.json')
        self.record = {'version':1,'identity':identity,'phase':'intent'}
        if self.path.exists():
            try:
                record = json.loads(self.path.read_text())
            except (ValueError, OSError):
                raise ValueError('Image checkpoint cannot be read; preserve it and inspect before resuming') from None
            if not isinstance(record,dict) or record.get('version') != 1 or record.get('identity') != identity or record.get('phase') not in PHASES:
                raise ValueError('Invalid image checkpoint identity/version/phase; refusing resume')
            for key in ('local_image_id','digest'):
                if record.get(key) is not None and not DIGEST.fullmatch(str(record[key])):
                    raise ValueError('Invalid image digest in checkpoint; refusing resume')
            if record['phase'] in ('built','pushing') and not record.get('local_image_id'):
                raise ValueError('Build checkpoint has no local image identity; refusing resume')
            if record['phase'] in ('pushed','published') and not record.get('digest'):
                raise ValueError('Published checkpoint has no digest; refusing resume')
            self.record = record

    def save(self, phase, **values):
        from .deploy import write_json
        if phase not in PHASES:
            raise ValueError('Invalid image checkpoint phase')
        stamp = datetime.now(timezone.utc).isoformat()
        record = {**self.record, **values, 'phase':phase, 'updated_at':stamp}
        record['history'] = [*record.get('history',[]), {'phase':phase,'at':stamp}][-40:]
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        write_json(self.path,record)
        # Atomic replacement protects process interruption; syncing both file
        # and parent also makes the committed phase durable across OS crashes.
        with self.path.open('rb') as stream:
            os.fsync(stream.fileno())
        for folder in (self.path.parent,self.path.parent.parent):
            directory = os.open(folder,os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        self.record = record
