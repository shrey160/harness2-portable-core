"""Export summary/logs and a compressed full run; source evidence stays intact."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run', type=Path)
parser.add_argument('destination', type=Path)
args = parser.parse_args()
source = args.run.expanduser().resolve(strict=True)
destination = args.destination.expanduser().resolve()
if destination == source or destination.is_relative_to(source):
    parser.error('destination must be outside the source run')
destination.mkdir(parents=True, exist_ok=True)
archive = source.parent / (source.name + '.zip')
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
    for file in sorted(source.rglob('*')):
        if not file.is_symlink() and not any(part.lower() == '.env' or part.lower().startswith('.env.') for part in file.parts) and file.is_file():
            bundle.write(file, file.relative_to(source))
for name in ('validation.json', 'tests.log', 'reliability.json'):
    if (source / name).is_file() and not (source / name).is_symlink():
        shutil.copyfile(source / name, destination / name)
shutil.copyfile(archive, destination / 'full-run.zip')
metadata = {'source_run': str(source), 'archive': 'full-run.zip',
            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'note': 'Raw records retain their original Linux absolute paths; archive members are relative.'}
(destination / 'export.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata))
