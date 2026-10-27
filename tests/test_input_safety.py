"""Reject unsafe inputs/state before touching credential contents or workers."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from h2portable.execution import LocalRunner
from h2portable.jobs import JobError, _tree_manifest, read_job, run_job


@unittest.skipUnless(os.name == 'posix', 'Linux controller tests')
class InputSafetyTests(unittest.TestCase):
    def test_protected_filename_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('h2portable.jobs.os.walk', return_value=[(str(root), [], ['.env'])]), \
                 patch('pathlib.Path.open', side_effect=AssertionError('credential content must not be read')):
                with self.assertRaisesRegex(JobError, 'protected credential'):
                    _tree_manifest(root)

    def test_fifo_and_symlink_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / 'pipe'
            os.mkfifo(fifo)
            with self.assertRaisesRegex(JobError, 'non-regular'):
                _tree_manifest(root)
            fifo.unlink()
            target = root / 'target.txt'
            target.write_text('fixture')
            (root / 'link').symlink_to(target)
            with self.assertRaisesRegex(JobError, 'symlink'):
                _tree_manifest(root)

    def test_invalid_state_and_foreign_log_paths_are_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'input'
            work.mkdir()
            store = root / 'store'
            run_job('safe', store, 'local', work, 5, [sys.executable, '-c', 'print(1)'])
            state_file = store / 'jobs/safe/state.json'
            original = state_file.read_text()
            state = json.loads(original)
            state['attempts'] = ['broken']
            state_file.write_text(json.dumps(state))
            with self.assertRaisesRegex(JobError, 'attempt history'):
                read_job('safe', store)
            state = json.loads(original)
            state['attempts'][0]['result']['stdout_file'] = '/not-a-job/.env'
            state_file.write_text(json.dumps(state))
            with self.assertRaisesRegex(JobError, 'log artifact location'):
                read_job('safe', store)

    def test_payload_never_starts_if_durable_registration_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'input'
            work.mkdir()
            marker = work / 'must-not-exist'
            with patch('h2portable.execution.write_record', side_effect=OSError('simulated disk error')):
                with self.assertRaises(OSError):
                    LocalRunner(terminate_grace=.1).run(
                        [sys.executable, '-c', "from pathlib import Path; Path('must-not-exist').write_text('bad')"],
                        work, root / 'logs', 5)
            self.assertFalse(marker.exists())

    def test_linked_log_directory_is_rejected_before_resource_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'input'
            work.mkdir()
            store = root / 'store'
            state = run_job('linked', store, 'local', work, 5, [sys.executable, '-c', 'print(1)'])
            logs = Path(state['attempts'][0]['log_directory'])
            moved = root / 'original-logs'
            logs.rename(moved)
            logs.symlink_to(moved, target_is_directory=True)
            with patch('h2portable.jobs.recover_records', side_effect=AssertionError('must not scan linked resources')):
                with self.assertRaisesRegex(JobError, 'linked attempt'):
                    read_job('linked', store)
