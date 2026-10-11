"""Реальные проверки VM, без pytest и без подключения к API/основной БД."""
import json
import argparse
import hashlib
from pathlib import Path
import statistics
import time
from runner.engine import VMRunner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true', help='Шесть основных VM проверок, в том числе TCG CI')
    parser.add_argument('--output', help='Путь JSON отчёта внутри контейнера')
    args = parser.parse_args()
    runner = VMRunner()
    results = []

    def case(name, language, source, payload=None, status='ok', stdout=None):
        result = runner.run_case(language, source, payload or {})
        assert result.status == status, (name, result.status, result.error_code)
        if stdout is not None:
            assert result.stdout.strip() == stdout, (name, 'unexpected_stdout')
        results.append({'name': name, 'status': 'passed', 'duration_ms': result.duration_ms,
                        'boot_ms': result.boot_ms})
        print(json.dumps(results[-1]), flush=True)

    # Only reviewed benign print before the feasibility gate has passed.
    case('KVM/TCG real VM readiness', 'python', 'print("VM ready")', stdout='VM ready')
    case('Python stdin', 'python', 'a,b=map(int,input().split()); print(a+b)', {'stdin': '17 25\n'}, stdout='42')
    case('JavaScript stdin', 'javascript', 'const fs=require("fs"); console.log(fs.readFileSync(0,"utf8").trim().split(/\\s+/).map(Number).reduce((a,b)=>a+b,0))', {'stdin': '17 25\n'}, stdout='42')
    case('SQLite query', 'sql', 'SELECT SUM(n) FROM samples',
         {'setup': 'CREATE TABLE samples(n INTEGER); INSERT INTO samples VALUES(17),(25);'}, stdout='[[42]]')
    if args.smoke:
        case('Python CPU timeout', 'python', 'while True: pass', status='timeout')
        result = runner.grade({'id': 'probe', 'lease_token': 'probe', 'language': 'python', 'source': 'print(43)',
                               'tests': [{'expected': '42'}]})
        assert result['status'] == 'wrong_answer' and result['passed'] == 0, (result['status'], result.get('error_code'), result['duration_ms'])
        results.append({'name': 'wrong answer', 'status': 'passed'})
        finish(runner, results, args.output)
        return
    case('Python syntax', 'python', 'this is not valid python!', status='runtime_error')
    case('JavaScript syntax', 'javascript', 'const = ;', status='runtime_error')
    case('Python CPU timeout', 'python', 'while True: pass', status='timeout')
    case('JavaScript CPU timeout', 'javascript', 'while(true){}', status='timeout')
    case('SQL progress timeout', 'sql', 'WITH RECURSIVE cnt(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM cnt) SELECT sum(x) FROM cnt', status='timeout')
    case('Python output limit', 'python', 'print("x" * 100000)', status='runtime_error')
    case('JavaScript output limit', 'javascript', 'console.log("x".repeat(100000))', status='runtime_error')
    case('Python memory limit', 'python', 'x=bytearray(512*1024*1024)', status='runtime_error')
    case('Guest UID/files/credentials isolation', 'python', '''import os
from pathlib import Path
assert os.getuid()==10001
assert not any(Path(p).exists() for p in ['/Volume1','/app','.env','/var/run/docker.sock'])
assert 'FSP_RUNNER_TOKEN' not in os.environ
assert 'FSP_DB_PASSWORD' not in os.environ
assert not Path('/dev/kvm').exists()
print('isolated')''', stdout='isolated')
    case('Network isolation', 'python', '''import socket
s=socket.socket(); s.settimeout(.5)
try: s.connect(('1.1.1.1',443))
except OSError: print('network_denied')
else: raise RuntimeError('network_available')''', stdout='network_denied')
    case('Readonly runtime', 'python', '''try:
 open('/guest_agent.py','w').write('broken')
except PermissionError: print('readonly')
else: raise RuntimeError('runtime_write')''', stdout='readonly')
    case('Job A local write', 'python', 'open("/work/neighbor_marker", "w").write("job A"); print("written")', stdout='written')
    case('Job B fresh VM', 'python', 'from pathlib import Path; assert not Path("/work/neighbor_marker").exists(); print("fresh")', stdout='fresh')
    case('SQL ATTACH denied', 'sql', "ATTACH DATABASE '/tmp/external.db' AS external", status='runtime_error')
    case('SQL load_extension denied', 'sql', "SELECT load_extension('/lib/x.so')", status='runtime_error')
    case('SQL PRAGMA denied', 'sql', 'PRAGMA database_list', status='runtime_error')
    case('SQL write denied', 'sql', 'DELETE FROM samples', {'setup': 'CREATE TABLE samples(n INTEGER);'}, status='runtime_error')
    case('SQL multiple statements denied', 'sql', 'SELECT 1; SELECT 2;', status='runtime_error')
    # FDs/pids/CPU are bounded even when a task spawns children; parent guard kills the VM.
    case('Process budget', 'python', '''import os
children=[]
try:
 for i in range(100):
  pid=os.fork()
  if pid==0:
   import time; time.sleep(1); os._exit(0)
  children.append(pid)
except OSError:
 print('pids_denied',flush=True)
for pid in children: os.waitpid(pid,0)''', stdout='pids_denied')
    case('Recovery after hostile cases', 'python', 'print(42)', stdout='42')
    for language, source, expected in [('python', 'print(42)', '42'),
                                        ('javascript', 'console.log(42)', '42'), ('sql', 'SELECT 42', [[42]])]:
        result = runner.grade({'id': 'probe', 'lease_token': 'probe', 'language': language, 'source': source,
                               'tests': [{'stdin': '', 'setup': '', 'expected': expected}]})
        assert result['status'] == 'passed' and result['passed'] == 1
        assert not any(key in result for key in ('stdout', 'stderr', 'source', 'tests', 'expected'))
        print(json.dumps({'name': language + ' oracle/hidden-output redaction', 'status': 'passed'}), flush=True)
        results.append({'name': language + ' oracle/hidden-output redaction', 'status': 'passed'})
    result = runner.grade({'id': 'probe', 'lease_token': 'probe', 'language': 'python', 'source': 'print(43)',
                           'tests': [{'expected': '42'}]})
    assert result['status'] == 'wrong_answer' and result['passed'] == 0
    results.append({'name': 'wrong answer', 'status': 'passed'})
    finish(runner, results, args.output)


def finish(runner, results, output):
    boots = [check['boot_ms'] for check in results if 'boot_ms' in check]
    report = {'summary': {'checks': len(results), 'failed': 0, 'accelerator': runner.accelerator,
                         'versions': runner.versions, 'boot_ms_median': statistics.median(boots),
                         'boot_ms_max': max(boots), 'guest_memory_mib': 512,
                         'cpu_seconds': 2 if runner.accelerator == 'kvm' else 20,
                         'output_bytes': 65536, 'max_pids_per_uid': 16,
                         'sha256': {name: hashlib.sha256((runner.guest / name).read_bytes()).hexdigest()
                                    for name in ('vmlinuz', 'initramfs.cpio.gz')}}, 'checks': results}
    if output:
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
