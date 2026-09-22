import contextlib
import importlib.util
import io
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
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'ask'
SCRIPT = SKILL / 'scripts' / 'ask-agent.py'
spec = importlib.util.spec_from_file_location('ask_agent', SCRIPT)
ask_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask_agent)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ask-agent-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / 'state'
        self.env = {**os.environ, 'ASK_AGENT_HOME': str(self.store)}
        self.root_patch = patch.object(ask_agent, 'ROOT', self.store)
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
        script = installed / 'scripts' / 'ask-agent.py'
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
        for path, mode in [(self.store, 0o700), (self.store / 'jobs', 0o700), (folder, 0o700),
                           *[(folder / n, 0o600) for n in ('job.json', 'stdout.log', 'stderr.log')]]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode, path)

    def test_existing_loose_store_is_tightened(self):
        (self.store / 'jobs').mkdir(parents=True)
        for path in (self.store, self.store / 'jobs'): path.chmod(0o755)
        self.run_code('pass')
        for path in (self.store, self.store / 'jobs'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)

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

    def test_status_lists_by_start_time_not_job_id(self):
        """Ids carry a random suffix, so two jobs started in the same second sort
        arbitrarily by name. The recorded start time orders them."""
        early, late = '20260101-120000-ffffff', '20260101-120000-000000'
        for job, moment in ((early, '2026-01-01T12:00:00.100000+00:00'),
                            (late, '2026-01-01T12:00:00.900000+00:00')):
            folder = self.store / 'jobs' / job
            folder.mkdir(parents=True)
            (folder / 'job.json').write_text(json.dumps(
                {'job': job, 'status': 'succeeded', 'created_at': moment, 'finished_at': moment}))
        listed = [json.loads(line)['job'] for line in self.cli('status').stdout.splitlines()]
        self.assertEqual(listed, [early, late])
        self.assertEqual(sorted(listed), [late, early], 'id order must be the opposite')

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
            ([{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Before failure'}},
              {'type': 'turn.failed', 'error': {'message': 'model not supported'}}], None),
            ([{'type': 'item.completed', 'item': {'type': 'error', 'message': 'metadata warning'}},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Codex final'}},
              {'type': 'turn.completed', 'usage': {'output_tokens': 7}}], 'Codex final'),
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
                self.assertEqual(result.returncode, 0 if delay == 0 else 124)

    def start_live_job(self, code=None, stderr=None):
        output = self.root / 'live-job.txt'
        handle = output.open('w')
        self.addCleanup(handle.close)
        code = code or ('import json,subprocess,sys,time; '
                        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                        'print(json.dumps({"thread_id":"thr_live", "child_pid":p.pid}),flush=True); time.sleep(60)')
        proc = subprocess.Popen([sys.executable, str(SCRIPT), 'run', '--timeout', '15', '--',
                                 sys.executable, '-c', code], env=self.env, stdout=handle,
                                stderr=stderr or subprocess.DEVNULL)
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
        self.assertEqual(proc.wait(timeout=15), 130)
        self.assert_dead(child_pid)
        self.assertEqual(self.metadata(job)['status'], 'cancelled')

    def test_stop_verified_job(self):
        proc, job, child_pid = self.start_live_job()
        # Identity verification is covered below; this tests signalling only our own child group.
        with patch.object(ask_agent, 'process_matches_job', return_value=True):
            ask_agent.cmd_stop(types.SimpleNamespace(job=job))
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
        self.assertIs(ask_agent.process_matches_job(pid, job), True)
        result = self.cli('stop', job)
        self.assertEqual(result.returncode, 0, result.stderr)
        proc.wait(timeout=15)
        self.assert_dead(child_pid)
        self.assertEqual(self.metadata(job)['status'], 'cancelled')

    def test_warning_and_status_listing_with_corrupt_record(self):
        result, good = self.run_code('pass')
        self.assertEqual(result.returncode, 0)
        _, bad = self.run_code('pass')
        (self.store / 'jobs' / bad / 'job.json').write_text('{broken')
        result = self.cli('status')
        records = {e['job']: e for e in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(records[good]['status'], 'succeeded')
        self.assertEqual(records[bad]['status'], 'corrupt')

    def test_process_identity(self):
        job = '20260101-120000-a1b2c3'
        with patch.object(ask_agent.os, 'kill'):
            for output, expected in [('cmd ASK_AGENT_JOB=' + job, True),
                                     ('cmd ASK_AGENT_JOB=' + job + 'extra', False),
                                     ('cmd without visible environment', None)]:
                with self.subTest(output=output), patch.object(ask_agent.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout=output)):
                    self.assertIs(ask_agent.process_matches_job(123, job), expected)
            with patch.object(ask_agent.subprocess, 'run', side_effect=PermissionError):
                self.assertIsNone(ask_agent.process_matches_job(123, job))
        with patch.object(ask_agent.os, 'kill', side_effect=ProcessLookupError):
            self.assertIs(ask_agent.process_matches_job(123, job), False)

    def test_unknown_and_vanished_stop(self):
        _, job = self.run_code('pass')
        ask_agent.update(job, status='running', process_group=123)
        args = types.SimpleNamespace(job=job)
        with patch.object(ask_agent, 'process_matches_job', return_value=None), patch.object(ask_agent, 'kill_group') as kill:
            self.assertEqual(ask_agent.effective_status(job, self.metadata(job)), 'unknown')
            with self.assertRaisesRegex(SystemExit, 'cannot verify'): ask_agent.cmd_stop(args)
            self.assertEqual(self.metadata(job)['status'], 'running')
            kill.assert_not_called()
        with patch.object(ask_agent, 'process_matches_job', return_value=False), patch.object(ask_agent, 'kill_group') as kill:
            self.assertEqual(ask_agent.effective_status(job, self.metadata(job)), 'process_gone')
            with self.assertRaisesRegex(SystemExit, 'process_gone'): ask_agent.cmd_stop(args)
            self.assertEqual(self.metadata(job)['status'], 'process_gone')
            kill.assert_not_called()

    def test_relative_store_is_refused(self):
        """A relative store would follow the caller's directory around, hiding jobs."""
        with patch.dict(os.environ, {'HOME': str(self.root), 'ASK_AGENT_HOME': 'relative/store'}):
            with self.assertRaisesRegex(SystemExit, 'must be an absolute path'):
                spec.loader.exec_module(importlib.util.module_from_spec(spec))

    def test_status_separates_a_missing_record_from_a_damaged_one(self):
        _, job = self.run_code('pass')
        (self.store / 'jobs' / job / 'job.json').write_text('{broken')
        damaged = self.cli('status', job)
        self.assertEqual(json.loads(damaged.stdout)['status'], 'corrupt')
        self.assertNotEqual(damaged.returncode, 0)
        gone = self.cli('status', '20260101-000000-aaaaaa')
        self.assertEqual(json.loads(gone.stdout)['status'], 'missing')
        self.assertNotEqual(gone.returncode, 0)
        # A listing still succeeds with an unreadable record in it.
        self.assertEqual(self.cli('status').returncode, 0)
        self.assertNotEqual(self.cli('path', '20260101-000000-aaaaaa').returncode, 0)

    def test_a_record_of_the_wrong_shape_is_corrupt_everywhere(self):
        """Valid JSON that is not an object is a damaged record. It must not take down a
        listing of every other job, and must never surface as a traceback."""
        _, good = self.run_code('pass')
        _, bad = self.run_code('pass')
        (self.store / 'jobs' / bad / 'job.json').write_text('[]')
        named = self.cli('status', bad)
        self.assertEqual(json.loads(named.stdout)['status'], 'corrupt')
        self.assertNotEqual(named.returncode, 0)
        listed = self.cli('status')
        records = {e['job']: e for e in map(json.loads, listed.stdout.splitlines())}
        self.assertEqual(records[bad]['status'], 'corrupt')
        self.assertEqual(records[good]['status'], 'succeeded')
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(listed.stderr, '')
        for args in (('answer', bad), ('session', bad), ('wait', bad), ('stop', bad)):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Traceback', result.stderr)
                self.assertIn('not an object', result.stderr)
        # One damaged record must not make the rest of the store unprunable.
        os.utime(self.store / 'jobs' / bad, (time.time() - 40 * 86400,) * 2)
        matched, _ = self.prune()
        self.assertEqual(matched[bad]['status'], 'corrupt')
        self.assertNotIn(good, matched)

    def test_wait_reports_each_outcome(self):
        for code, status, expected in [('pass', 'succeeded', 0), ('raise SystemExit(3)', 'failed', 1)]:
            with self.subTest(status=status):
                _, job = self.run_code(code)
                result = self.cli('wait', job)
                self.assertEqual(result.stdout.strip(), status)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_wait_blocks_until_a_live_job_finishes(self):
        brief = ('import json,os,time; '
                 'print(json.dumps({"child_pid":os.getpid()}),flush=True); time.sleep(2)')
        proc, job, _ = self.start_live_job(brief)
        result = self.cli('wait', job)
        self.assertEqual(result.stdout.strip(), 'succeeded', result.stderr)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(proc.wait(timeout=15), 0)

    def test_wait_waits_out_a_job_that_may_only_be_cleaning_up(self):
        """A runner cleaning up and a runner that died read the same. Only a reading that
        outlasts the cleanup it could be explained by is a conclusion."""
        _, job = self.run_code('pass')
        args = types.SimpleNamespace(job=job, timeout=None)
        # A job that reappears with an outcome was only ever cleaning up.
        with patch.object(ask_agent, 'effective_status', side_effect=['process_gone', 'succeeded']), \
             patch.object(ask_agent.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ask_agent.cmd_wait(args), 0)
        self.assertEqual(out.getvalue().strip(), 'succeeded')
        # A reading that persists past the window is the runner never coming back.
        clock = iter([0.0, 0.0, 1.0, 2.0] + [ask_agent.GONE_AFTER + 1.0] * 8)
        with patch.object(ask_agent, 'effective_status', return_value='process_gone'), \
             patch.object(ask_agent.time, 'monotonic', lambda: next(clock)), \
             patch.object(ask_agent.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ask_agent.cmd_wait(args), 1)
        self.assertEqual(out.getvalue().strip(), 'process_gone')

    def test_wait_gives_up_without_stopping_the_job(self):
        proc, job, child_pid = self.start_live_job()
        result = self.cli('wait', job, '--timeout', '1')
        self.assertEqual(result.returncode, 125)
        self.assertIn(f'gave up waiting for {job} after 1s', result.stderr)
        self.assertIn('was not stopped', result.stderr)
        self.assertEqual(self.metadata(job)['status'], 'running')
        self.assertNotEqual(self.cli('wait', job, '--timeout', '0').returncode, 0)
        proc.terminate()
        proc.wait(timeout=15)
        self.assert_dead(child_pid)

    def test_wait_default_window_follows_the_job(self):
        _, job = self.run_code('pass', '--timeout', '7200')
        with patch.object(ask_agent, 'effective_status', return_value='running'), \
             patch.object(ask_agent.time, 'monotonic', side_effect=[0.0, 7259.0, 7261.0]), \
             patch.object(ask_agent.time, 'sleep'), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ask_agent.cmd_wait(types.SimpleNamespace(job=job, timeout=None)), 125)
        self.assertIn('after 7260s', err.getvalue())

    def test_default_store_is_the_home_directory(self):
        def load(environ):
            with patch.dict(os.environ, environ, clear=True):
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module.ROOT
        self.assertEqual(load({'HOME': str(self.root)}), self.root / '.ask-agent')
        self.assertEqual(load({'HOME': str(self.root), 'ASK_AGENT_HOME': '~/elsewhere'}),
                         self.root / 'elsewhere')

    def test_finished_job_does_not_rescan_its_log(self):
        _, job = self.run_code('pass')
        with patch.object(ask_agent, 'find_session') as scan:
            self.assertIsNone(ask_agent.effective_session(job, self.metadata(job)))
            scan.assert_not_called()
        running = {**self.metadata(job), 'finished_at': None, 'status': 'running'}
        with patch.object(ask_agent, 'find_session', return_value='thr_live') as scan:
            self.assertEqual(ask_agent.effective_session(job, running), 'thr_live')
            scan.assert_called_once()

    def test_missing_session_is_reported_from_the_outcome_not_the_flags(self):
        """The runner does not guess from a provider's flag names whether its output will
        be parseable; it reports what the run produced."""
        quiet, _ = self.run_code('print(\'{"session_id":"sess_1"}\')')
        self.assertNotIn('no session id', quiet.stderr)
        # argv is no longer consulted, so a structured-looking flag changes nothing.
        looks_structured = self.cli('run', '--', sys.executable, '-c', 'pass', '--output-format=json')
        self.assertIn('no session id', looks_structured.stderr)
        loud, _ = self.run_code('pass')
        self.assertIn('no session id', loud.stderr)
        # Not reported for a failed job, which already reports its failure.
        failed, _ = self.run_code('raise SystemExit(1)')
        self.assertNotIn('no session id', failed.stderr)

    def age_job(self, job, days, **patch):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        data = {**self.metadata(job), 'created_at': stamp, 'finished_at': stamp, **patch}
        (self.store / 'jobs' / job / 'job.json').write_text(json.dumps(data))
        return job

    def prune_in_process(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ask_agent.cmd_prune(types.SimpleNamespace(older_than=0, delete=True, **kwargs))
        return out.getvalue()

    def prune(self, *args):
        result = self.cli('prune', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return {json.loads(line)['job']: json.loads(line) for line in result.stdout.splitlines()}, result

    def test_prune_lists_before_it_deletes(self):
        old = self.age_job(self.run_code('print(\'{"session_id":"sess_old"}\')')[1], 40)
        recent = self.age_job(self.run_code('pass')[1], 2)
        listed, result = self.prune()
        self.assertEqual(set(listed), {old})
        self.assertEqual(listed[old]['session_id'], 'sess_old')
        self.assertFalse(listed[old]['deleted'])
        self.assertIn('re-run with --delete', result.stderr)
        # Nothing is removed without --delete.
        self.assertEqual(set(p.name for p in (self.store / 'jobs').iterdir()), {old, recent})
        listed, _ = self.prune('--delete')
        self.assertTrue(listed[old]['deleted'])
        self.assertEqual(set(p.name for p in (self.store / 'jobs').iterdir()), {recent})

    def test_prune_removes_a_running_job_and_the_runner_says_so(self):
        """Nothing is exempt. Pruning a live job is the same as deleting its directory by
        hand: the provider is still cleaned up, and the runner reports what happened."""
        errors = (self.root / 'runner-stderr.txt').open('w+')
        self.addCleanup(errors.close)
        # Pruning does not interrupt a run; it only fails the final write.
        brief = ('import json,subprocess,sys,time; '
                 'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                 'print(json.dumps({"thread_id":"thr_live","child_pid":p.pid}),flush=True); time.sleep(4)')
        proc, job, child_pid = self.start_live_job(brief, stderr=errors)
        self.assertIsNone(self.metadata(job)['session_id'])
        preview, _ = self.prune('--older-than', '0')
        self.assertEqual(preview[job]['session_id'], 'thr_live')
        listed, _ = self.prune('--older-than', '0', '--delete')
        self.assertTrue(listed[job]['deleted'])
        self.assertEqual(listed[job]['session_id'], 'thr_live')
        self.assertFalse((self.store / 'jobs' / job).exists())
        self.assertEqual(proc.wait(timeout=15), 1)
        self.assert_dead(child_pid)
        errors.seek(0)
        self.assertIn('disappeared while it ran', errors.read())

    def test_prune_removes_a_record_too_damaged_to_read(self):
        bad = self.store / 'jobs' / '20260101-000000-badbad'
        bad.mkdir(parents=True); (bad / 'job.json').write_text('{broken')
        os.utime(bad, (time.time() - 40 * 86400,) * 2)
        listed, _ = self.prune('--delete')
        self.assertEqual(listed['20260101-000000-badbad']['status'], 'corrupt')
        self.assertFalse(bad.exists())

    def test_prune_window_and_argument_validation(self):
        job = self.age_job(self.run_code('pass')[1], 10)
        self.assertEqual(set(self.prune('--older-than', '30')[0]), set())
        self.assertEqual(set(self.prune('--older-than', '5')[0]), {job})
        self.assertNotEqual(self.cli('prune', '--older-than', '-1').returncode, 0)
        self.assertTrue((self.store / 'jobs' / job).is_dir())

    def test_prune_refuses_to_follow_a_symlink_out_of_the_store(self):
        outside = self.root / 'precious'; outside.mkdir(); (outside / 'keep.txt').write_text('keep')
        (self.store / 'jobs').mkdir(parents=True, exist_ok=True)
        (self.store / 'jobs' / '20260101-000000-abcdef').symlink_to(outside)
        with self.assertRaises(SystemExit):
            ask_agent.remove_job('20260101-000000-abcdef')
        self.assertTrue((outside / 'keep.txt').exists())

    def test_validation_and_provider_flags(self):
        for args in [('path', '../../etc'), ('run', '--'), ('run', '--timeout', '0', '--', 'true'),
                     ('run', '--cwd', str(self.root / 'missing'), '--', 'true')]:
            with self.subTest(args=args): self.assertNotEqual(self.cli(*args).returncode, 0)
        result = self.cli('run', '--', sys.executable, '-c', 'import sys; print(sys.argv[1:])', '--cwd', '--timeout', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.metadata(result.stdout.strip())['argv'][-3:], ['--cwd', '--timeout', '--json'])


if __name__ == '__main__':
    unittest.main()
