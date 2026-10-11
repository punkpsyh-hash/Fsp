"""Собрать минимальный initramfs из закреплённых Docker/Debian runtimes."""
from pathlib import Path
import gzip
import json
import os
import re
import shutil
import subprocess

root = Path('/build/root')
out = Path('/build/guest')
root.mkdir(parents=True, exist_ok=True)
out.mkdir(parents=True, exist_ok=True)
for directory in ('bin', 'dev', 'proc', 'sys', 'tmp', 'work', 'run', 'etc'):
    (root / directory).mkdir(exist_ok=True)


def copy_file(path):
    source = Path(path)
    target = root / source.relative_to('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=True)


def libraries(path):
    result = subprocess.run(['ldd', str(path)], capture_output=True, text=True)
    for library in re.findall(r'(/[^\s()]+)', result.stdout):
        if Path(library).is_file():
            copy_file(library)


copy_file('/bin/busybox')
for command in ('sh', 'mount', 'poweroff', 'mkdir', 'chmod'):
    (root / 'bin' / command).symlink_to('busybox')
for binary in ('/usr/local/bin/python3.12', '/usr/local/bin/node'):
    copy_file(binary)
    libraries(binary)
copy_file('/usr/local/lib/libpython3.12.so.1.0')
shutil.copytree('/usr/local/lib/python3.12', root / 'usr/local/lib/python3.12',
                ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'ensurepip', 'idlelib', 'tkinter'))
for library in (root / 'usr/local/lib/python3.12/lib-dynload').glob('*.so'):
    libraries('/' + str(library.relative_to(root)))
shutil.copy2('/build/runner/guest_init.sh', root / 'init')
shutil.copy2('/build/runner/guest_agent.py', root / 'guest_agent.py')
shutil.copy2('/build/runner/sql_guest.py', root / 'sql_guest.py')
os.chmod(root / 'init', 0o755)
(root / 'etc/passwd').write_text('root:x:0:0:root:/:/bin/sh\ncandidate:x:10001:10001:candidate:/work:/bin/sh\n')
(root / 'etc/group').write_text('root:x:0:\ncandidate:x:10001:\n')
kernel = next(Path('/boot').glob('vmlinuz-*'))
shutil.copy2(kernel, out / 'vmlinuz')
archive = subprocess.run(['cpio', '-o', '-H', 'newc', '--owner=0:0'],
                         input='\n'.join(['.'] + sorted(str(p.relative_to(root)) for p in root.rglob('*'))).encode() + b'\n',
                         cwd=root, capture_output=True, check=True).stdout
with (out / 'initramfs.cpio.gz').open('wb') as stream:
    stream.write(gzip.compress(archive, compresslevel=6, mtime=0))
versions = {
    'python': subprocess.check_output(['/usr/local/bin/python3.12', '--version'], text=True).strip(),
    'javascript': 'Node ' + subprocess.check_output(['node', '--version'], text=True).strip(),
    'sql': 'SQLite ' + __import__('sqlite3').sqlite_version,
    'kernel': kernel.name.removeprefix('vmlinuz-'),
    'debian_packages': dict(line.split('=', 1) for line in subprocess.check_output(
        ['dpkg-query', '-W', '-f=${binary:Package}=${Version}\n', 'linux-image-amd64',
         'busybox-static', 'libsqlite3-0', 'libc6', 'libstdc++6', 'cpio'], text=True).splitlines()),
    'official_sources': {
        'debian_packages': 'https://www.debian.org/distrib/packages',
        'linux': 'https://tracker.debian.org/pkg/linux',
        'qemu': 'https://sources.debian.org/src/qemu/',
        'node': 'https://nodejs.org/download/release/' + subprocess.check_output(['node', '--version'], text=True).strip() + '/',
        'python': 'https://www.python.org/downloads/release/python-31213/',
    },
}
licenses = out / 'licenses'
licenses.mkdir(exist_ok=True)
for name, path in {
    'Node-LICENSE': Path('/build/node-LICENSE'),
    'Python-LICENSE': Path('/usr/local/lib/python3.12/LICENSE.txt'),
    'BusyBox-copyright': Path('/usr/share/doc/busybox-static/copyright'),
    'SQLite-copyright': Path('/usr/share/doc/libsqlite3-0/copyright'),
    'glibc-copyright': Path('/usr/share/doc/libc6/copyright'),
    'Linux-copyright': Path('/usr/share/doc') / ('linux-image-' + versions['kernel']) / 'copyright',
    'GPL-2': Path('/usr/share/common-licenses/GPL-2'),
    'LGPL-2.1': Path('/usr/share/common-licenses/LGPL-2.1'),
}.items():
    shutil.copy2(path, licenses / name)
(out / 'versions.json').write_text(json.dumps(versions))
print(json.dumps({'runtime': versions, 'initramfs_bytes': (out / 'initramfs.cpio.gz').stat().st_size}))
