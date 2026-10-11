"""VM boundary and host-side oracle. No task code ever runs on worker Linux."""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time

MAX_SOURCE = 32768
MAX_INPUT = 16384
MAX_SETUP = 32768
MAX_CASES = 10
MAX_SERIAL = 1024 * 1024


@dataclass
class CaseResult:
    status: str
    stdout: str = ''
    error_code: str | None = None
    duration_ms: int = 0
    boot_ms: int = 0


def cpio_file(name: str, data: bytes, mode: int = 0o100400) -> bytes:
    """Minimal newc archive, no shell/archive path interpolation."""
    def entry(path, payload, permissions, inode):
        encoded = path.encode() + b'\0'
        fields = (inode, permissions, 0, 0, 1, 0, len(payload), 0, 0, 0, 0, len(encoded), 0)
        header = b'070701' + b''.join(f'{field:08x}'.encode() for field in fields)
        start = header + encoded
        start += b'\0' * (-len(start) % 4)
        return start + payload + b'\0' * (-len(payload) % 4)
    archive = entry(name, data, mode, 1) + entry('TRAILER!!!', b'', 0, 2)
    return archive + b'\0' * (-len(archive) % 512)


class VMRunner:
    def __init__(self, guest_dir: str | Path = '/opt/fsp-guest', accelerator: str | None = None):
        self.guest = Path(guest_dir)
        self.accelerator = accelerator or os.environ.get('FSP_RUNNER_ACCEL', 'kvm')
        if self.accelerator not in ('kvm', 'tcg'):
            raise ValueError('invalid_accelerator')
        self.versions = json.loads((self.guest / 'versions.json').read_text())

    def command(self, initramfs):
        return ['qemu-system-x86_64', '-no-user-config', '-nodefaults',
                '-machine', 'q35', '-accel', self.accelerator,
                '-cpu', 'host' if self.accelerator == 'kvm' else 'max', '-smp', '1', '-m', '512',
                '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-nic', 'none',
                '-no-reboot', '-sandbox', 'on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny',
                '-kernel', str(self.guest / 'vmlinuz'), '-initrd', str(initramfs),
                '-append', 'console=ttyS0 quiet panic=1 random.trust_cpu=on rdinit=/init']

    def run_case(self, language: str, source: str, case: dict, seconds: int = 2) -> CaseResult:
        start = time.monotonic()
        if language not in ('python', 'javascript', 'sql'):
            return CaseResult('system_error', error_code='unsupported_language')
        stdin, setup = case.get('stdin', ''), case.get('setup', '')
        if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE or not isinstance(stdin, str) or len(stdin.encode()) > MAX_INPUT or not isinstance(setup, str) or len(setup.encode()) > MAX_SETUP:
            return CaseResult('system_error', error_code='payload_limit')
        seconds = max(1, min(3, int(seconds)))
        execution_seconds = seconds * (10 if self.accelerator == 'tcg' else 1)
        # Never copy expected outputs, IDs, lease tokens or broker credentials to VM.
        payload = {'language': language, 'source': source, 'stdin': stdin,
                   'setup': setup if language == 'sql' else '', 'time_limit_seconds': execution_seconds,
                   'execution_cpu_seconds': execution_seconds}
        ready_at = None
        result = None
        with tempfile.TemporaryDirectory(prefix='fsp-vm-') as directory:
            initramfs = Path(directory) / 'initramfs'
            with initramfs.open('wb') as stream, (self.guest / 'initramfs.cpio.gz').open('rb') as base:
                shutil.copyfileobj(base, stream)
                stream.write(gzip.compress(cpio_file('job.json', json.dumps(payload).encode()), mtime=0))
            try:
                process = subprocess.Popen(self.command(initramfs), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True,
                    env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'LANG': 'C'}, start_new_session=True)
            except OSError:
                return CaseResult('system_error', error_code='runtime_unavailable')
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            os.set_blocking(process.stdout.fileno(), False)
            buffer = bytearray()
            total = 0
            # No hidden acceleration fallback: CI uses explicit TCG with larger boot budget.
            boot_budget = 15 if self.accelerator == 'kvm' else 90
            deadline = start + boot_budget
            try:
                while time.monotonic() < deadline:
                    if process.poll() is not None and not selector.get_map():
                        break
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > MAX_SERIAL:
                            return CaseResult('system_error', error_code='protocol_limit')
                        buffer.extend(chunk)
                        while b'\n' in buffer:
                            line, _, tail = buffer.partition(b'\n')
                            buffer = bytearray(tail)
                            line = line.rstrip(b'\r')
                            if line == b'FSP_VM_READY' and ready_at is None:
                                ready_at = time.monotonic()
                                # Wall-clock limit remains enforced by host even if guest is compromised.
                                deadline = ready_at + execution_seconds + 4
                            elif line.startswith(b'FSP_VM_RESULT:'):
                                try:
                                    result = json.loads(line[len(b'FSP_VM_RESULT:'):])
                                except (ValueError, UnicodeError):
                                    return CaseResult('system_error', error_code='protocol_error')
                    if result is not None:
                        break
                duration = round((time.monotonic() - start) * 1000)
                boot = round((ready_at - start) * 1000) if ready_at else 0
                if result is None:
                    return CaseResult('timeout' if ready_at else 'system_error',
                                      error_code='execution_timeout' if ready_at else 'boot_failed', duration_ms=duration, boot_ms=boot)
                status = result.get('status')
                if status not in ('ok', 'timeout', 'runtime_error', 'output_limit', 'system_error'):
                    return CaseResult('system_error', error_code='protocol_error', duration_ms=duration, boot_ms=boot)
                stdout = result.get('stdout', '')
                if not isinstance(stdout, str) or len(stdout.encode()) > 65536:
                    return CaseResult('system_error', error_code='protocol_error', duration_ms=duration, boot_ms=boot)
                return CaseResult('runtime_error' if status == 'output_limit' else status, stdout,
                                  'output_limit' if status == 'output_limit' else result.get('error_code'), duration, boot)
            finally:
                selector.close()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    def grade(self, job: dict) -> dict:
        start = time.monotonic()
        tests = job.get('tests')
        language = job.get('language')
        output = {'lease_token': job['lease_token'], 'status': 'system_error', 'passed': 0,
                  'total': len(tests) if isinstance(tests, list) else 0, 'duration_ms': 0,
                  'runtime_version': self.versions.get(language, 'unknown') + '; Linux ' + self.versions['kernel'] + '; ' + self.accelerator + (' CPU x10' if self.accelerator == 'tcg' else '')}
        if not isinstance(tests, list) or not 1 <= len(tests) <= MAX_CASES:
            output['error_code'] = 'invalid_test_count'
            return output
        output['status'] = 'passed'
        for case in tests:
            if time.monotonic() - start >= (240 if self.accelerator == 'kvm' else 600):
                output.update(status='system_error', error_code='job_budget')
                break
            result = self.run_case(language, job['source'], case, job.get('time_limit_seconds', 2))
            if result.status != 'ok':
                output.update(status=result.status, error_code=result.error_code or result.status)
                break
            if language == 'sql':
                try:
                    matched = json.loads(result.stdout) == case['expected']
                except (ValueError, TypeError):
                    matched = False
            else:
                matched = result.stdout.rstrip() == case['expected'].rstrip()
            if matched:
                output['passed'] += 1
            else:
                output['status'] = 'wrong_answer'
        output['duration_ms'] = round((time.monotonic() - start) * 1000)
        # stdout/stderr and inputs are deliberately absent from all candidate diagnostics.
        return output
