import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'xagent'
SCRIPT = SKILL / 'scripts' / 'xagent.py'
spec = importlib.util.spec_from_file_location('xagent', SCRIPT)
xagent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xagent)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xagent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / 'state'
        self.env = {**os.environ, 'XAGENT_HOME': str(self.store)}
        self.root_patch = patch.object(xagent, 'ROOT', self.store)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def cli(self, *args, input=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                              input=input, text=True, capture_output=True, timeout=20)

    def run_code(self, code, *options):
        result = self.cli('run', '--cwd', str(self.root), *options,
                          '--', sys.executable, '-c', code)
        return result, result.stdout.strip()

    def metadata(self, job):
        return json.loads((self.store / 'jobs' / job / 'job.json').read_text())

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(0.03)
        self.fail('timed out waiting for child process')

    def alive(self, pid):
        try: os.kill(pid, 0)
        except ProcessLookupError: return False
        # A zombie has exited but may be waiting for an external parent to reap it.
        proc_stat = Path(f'/proc/{pid}/stat')
        try:
            if proc_stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z': return False
        except FileNotFoundError: pass
        return True

    def assert_dead(self, pid):
        try:
            self.wait_for(lambda: not self.alive(pid))
        finally:
            if self.alive(pid): os.kill(pid, signal.SIGKILL)

    def test_installed_skill_is_self_contained(self):
        installed = self.root / 'installed-skill'
        shutil.copytree(SKILL, installed, ignore=shutil.ignore_patterns('__pycache__'))
        script = installed / 'scripts' / 'xagent.py'
        code = 'print(\'{"type":"result","subtype":"success","result":"Installed answer"}\')'
        result = subprocess.run([sys.executable, str(script), 'run', '--', sys.executable, '-c', code],
                                cwd=self.root, env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = subprocess.run([sys.executable, str(script), 'answer', result.stdout.strip()],
                                cwd=self.root, env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertEqual(answer.stdout.strip(), 'Installed answer')

    def test_record_streams_permissions_and_verbatim_argv(self):
        code = 'import sys; print("hello"); print("error",file=sys.stderr)'
        result, job = self.run_code(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.metadata(job)
        self.assertEqual(data['argv'], [sys.executable, '-c', code])
        self.assertEqual(data['status'], 'succeeded')
        folder = self.store / 'jobs' / job
        self.assertEqual((folder / 'stdout.log').read_text(), 'hello\n')
        self.assertEqual((folder / 'stderr.log').read_text(), 'error\n')
        self.assertEqual(Path(self.cli('path', job).stdout.strip()), folder.resolve())
        for path, mode in [(folder, 0o700), *[(folder / n, 0o600) for n in ('job.json', 'stdout.log', 'stderr.log')]]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_failure_and_missing_executable(self):
        result, job = self.run_code('raise SystemExit(3)')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.metadata(job)['exit_code'], 3)
        self.assertEqual(self.metadata(job)['status'], 'failed')
        result = self.cli('run', '--', str(self.root / 'missing'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.metadata(result.stdout.strip())['status'], 'failed')

    def test_prompt_file_and_stdin(self):
        prompt = 'Review café, $HOME, `quotes`, and newlines.\nSecond line.'
        path = self.root / 'prompt.txt'
        path.write_text(prompt)
        for source in (str(path), '-'):
            with self.subTest(source=source):
                result = self.cli('run', '--prompt-file', source, '--', sys.executable,
                                  '-c', 'import sys; sys.stdout.write(sys.stdin.read())', input=prompt)
                job = result.stdout.strip()
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in ('prompt.txt', 'stdout.log'):
                    self.assertEqual((self.store / 'jobs' / job / name).read_text(), prompt)

    def test_session_and_lineage(self):
        _, job = self.run_code('print(\'{"thread_id":"thr_1234"}\')')
        self.assertEqual(self.cli('session', job).stdout.strip(), 'thr_1234')
        self.assertEqual(self.metadata(job)['session_id'], 'thr_1234')
        _, child = self.run_code('pass', '--parent', job)
        self.assertEqual(self.metadata(child)['parent_job'], job)

    def test_answers(self):
        fixtures = [
            ([{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Earlier'}},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Codex final'}},
              {'type': 'item.updated', 'item': {'type': 'agent_message', 'text': 'Partial'}}], 'Codex final'),
            ([{'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Thinking'}]}},
              {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Claude final'}], 'Claude final'),
            ([{'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'agy final'}}], 'agy final'),
            ([{'type': 'result', 'subtype': 'success', 'result': ''}], ''),
            ([{'type': 'result', 'is_error': True, 'result': 'Error'}], None),
            ([{'type': 'result', 'subtype': 'error_max_turns', 'result': 'Incomplete'}], None),
            ([{'event': 'result', 'result': {'status': 'ERROR', 'response': 'Error'}}], None),
            ([{'type': 'item.completed', 'item': None}, {'type': 'result', 'result': {'unexpected': True}}], None),
        ]
        for events, expected in fixtures:
            with self.subTest(expected=expected, events=events):
                log = 'plain diagnostic\n' + '\n'.join(json.dumps(e) for e in events) + '\n{broken'
                _, job = self.run_code(f'print({log!r})')
                result = self.cli('answer', job)
                self.assertEqual(result.returncode, 0 if expected is not None else 1, result.stderr)
                self.assertEqual(result.stdout.strip(), expected or '')
                self.assertEqual((self.store / 'jobs' / job / 'stdout.log').read_text(), log + '\n')

    def test_failed_job_does_not_present_partial_answer(self):
        _, job = self.run_code('print(\'{"type":"item.completed","item":{"type":"agent_message","text":"Partial"}}\'); raise SystemExit(1)')
        result = self.cli('answer', job)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('failed', result.stderr)

    def test_completion_and_timeout_clean_up_actual_grandchild(self):
        for delay, expected in [(0, 'succeeded'), (60, 'timed_out')]:
            with self.subTest(expected=expected):
                code = ('import subprocess,sys,time; '
                        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                        f'print(p.pid,flush=True); time.sleep({delay})')
                result, job = self.run_code(code, '--timeout', '1')
                pid = int((self.store / 'jobs' / job / 'stdout.log').read_text())
                self.assert_dead(pid)
                self.assertEqual(self.metadata(job)['status'], expected, result.stderr)
                self.assertEqual(result.returncode, 0 if delay == 0 else 1)

    def start_live_job(self, code=None):
        output = self.root / 'live-job.txt'
        handle = output.open('w')
        self.addCleanup(handle.close)
        code = code or ('import json,subprocess,sys,time; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                'print(json.dumps({"thread_id":"thr_live", "child_pid":p.pid}),flush=True); time.sleep(60)')
        proc = subprocess.Popen([sys.executable, str(SCRIPT), 'run', '--timeout', '15', '--',
                                 sys.executable, '-c', code], env=self.env, stdout=handle, stderr=subprocess.DEVNULL)
        def cleanup():
            if proc.poll() is None: proc.terminate()
            proc.wait(timeout=15)
        self.addCleanup(cleanup)
        self.wait_for(lambda: bool(output.read_text().strip()))
        job = output.read_text().strip()
        log = self.store / 'jobs' / job / 'stdout.log'
        self.wait_for(lambda: log.exists() and '\n' in log.read_text())
        return proc, job, json.loads(log.read_text())['child_pid']

    def test_live_session_and_sigterm_cleanup(self):
        proc, job, child_pid = self.start_live_job()
        self.assertIsNone(self.metadata(job)['session_id'])
        self.assertEqual(self.cli('session', job).stdout.strip(), 'thr_live')
        self.assertNotEqual(self.cli('answer', job).returncode, 0)
        proc.terminate()
        proc.wait(timeout=15)
        self.assert_dead(child_pid)
        self.assertEqual(self.metadata(job)['status'], 'cancelled')

    def test_stop_verified_job(self):
        proc, job, child_pid = self.start_live_job()
        # Identity verification is covered below; this tests signalling only our own child group.
        with patch.object(xagent, 'process_matches_job', return_value=True):
            xagent.cmd_stop(types.SimpleNamespace(job=job))
        proc.wait(timeout=15)
        self.assert_dead(child_pid)
        self.assertEqual(self.metadata(job)['status'], 'cancelled')

    def test_repeated_interrupt_preserves_outcome_and_kills_stubborn_child(self):
        code = ('import json,os,signal,time; '
                'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'print(json.dumps({"child_pid":os.getpid()}),flush=True); time.sleep(60)')
        proc, job, child_pid = self.start_live_job(code)
        try:
            proc.send_signal(signal.SIGTERM)
            time.sleep(0.2)
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=12)
            data = self.metadata(job)
            self.assertEqual(data['status'], 'cancelled')
            self.assertEqual(data['stop_reason'], 'interrupted')
            self.assertEqual(data['exit_code'], -signal.SIGKILL)
            self.assertIsNotNone(data['finished_at'])
        finally:
            self.assert_dead(child_pid)

    def test_timeout_allows_prompt_graceful_exit(self):
        code = ('import signal,time; '
                'signal.signal(signal.SIGTERM,lambda *_: exit(0)); time.sleep(60)')
        start = time.monotonic()
        result, job = self.run_code(code, '--timeout', '1')
        elapsed = time.monotonic() - start
        self.assertEqual(self.metadata(job)['status'], 'timed_out', result.stderr)
        self.assertEqual(self.metadata(job)['exit_code'], 0)
        self.assertLess(elapsed, 4, 'gracefully exited child should not consume the full grace period')

    def test_real_process_identity_and_stop(self):
        proc, job, child_pid = self.start_live_job()
        pid = self.metadata(job)['process_group']
        try:
            check = subprocess.run(['ps', 'eww', '-p', str(pid), '-o', 'command='],
                                   capture_output=True, text=True, timeout=2)
        except OSError:
            self.skipTest('process inspection is unavailable in this environment')
        if check.returncode != 0:
            self.skipTest('process inspection is unavailable in this environment')
        self.assertIs(xagent.process_matches_job(pid, job), True)
        result = self.cli('stop', job)
        self.assertEqual(result.returncode, 0, result.stderr)
        proc.wait(timeout=15)
        self.assert_dead(child_pid)
        self.assertEqual(self.metadata(job)['status'], 'cancelled')

    def test_warning_and_status_listing_with_corrupt_record(self):
        result, good = self.run_code('pass')
        self.assertEqual(result.returncode, 0)
        self.assertIn('no structured output flag detected', result.stderr)
        _, bad = self.run_code('pass')
        (self.store / 'jobs' / bad / 'job.json').write_text('{broken')
        result = self.cli('status')
        records = {e['job']: e for e in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(records[good]['status'], 'succeeded')
        self.assertEqual(records[bad]['status'], 'corrupt')

    def test_process_identity(self):
        job = '20260101-120000-a1b2c3'
        with patch.object(xagent.os, 'kill'):
            for output, expected in [('cmd XAGENT_JOB=' + job, True),
                                     ('cmd XAGENT_JOB=' + job + 'extra', False),
                                     ('cmd without visible environment', None)]:
                with self.subTest(output=output), patch.object(xagent.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout=output)):
                    self.assertIs(xagent.process_matches_job(123, job), expected)
            with patch.object(xagent.subprocess, 'run', side_effect=PermissionError):
                self.assertIsNone(xagent.process_matches_job(123, job))
        with patch.object(xagent.os, 'kill', side_effect=ProcessLookupError):
            self.assertIs(xagent.process_matches_job(123, job), False)

    def test_unknown_and_abandoned_stop(self):
        _, job = self.run_code('pass')
        xagent.update(job, status='running', process_group=123)
        args = types.SimpleNamespace(job=job)
        with patch.object(xagent, 'process_matches_job', return_value=None), patch.object(xagent, 'kill_group') as kill:
            self.assertEqual(xagent.effective_status(job, self.metadata(job)), 'unknown')
            with self.assertRaisesRegex(SystemExit, 'cannot verify'): xagent.cmd_stop(args)
            self.assertEqual(self.metadata(job)['status'], 'running')
            kill.assert_not_called()
        with patch.object(xagent, 'process_matches_job', return_value=False), patch.object(xagent, 'kill_group') as kill:
            self.assertEqual(xagent.effective_status(job, self.metadata(job)), 'abandoned')
            with self.assertRaisesRegex(SystemExit, 'abandoned'): xagent.cmd_stop(args)
            self.assertEqual(self.metadata(job)['status'], 'abandoned')
            kill.assert_not_called()

    def test_validation_and_provider_flags(self):
        for args in [('path', '../../etc'), ('run', '--'), ('run', '--timeout', '0', '--', 'true'),
                     ('run', '--cwd', str(self.root / 'missing'), '--', 'true')]:
            with self.subTest(args=args): self.assertNotEqual(self.cli(*args).returncode, 0)
        result = self.cli('run', '--', sys.executable, '-c', 'import sys; print(sys.argv[1:])', '--cwd', '--timeout', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.metadata(result.stdout.strip())['argv'][-3:], ['--cwd', '--timeout', '--json'])


if __name__ == '__main__':
    unittest.main()
