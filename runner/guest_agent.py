"""PID 1, доверенная сторона внутри VM. Ответов hidden tests здесь нет."""
import ctypes
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import subprocess
import tempfile
import time

OUTPUT_LIMIT = 65536
UID = 10001


def restrictions(seconds, language):
    os.setgroups([])
    os.setgid(UID)
    os.setuid(UID)
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # V8 reserves a large virtual range. Its physical memory is capped by VM RAM,
    # and its heap separately; Python/SQLite also have an address-space budget.
    if language != 'javascript':
        resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024, 192 * 1024 * 1024))
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError('no_new_privs')


def run(payload):
    language = payload['language']
    # Host explicitly scales the software-emulation profile; task cannot edit this
    # root-only payload. KVM remains 1–3 s, TCG can use 10–30 s.
    seconds = max(1, min(30, int(payload.get('execution_cpu_seconds', payload.get('time_limit_seconds', 2)))))
    work = Path('/work')
    os.chown(work, UID, UID)
    source = work / ('main.py' if language == 'python' else 'main.js')
    source.write_text(payload['source'])
    source.chmod(0o444)
    if language == 'python':
        command = ['/usr/local/bin/python3.12', '-I', '-B', str(source)]
    elif language == 'javascript':
        command = ['/usr/local/bin/node', '--jitless', '--max-old-space-size=64', str(source)]
    elif language == 'sql':
        command = ['/usr/local/bin/python3.12', '-I', '-B', '/sql_guest.py']
    else:
        return {'status': 'system_error', 'error_code': 'unsupported_language'}
    input_data = (json.dumps(payload) if language == 'sql' else payload.get('stdin', '')).encode()
    # A regular temporary stdin avoids a pipe deadlock when a task never reads it.
    input_stream = tempfile.TemporaryFile(dir='/tmp')
    input_stream.write(input_data)
    input_stream.seek(0)
    process = subprocess.Popen(command, stdin=input_stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=work, env={'PATH': '/usr/local/bin:/bin', 'HOME': '/work', 'TMPDIR': '/work',
                               'LD_LIBRARY_PATH': os.environ['LD_LIBRARY_PATH']}, start_new_session=True,
                               preexec_fn=lambda: restrictions(seconds, language))
    input_stream.close()
    selector = selectors.DefaultSelector()
    for stream in (process.stdout, process.stderr):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    stdout = bytearray()
    total = 0
    deadline = time.monotonic() + seconds + 2
    status = 'ok'
    while selector.get_map():
        if time.monotonic() >= deadline:
            status = 'timeout'
            break
        for key, _ in selector.select(timeout=0.05):
            chunk = os.read(key.fileobj.fileno(), 8192)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            total += len(chunk)
            if total > OUTPUT_LIMIT:
                status = 'output_limit'
                break
            if key.fileobj is process.stdout:
                stdout.extend(chunk)
        if status != 'ok':
            break
    if status != 'ok' or process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    returncode = process.wait()
    if status == 'ok' and returncode != 0:
        status = 'timeout' if returncode in (-signal.SIGXCPU, -signal.SIGKILL) or (language == 'sql' and returncode == 124) else 'runtime_error'
    return {'status': status, 'stdout': stdout.decode('utf-8', errors='replace') if status == 'ok' else ''}


try:
    payload = json.loads(Path('/job.json').read_text())
    # Signal readiness before executing code: missing boot is infrastructure error.
    print('FSP_VM_READY', flush=True)
    result = run(payload)
except Exception:
    result = {'status': 'system_error', 'error_code': 'guest_agent_error'}
print('FSP_VM_RESULT:' + json.dumps(result, ensure_ascii=True), flush=True)
os.sync()
subprocess.run(['/bin/poweroff', '-f'])
while True:
    time.sleep(60)
