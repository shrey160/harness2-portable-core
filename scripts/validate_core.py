"""Reproduce offline core evidence. Uses no model endpoints or credentials."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from h2portable.execution import resolve_image
from h2portable.jobs import run_job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'projects/harness2_portable_core')
    parser.add_argument('--image', default='h2portable:offline')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    project = root / 'project'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    evidence = root / 'evidence' / ('validation-' + stamp)
    evidence.mkdir(parents=True)
    image_id = resolve_image(args.image)
    report = {'state': 'running', 'started_at': stamp, 'evidence': str(evidence),
              'image_reference': args.image, 'image_id': image_id,
              'python': sys.version, 'checks': {},
              'source_manifest': json.loads((project / '.source-sync.json').read_text())}

    def save() -> None:
        (evidence / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')

    def execute(label: str, argv: list[str], env: dict | None = None) -> None:
        with (evidence / (label + '.log')).open('w') as stream:
            completed = subprocess.run(argv, cwd=project, stdout=stream,
                                       stderr=subprocess.STDOUT, env=env, timeout=180)
        if completed.returncode:
            raise RuntimeError(f'{label} failed; inspect {evidence / (label + ".log")}')
        print(label + ': passed', flush=True)

    try:
        pins = json.loads((project / 'upstream.lock.json').read_text())
        for name, pin in pins.items():
            actual = subprocess.check_output(
                ['git', '-C', str(root / 'upstream' / name), 'rev-parse', 'HEAD'], text=True).strip()
            if actual != pin['commit']:
                raise AssertionError(f'{name} revision differs from lock')
        report['upstream'] = pins
        execute('tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                {**os.environ, 'H2_TEST_DOCKER_IMAGE': image_id})
        report['checks']['tests'] = 'passed; see tests.log for count'
        execute('official-demo', [str(root / 'upstream/official/.venv/bin/harness2-demo'),
                                  '--output', str(evidence / 'official-demo'), '--k', '1'])
        execute('cli-demo', [str(root / 'upstream/cli/.venv/bin/harness2'), 'demo',
                             '--output', str(evidence / 'cli-demo'), '--k', '1'])
        for name in ('official-demo', 'cli-demo'):
            data = json.loads((evidence / name / 'demo.json').read_text())
            if data['done'] != 2 or data['failed'] != 0:
                raise AssertionError(data)
            report['checks'][name] = data

        for backend in ('local', 'docker'):
            output = evidence / ('custom-' + backend)
            command = [sys.executable, 'fixtures/custom_workflow.py', '--backend', backend,
                       '--image', image_id, '--output', str(output),
                       '--upstream-cli', str(root / 'upstream/cli')]
            execute('custom-' + backend, command)
            first = json.loads((output / 'custom-workflow.json').read_text())
            if first['execution_count'] <= 0:
                raise AssertionError('fresh custom workflow did not execute')
            execute('resume-' + backend, command)
            resumed = json.loads((output / 'custom-workflow.json').read_text())
            if resumed['execution_count'] or resumed['proposer_calls'] or resumed['reflection_calls']:
                raise AssertionError(f'completed {backend} workflow repeated work: {resumed}')
            report['checks']['custom-' + backend] = {'first': first, 'resumed': resumed}
        local = report['checks']['custom-local']['first']['selected']
        docker = report['checks']['custom-docker']['first']['selected']
        if {k: v['selected_output'] for k, v in local.items()} != {k: v['selected_output'] for k, v in docker.items()}:
            raise AssertionError('local and Docker semantic outputs differ')

        # Deliberately corrupt our own generated artifact, then require a real rerun.
        output = evidence / 'custom-local'
        run_id = local['records-1']['selected_run_id']
        answer = output / 'runs/executions' / run_id / 'answer.json'
        broken = json.loads(answer.read_text())
        broken['total'] = '999.00'
        answer.write_text(json.dumps(broken))
        execute('recover-damaged-answer', [sys.executable, 'fixtures/custom_workflow.py',
                 '--backend', 'local', '--output', str(output),
                 '--upstream-cli', str(root / 'upstream/cli')])
        repaired = json.loads((output / 'custom-workflow.json').read_text())
        if repaired['execution_count'] <= 0 or repaired['selected']['records-1']['selected_output']['total'] != '-2.00':
            raise AssertionError('damaged artifact was not regenerated and independently verified')
        report['checks']['damaged_answer_recovery'] = repaired

        execute('whole-container', [sys.executable, 'scripts/container_smoke.py',
                '--image', image_id, '--output', str(evidence / 'whole-container')])
        report['checks']['whole-container'] = json.loads((evidence / 'whole-container/result.json').read_text())

        source = evidence / 'job-input'
        source.mkdir()
        (source / 'input.txt').write_text('stable input')
        command = ['python3', '-c', "from pathlib import Path; Path('output.txt').write_text('checked')"]
        job = run_job('docker-proof', evidence / 'job-store', 'docker', source, 10, command, image_id)
        again = run_job('docker-proof', evidence / 'job-store', 'docker', source, 10, command, image_id)
        if job['status'] != 'completed' or not again.get('reused') or len(again['attempts']) != 1:
            raise AssertionError('Docker persisted job did not complete and reuse')
        report['checks']['docker_job'] = again
        report['state'] = 'passed'
    except BaseException as exc:
        report['state'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        save()
        print('Evidence: ' + str(evidence / 'validation.json'), flush=True)


if __name__ == '__main__':
    main()

