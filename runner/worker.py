"""Sequential broker client. Authentication never enters job VM or logs."""
import json
import os
from pathlib import Path
import signal
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from runner.engine import VMRunner

stopping = False


def stop(signum, frame):
    global stopping
    stopping = True


class Broker:
    def __init__(self):
        self.url = os.environ.get('FSP_RUNNER_BROKER_URL', 'http://app:8470').rstrip('/')
        parsed = urlparse(self.url)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            raise ValueError('invalid_broker_url')
        self.token = os.environ.get('FSP_RUNNER_TOKEN', '')
        if len(self.token) < 32:
            raise ValueError('runner_token_missing')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path, payload):
        request = urllib.request.Request(self.url + path, json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token}, method='POST')
        with self.opener.open(request, timeout=10) as response:
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('broker_payload_limit')
            return json.loads(data or '{}')


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    runner = VMRunner()
    # Gate precedes receiving any untrusted job.
    gate = runner.run_case('python', 'print("fsp_vm_ready")', {})
    if gate.status != 'ok' or gate.stdout.strip() != 'fsp_vm_ready':
        raise RuntimeError('VM readiness gate failed: ' + (gate.error_code or gate.status))
    broker = Broker()
    print(json.dumps({'event': 'runner_ready', 'accel': runner.accelerator,
                      'runtime': runner.versions, 'boot_ms': gate.boot_ms}), flush=True)
    while not stopping:
        try:
            claimed = broker.post('/internal/runner/claim', {})
            Path('/tmp/fsp-runner-heartbeat').touch()
            job = claimed.get('job')
            if job is None:
                time.sleep(1)
                continue
            try:
                result = runner.grade(job)
            except Exception:
                # Never stringify exceptions that may embed source or broker payload.
                result = {'lease_token': job['lease_token'], 'status': 'system_error', 'passed': 0,
                          'total': len(job.get('tests', [])), 'duration_ms': 0,
                          'runtime_version': runner.versions.get(job.get('language'), 'unknown'),
                          'error_code': 'worker_error'}
            broker.post('/internal/runner/jobs/' + str(job['id']) + '/result', result)
            Path('/tmp/fsp-runner-heartbeat').touch()
            print(json.dumps({'event': 'job_finished', 'status': result['status'],
                              'duration_ms': result['duration_ms']}), flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError):
            print('{"event":"broker_unavailable"}', flush=True)
            time.sleep(2)


if __name__ == '__main__':
    main()
