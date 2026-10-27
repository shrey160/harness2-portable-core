"""Crash recovery for worker resources registered by nested local workflows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path



@unittest.skipUnless(os.name == "posix" and os.environ.get("H2_TEST_DOCKER_IMAGE"),
                     "set H2_TEST_DOCKER_IMAGE to enable nested Docker recovery")
class TestNestedDockerRecovery(unittest.TestCase):
    def test_crashed_outer_local_worker_recovers_nested_docker_worker(self) -> None:
        image = os.environ["H2_TEST_DOCKER_IMAGE"]
        with tempfile.TemporaryDirectory(prefix="h2 nested recovery ") as directory:
            root = Path(directory)
            store, workspace = root / "store", root / "workflow input"
            workspace.mkdir()
            env = {**os.environ, "H2_NESTED_RECOVERY_SLEEP": "30"}
            workflow = workspace / "workflow.py"
            workflow.write_text(
                "import os,sys\n"
                "from pathlib import Path\n"
                "from concurrent.futures import ThreadPoolExecutor\n"
                "from h2portable.execution import DockerRunner\n"
                "def run_one(index):\n"
                "    work = Path.cwd() / f'task-{index}'\n"
                "    logs = Path.cwd() / f'logs-{index}'\n"
                "    work.mkdir()\n"
                "    logs.mkdir()\n"
                "    code = 'import pathlib,sys,time; pathlib.Path(\"/work/started\").write_text(\"ready\"); time.sleep(float(sys.argv[1]))'\n"
                "    return DockerRunner(sys.argv[1]).run(['python3','-c',code,os.environ['H2_NESTED_RECOVERY_SLEEP']], work, logs, 45).outcome\n"
                "with ThreadPoolExecutor(max_workers=2) as pool:\n"
                "    outcomes = list(pool.map(run_one, range(2)))\n"
                "raise SystemExit(0 if outcomes == ['completed', 'completed'] else 1)\n",
                encoding="utf-8",
            )
            command = [sys.executable, "workflow.py", image]
            owner = subprocess.Popen(
                [sys.executable, "-m", "h2portable", "run", "--id", "nested-recovery", "--store", str(store),
                 "--backend", "local", "--workspace", str(workspace), "--timeout", "60", "--", *command],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            attempt_logs = store / "jobs" / "nested-recovery" / "attempts" / "0001" / "logs"
            try:
                deadline = time.monotonic() + 50
                records: dict[str, dict] = {}
                record_paths: dict[str, Path] = {}
                container_infos: dict[str, dict] = {}
                while time.monotonic() < deadline:
                    if attempt_logs.exists():
                        for path in attempt_logs.glob("*.resource.json"):
                            try:
                                record = json.loads(path.read_text(encoding="utf-8"))
                            except (OSError, json.JSONDecodeError):
                                continue
                            records[path.name] = record
                            record_paths[path.name] = path
                    docker_records = [r for r in records.values() if r.get("kind") == "docker" and r.get("cid")]
                    if len(docker_records) == 2:
                        for docker_record in docker_records:
                            cid = docker_record["cid"]
                            if cid in container_infos:
                                continue
                            inspect = subprocess.run(["docker", "inspect", cid], capture_output=True,
                                                     text=True, timeout=10)
                            if inspect.returncode == 0:
                                info = json.loads(inspect.stdout)[0]
                                mounts = info.get("Mounts", [])
                                self.assertFalse(any(Path(mount.get("Source", "/nonexistent")).resolve()
                                                     == attempt_logs.resolve() for mount in mounts),
                                                 "host resource registry must not be mounted into the task container")
                                self.assertFalse(any(item.startswith("H2PORTABLE_RESOURCE_ROOT=")
                                                     for item in info.get("Config", {}).get("Env", [])),
                                                 "host resource registry variable must not reach the task container")
                                container_infos[cid] = info
                        state_path = store / "jobs" / "nested-recovery" / "state.json"
                        if state_path.exists():
                            state = json.loads(state_path.read_text(encoding="utf-8"))
                            task_workspace = Path(state["attempts"][-1]["workspace"])
                            markers_ready = all((task_workspace / f"task-{i}" / "started").exists() for i in range(2))
                            if (len(container_infos) == 2 and markers_ready
                                    and all(i.get("State", {}).get("Running") for i in container_infos.values())):
                                break
                    time.sleep(0.1)
                local_records = [r for r in records.values() if r.get("kind") == "local"]
                docker_records = [r for r in records.values() if r.get("kind") == "docker"]
                self.assertEqual(len(local_records), 1, "outer local worker resource was not registered")
                self.assertEqual(len(docker_records), 2, "both nested Docker resources must be registered")
                self.assertTrue(all(r.get("cid") for r in docker_records), "nested Docker CIDs were not recorded")
                self.assertTrue(all(r.get("controller_pid") == local_records[0].get("pid")
                                    for r in docker_records),
                                "nested Docker workers must identify their registered local controller")
                owner.kill()  # SIGKILL only the job controller; status owns recovery.
                owner.wait(timeout=5)

                status = subprocess.run([sys.executable, "-m", "h2portable", "status", "--id", "nested-recovery",
                                         "--store", str(store)], env=env, capture_output=True, text=True, timeout=45)
                self.assertEqual(status.returncode, 0, status.stderr)
                state = json.loads(status.stdout)
                self.assertEqual(state["status"], "interrupted")
                attempt = state["attempts"][-1]
                self.assertEqual(attempt["recovery"]["status"], "recovered")
                recovered_records = {kind: json.loads(path.read_text(encoding="utf-8"))
                                     for kind, path in record_paths.items()}
                self.assertTrue(all(record.get("released") for record in recovered_records.values()),
                                "all nested worker records must be marked released")
                for docker_record in docker_records:
                    inspect_after = subprocess.run(["docker", "inspect", docker_record["cid"]],
                                                   capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(inspect_after.returncode, 0, "nested owned container survived recovery")

                retry_env = {**env, "H2_NESTED_RECOVERY_SLEEP": "0.1"}
                retried = subprocess.run(
                    [sys.executable, "-m", "h2portable", "run", "--id", "nested-recovery", "--store", str(store),
                     "--backend", "local", "--workspace", str(workspace), "--timeout", "60", "--", *command],
                    env=retry_env, capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(retried.returncode, 0, retried.stderr)
                self.assertEqual(len(json.loads(retried.stdout)["attempts"]), 2)
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=5)
                if attempt_logs.exists():
                    from h2portable.recovery import recover_records
                    recover_records(attempt_logs)


if __name__ == "__main__":
    unittest.main()
