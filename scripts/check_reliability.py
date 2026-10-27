"""Repeat real controller crashes, concurrent status checks, retry and stop."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from h2portable.execution import resolve_image
from h2portable.jobs import read_job
from h2portable.recovery import _live_group


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home()/'projects/harness2_portable_core')
    parser.add_argument('--image', default='h2portable:offline')
    parser.add_argument('--cycles', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 20:
        parser.error('cycles must be between 1 and 20')
    root = args.root.expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = root/'evidence'/('reliability-'+stamp)
    output.mkdir(parents=True)
    image = resolve_image(args.image)
    report = {'state':'running','image':image,'cycles_per_backend':args.cycles,
              'runs':[],'note':'Synthetic tasks only; no model requests or environment dumps.'}

    def cli(*arguments: str) -> list[str]:
        return [sys.executable,'-m','h2portable',*arguments]

    def wait_started(store: Path, job: str, number: int) -> Path:
        attempt = store/'jobs'/job/'attempts'/f'{number:04d}'
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            records = list((attempt/'logs').glob('*.resource.json'))
            if records and (attempt/'workspace'/'started').exists():
                return records[0]
            time.sleep(.025)
        raise AssertionError(f'worker did not start: {attempt}')

    try:
        for backend in ('local','docker'):
            for cycle in range(args.cycles):
                store = output/backend/str(cycle)/'store'
                work = output/backend/str(cycle)/'input'
                work.mkdir(parents=True)
                job = f'{backend}-{cycle}'
                command = cli('run','--id',job,'--store',str(store),'--backend',backend,
                              '--workspace',str(work),'--timeout','60')
                if backend == 'docker':
                    command += ['--image',image]
                command += ['--','python3','-c',
                            "from pathlib import Path; import time; Path('started').write_text('yes'); time.sleep(30)"]
                owners = []
                try:
                    owner = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    owners.append(owner)
                    resource_path = wait_started(store,job,1)
                    resource = json.loads(resource_path.read_text())
                    owner.kill()
                    owner.wait(timeout=5)
                    status = cli('status','--id',job,'--store',str(store))
                    # Two simultaneous observers must not both own cleanup.
                    observers = [subprocess.Popen(status, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
                    for observer in observers:
                        stdout,stderr = observer.communicate(timeout=15)
                        if observer.returncode:
                            raise AssertionError(stderr.decode('utf-8','replace'))
                    state = read_job(job,store)
                    if state['status']!='interrupted' or state['attempts'][0]['recovery']['status']!='recovered':
                        raise AssertionError(state)
                    if backend == 'local':
                        if _live_group(resource['pgid']):
                            raise AssertionError('abandoned local group is still active')
                    else:
                        probe = subprocess.run(['docker','inspect',resource['cid']],capture_output=True,timeout=5)
                        if probe.returncode==0:
                            raise AssertionError('abandoned owned container still exists')
                    retry = subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                    owners.append(retry)
                    wait_started(store,job,2)
                    stopped = subprocess.run(cli('stop','--id',job,'--store',str(store)),
                                             capture_output=True,timeout=10)
                    if stopped.returncode:
                        raise AssertionError(stopped.stderr.decode('utf-8','replace'))
                    _,stderr = retry.communicate(timeout=15)
                    state = read_job(job,store)
                    if retry.returncode!=130 or state['status']!='cancelled' or len(state['attempts'])!=2:
                        raise AssertionError(f'retry stop failed: {state}; {stderr!r}')
                    report['runs'].append({'backend':backend,'cycle':cycle,'status':'passed',
                                           'recovery':'recovered','retry':'cancelled','attempts':2})
                    print(f'{backend} crash/recover/retry/stop {cycle+1}/{args.cycles}: passed',flush=True)
                finally:
                    for owner in owners:
                        if owner.poll() is None:
                            owner.kill()
                            owner.wait(timeout=5)
                        if owner.stderr:
                            owner.stderr.close()
                    try:
                        read_job(job,store)
                    except Exception:
                        pass
        report['state']='passed'
    except BaseException as exc:
        report.update(state='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        (output/'reliability.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Evidence: '+str(output/'reliability.json'),flush=True)


if __name__=='__main__':
    main()

