"""Real container contract checks; no model or external network is used."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from h2portable.execution import DockerRunner


@unittest.skipUnless(os.environ.get('H2_TEST_DOCKER_IMAGE'), 'Docker integration opt-in required')
class SandboxTests(unittest.TestCase):
    def test_only_work_is_writable_and_no_host_or_socket_mount(self):
        with tempfile.TemporaryDirectory(prefix='h2 sandbox ü ') as directory:
            root = Path(directory)
            work, logs = root / 'task', root / 'controller'
            work.mkdir()
            logs.mkdir()
            hidden = logs / 'held-out-secret.txt'
            hidden.write_text('controller-only')
            code = '''import json,os,pathlib,socket
assert os.getuid() != 0
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/opt/h2portable/fixtures/custom_workflow.py').exists()
assert not pathlib.Path(%r).exists()
try:
 pathlib.Path('/rootfs-write-probe').write_text('bad')
except OSError:
 pass
else:
 raise AssertionError('rootfs writable')
interfaces=socket.if_nameindex()
assert all(name == 'lo' for _,name in interfaces), interfaces
pathlib.Path('/work/output.txt').write_text('retained')
print(json.dumps({'uid':os.getuid(),'network_interfaces':interfaces,'root_read_only':True}))
''' % str(hidden)
            result = DockerRunner(os.environ['H2_TEST_DOCKER_IMAGE']).run(
                ['python3', '-c', code], work, logs, 10)
            self.assertEqual(result.outcome, 'completed', result.error or Path(result.stderr_file).read_text())
            self.assertTrue(json.loads(Path(result.stdout_file).read_text())['root_read_only'])
            self.assertEqual((work / 'output.txt').read_text(), 'retained')
