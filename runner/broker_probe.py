"""Проба реального worker HTTP protocol без доступа к основной БД."""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import secrets
import subprocess
import threading
import time


def main():
    token = secrets.token_urlsafe(48)
    jobs = [
        {'language': 'python', 'source': 'print(int(input()) * 2)', 'tests': [{'stdin': '21\n', 'expected': '42'}]},
        {'language': 'javascript', 'source': 'console.log(Number(require("fs").readFileSync(0,"utf8"))*2)', 'tests': [{'stdin': '21\n', 'expected': '42'}]},
        {'language': 'sql', 'source': 'SELECT SUM(n) FROM t', 'tests': [{'setup': 'CREATE TABLE t(n); INSERT INTO t VALUES(17),(25);', 'expected': [[42]]}]},
        {'language': 'python', 'source': 'print(43)', 'tests': [{'expected': '42'}]},
        {'language': 'python', 'source': 'while True: pass', 'tests': [{'expected': '42'}]},
    ]
    for index, job in enumerate(jobs):
        job.update(id=str(index), lease_token=secrets.token_urlsafe(32), time_limit_seconds=2)
    results = {}
    claimed = []
    failures = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send_error(401)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 65536:
                    raise ValueError('request_limit')
                payload = json.loads(self.rfile.read(length))
                if self.path == '/internal/runner/claim':
                    next_job = next((job for job in jobs if job['id'] not in claimed), None)
                    if next_job:
                        claimed.append(next_job['id'])
                    response = {'job': next_job}
                else:
                    parts = self.path.split('/')
                    if len(parts) != 6 or parts[1:4] != ['internal', 'runner', 'jobs'] or parts[5] != 'result':
                        raise ValueError('path')
                    job_id = parts[4]
                    job = jobs[int(job_id)]
                    assert hmac.compare_digest(payload['lease_token'], job['lease_token'])
                    assert payload['total'] == 1
                    assert 'runtime_version' in payload and payload['duration_ms'] > 0
                    assert not set(payload).intersection({'stdout', 'stderr', 'source', 'expected', 'tests', 'setup'})
                    assert job_id not in results
                    results[job_id] = {'status': payload['status'], 'passed': payload['passed'],
                                       'duration_ms': payload['duration_ms']}
                    response = {'ok': True}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception:
                failures.append('invalid_worker_protocol')
                self.send_error(400)

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, FSP_RUNNER_BROKER_URL=f'http://127.0.0.1:{server.server_port}', FSP_RUNNER_TOKEN=token)
    process = subprocess.Popen(['python', '-m', 'runner.worker'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + (180 if os.environ.get('FSP_RUNNER_ACCEL', 'kvm') == 'kvm' else 600)
    try:
        while len(results) < len(jobs) and not failures and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError('worker_exited')
            time.sleep(0.1)
        assert not failures and len(results) == len(jobs), 'broker_probe_incomplete'
        assert [results[str(i)]['status'] for i in range(len(jobs))] == [
            'passed', 'passed', 'passed', 'wrong_answer', 'timeout'], 'wrong_worker_results'
        assert [results[str(i)]['passed'] for i in range(len(jobs))] == [1, 1, 1, 0, 0]
        print(json.dumps({'checks': 5, 'failed': 0, 'probe': 'real_worker_authenticated_broker',
                          'accelerator': os.environ.get('FSP_RUNNER_ACCEL', 'kvm'), 'results': results}), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
