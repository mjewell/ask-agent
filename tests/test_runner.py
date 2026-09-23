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

    def cli(self, *args, input=''):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                              input=input, text=True, capture_output=True, timeout=20)

    def run_code(self, code, *options):
        result = self.cli('run', '--cwd', str(self.root), '--prompt-file', '-', *options,
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
        result = subprocess.run([sys.executable, str(script), 'run', '--prompt-file', '-', '--',
                                 sys.executable, '-c', code], input='',
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
        self.assertEqual(Path(json.loads(self.cli('status', job).stdout)['path']), folder.resolve())
        self.assertEqual([p.name for p in (self.store / 'jobs').iterdir()], [job], 'staging left behind')
        names = ('job.json', 'prompt.txt', 'runner.lock', 'stdout.log', 'stderr.log')
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(names))
        for path, mode in [(self.store, 0o700), (self.store / 'jobs', 0o700), (folder, 0o700),
                           *[(folder / n, 0o600) for n in names]]:
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
        result = self.cli('run', '--prompt-file', '-', '--', str(self.root / 'missing'))
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

    def test_prompt_as_an_argument_is_still_saved(self):
        """A CLI that takes its prompt as an argument gets it in place of the placeholder,
        and nothing on stdin; the record keeps the placeholder and prompt.txt the text."""
        prompt = 'Review café, $HOME, `quotes`, and newlines.\nSecond line.'
        argv = [sys.executable, '-c', 'import sys; sys.stdout.write(repr((sys.argv[1:], sys.stdin.read())))',
                '--print', '{prompt}', 'not{prompt}']
        result = self.cli('run', '--prompt-file', '-', '--', *argv, input=prompt)
        self.assertEqual(result.returncode, 0, result.stderr)
        job = result.stdout.strip()
        folder = self.store / 'jobs' / job
        self.assertEqual((folder / 'stdout.log').read_text(), repr((['--print', prompt, 'not{prompt}'], '')))
        self.assertEqual((folder / 'prompt.txt').read_text(), prompt)
        self.assertEqual(self.metadata(job)['argv'], argv)

    def test_a_prompt_is_required(self):
        result = self.cli('run', '--', sys.executable, '-c', 'pass')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--prompt-file', result.stderr)
        self.assertFalse((self.store / 'jobs').exists())
        missing = self.cli('run', '--prompt-file', str(self.root / 'absent.md'), '--', sys.executable, '-c', 'pass')
        self.assertIn('cannot read prompt file', missing.stderr)

    def test_session_and_lineage(self):
        _, job = self.run_code('print(\'{"thread_id":"thr_1234"}\')')
        self.assertEqual(self.cli('session', job).stdout.strip(), 'thr_1234')
        self.assertEqual(self.metadata(job)['session_id'], 'thr_1234')

    def write_job(self, job, created_at, **fields):
        folder = self.store / 'jobs' / job
        folder.mkdir(parents=True)
        (folder / 'job.json').write_text(json.dumps(
            {'job': job, 'status': 'succeeded', 'created_at': created_at, 'finished_at': created_at, **fields}))

    def listed(self, *args):
        result = self.cli('status', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line)['job'] for line in result.stdout.splitlines()]

    def test_status_lists_newest_first_by_start_time_not_job_id(self):
        """Ids carry a random suffix, so two jobs started in the same second sort
        arbitrarily by name. The recorded start time orders them."""
        early, late = '20260101-120000-ffffff', '20260101-120000-000000'
        self.write_job(early, '2026-01-01T12:00:00.100000+00:00')
        self.write_job(late, '2026-01-01T12:00:00.900000+00:00')
        self.assertEqual(self.listed(), [late, early])
        self.assertEqual(sorted([late, early], reverse=True), [early, late], 'id order must be the opposite')

    def test_status_limit_and_session(self):
        jobs = [f'20260101-1200{i:02d}-aaaaaa' for i in range(25)]
        for i, job in enumerate(jobs):
            self.write_job(job, f'2026-01-01T12:00:{i:02d}+00:00', session_id='sess_a' if i < 3 else None)
        newest_first = jobs[::-1]
        self.assertEqual(self.listed(), newest_first[:20])
        self.assertEqual(self.listed('--limit', '2'), newest_first[:2])
        self.assertEqual(self.listed('--limit', '0'), newest_first)
        # The session filter reaches past the default limit, and applies before it.
        self.assertEqual(self.listed('--session', 'sess_a'), jobs[2::-1])
        self.assertEqual(self.listed('--session', 'sess_a', '--limit', '1'), [jobs[2]])
        self.assertEqual(self.listed('--session', 'sess_none'), [])
        for args in (('--limit', '-1'), (jobs[0], '--limit', '20'), (jobs[0], '--session', 'sess_a')):
            with self.subTest(args=args): self.assertNotEqual(self.cli('status', *args).returncode, 0)

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
        proc = subprocess.Popen([sys.executable, str(SCRIPT), 'run', '--timeout', '15', '--prompt-file', '-',
                                 '--', sys.executable, '-c', code], env=self.env, stdout=handle,
                                stdin=subprocess.DEVNULL, stderr=stderr or subprocess.DEVNULL)
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

    def test_stop_waits_for_the_recorded_outcome(self):
        proc, job, child_pid = self.start_live_job()
        self.assertEqual(json.loads(self.cli('status', job).stdout)['status'], 'running')
        result = self.cli('stop', job)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'cancelled')
        self.assertEqual(self.metadata(job)['status'], 'cancelled')
        self.assertEqual(proc.wait(timeout=15), 130)
        self.assert_dead(child_pid)
        again = self.cli('stop', job)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('not running (status: cancelled)', again.stderr)

    def test_a_runner_that_dies_is_reported_at_once(self):
        """The lock goes with the runner, and the provider it leaves behind cannot hold it."""
        proc, job, child_pid = self.start_live_job()
        self.addCleanup(lambda: self.alive(child_pid) and os.killpg(os.getpgid(child_pid), signal.SIGKILL))
        proc.kill(); proc.wait(timeout=5)
        self.assertTrue(self.alive(child_pid), 'the orphaned provider is outside the runner')
        self.assertEqual(self.metadata(job)['status'], 'running')
        self.assertEqual(json.loads(self.cli('status', job).stdout)['status'], 'runner_died')
        start = time.monotonic()
        waited = self.cli('wait', job)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual((waited.stdout.strip(), waited.returncode), ('runner_died', 1))
        self.assertIn('not running (status: runner_died)', self.cli('stop', job).stderr)
        self.assertIn('job is runner_died', self.cli('answer', job).stderr)

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

    def test_warning_and_status_listing_with_corrupt_record(self):
        result, good = self.run_code('pass')
        self.assertEqual(result.returncode, 0)
        _, bad = self.run_code('pass')
        (self.store / 'jobs' / bad / 'job.json').write_text('{broken')
        result = self.cli('status')
        records = {e['job']: e for e in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(records[good]['status'], 'succeeded')
        self.assertEqual(records[bad]['status'], 'unreadable')

    def test_relative_store_is_refused(self):
        """A relative store would follow the caller's directory around, hiding jobs."""
        with patch.dict(os.environ, {'HOME': str(self.root), 'ASK_AGENT_HOME': 'relative/store'}):
            with self.assertRaisesRegex(SystemExit, 'must be an absolute path'):
                spec.loader.exec_module(importlib.util.module_from_spec(spec))

    def test_status_of_an_unreadable_or_unknown_job(self):
        _, job = self.run_code('pass')
        (self.store / 'jobs' / job / 'job.json').write_text('{broken')
        damaged = self.cli('status', job)
        self.assertEqual(json.loads(damaged.stdout)['status'], 'unreadable')
        self.assertNotEqual(damaged.returncode, 0)
        (self.store / 'jobs' / job / 'job.json').unlink()
        self.assertEqual(json.loads(self.cli('status', job).stdout)['status'], 'unreadable')
        gone = self.cli('status', '20260101-000000-aaaaaa')
        self.assertIn('unknown job', gone.stderr)
        self.assertNotEqual(gone.returncode, 0)
        # A listing still succeeds with an unreadable record in it.
        self.assertEqual(self.cli('status').returncode, 0)

    def test_a_record_of_the_wrong_shape_is_unreadable_everywhere(self):
        """Valid JSON that is not an object is a damaged record. It must not take down a
        listing of every other job, and must never surface as a traceback."""
        _, good = self.run_code('pass')
        _, bad = self.run_code('pass')
        (self.store / 'jobs' / bad / 'job.json').write_text('[]')
        named = self.cli('status', bad)
        self.assertEqual(json.loads(named.stdout)['status'], 'unreadable')
        self.assertNotEqual(named.returncode, 0)
        listed = self.cli('status')
        records = {e['job']: e for e in map(json.loads, listed.stdout.splitlines())}
        self.assertEqual(records[bad]['status'], 'unreadable')
        self.assertEqual(records[good]['status'], 'succeeded')
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(listed.stderr, '')
        for args in (('answer', bad), ('session', bad), ('wait', bad), ('stop', bad)):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Traceback', result.stderr)
                self.assertIn('not an object', result.stderr)

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
        with patch.object(ask_agent, 'job_state', return_value={'status': 'running'}), \
             patch.object(ask_agent.time, 'monotonic', side_effect=[0.0, 7229.0, 7231.0]), \
             patch.object(ask_agent.time, 'sleep'), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ask_agent.cmd_wait(types.SimpleNamespace(job=job, timeout=None)), 125)
        self.assertIn('after 7230s', err.getvalue())

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
        looks_structured = self.cli('run', '--prompt-file', '-', '--', sys.executable, '-c', 'pass',
                                    '--output-format=json')
        self.assertIn('no session id', looks_structured.stderr)
        loud, _ = self.run_code('pass')
        self.assertIn('no session id', loud.stderr)
        # Not reported for a failed job, which already reports its failure.
        failed, _ = self.run_code('raise SystemExit(1)')
        self.assertNotIn('no session id', failed.stderr)

    def test_a_record_deleted_while_running_is_reported(self):
        """Deleting a live job's directory does not interrupt the run; the provider is still
        cleaned up, and the runner reports that it could not record the outcome."""
        errors = (self.root / 'runner-stderr.txt').open('w+')
        self.addCleanup(errors.close)
        brief = ('import json,subprocess,sys,time; '
                 'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                 'print(json.dumps({"child_pid":p.pid}),flush=True); time.sleep(2)')
        proc, job, child_pid = self.start_live_job(brief, stderr=errors)
        shutil.rmtree(self.store / 'jobs' / job)
        self.assertEqual(proc.wait(timeout=15), 1)
        self.assert_dead(child_pid)
        errors.seek(0)
        self.assertIn('was deleted while it ran', errors.read())

    def test_validation_and_provider_flags(self):
        for args in [('status', '../../etc'), ('session', '../../etc'), ('run', '--prompt-file', '-', '--'),
                     ('run', '--prompt-file', '-', '--timeout', '0', '--', 'true'),
                     ('run', '--prompt-file', '-', '--cwd', str(self.root / 'missing'), '--', 'true')]:
            with self.subTest(args=args): self.assertNotEqual(self.cli(*args).returncode, 0)
        result = self.cli('run', '--prompt-file', '-', '--', sys.executable, '-c', 'import sys; print(sys.argv[1:])',
                          '--cwd', '--timeout', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.metadata(result.stdout.strip())['argv'][-3:], ['--cwd', '--timeout', '--json'])


if __name__ == '__main__':
    unittest.main()
