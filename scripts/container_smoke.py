"""Run the complete upstream scripted CLI in a network-disabled task container."""
import argparse
import json
from pathlib import Path

from h2portable.execution import DockerRunner

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image', default='h2portable:offline')
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
root = args.output.expanduser().resolve()
work = root / 'workspace'
work.mkdir(parents=True, exist_ok=True)
result = DockerRunner(args.image).run(
    ['harness2', 'demo', '--output', '/work/demo', '--k', '1'],
    work, root / 'logs', 60)
record = {'execution': result.to_dict()}
if result.outcome == 'completed':
    report = json.loads((work / 'demo/demo.json').read_text())
    if report['done'] != 2 or report['failed'] != 0:
        raise AssertionError(report)
    record['demo'] = report
(root / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
if result.outcome != 'completed':
    print(Path(result.stderr_file).read_text())
    raise SystemExit(1)
