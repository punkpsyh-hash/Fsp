"""Регрессии безопасного создания и дополнения локального ``.env``."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == 'nt', reason='init_env выполняется в Linux-контейнере')


def isolated_script(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    target = scripts / 'init_env.py'
    shutil.copy2(ROOT / 'scripts/init_env.py', target)
    return target


def run_init(script):
    return subprocess.run([sys.executable, str(script)], text=True, capture_output=True,
                          check=False)


def values(path):
    return dict(line.split('=', 1) for line in path.read_text(encoding='utf-8').splitlines()
                if '=' in line and not line.lstrip().startswith('#'))


def test_existing_configuration_is_preserved_byte_for_byte(tmp_path):
    script = isolated_script(tmp_path)
    env_file = tmp_path / '.env'
    original = ('FSP_DB_PASSWORD=existing-db\n'
                'FSP_RUNNER_TOKEN=existing-runner\n'
                'FSP_LOCAL_MODEL_API_KEY=existing-model-key\n'
                'CUSTOM_SETTING=preserve-me\n')
    env_file.write_text(original, encoding='utf-8')

    result = run_init(script)

    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding='utf-8') == original
    assert '.env уже настроен' in result.stdout


def test_missing_local_key_is_generated_once_and_repeat_is_stable(tmp_path):
    script = isolated_script(tmp_path)
    env_file = tmp_path / '.env'
    env_file.write_text('FSP_DB_PASSWORD=existing-db\nFSP_RUNNER_TOKEN=existing-runner\n',
                        encoding='utf-8')

    first = run_init(script)
    after_first = env_file.read_bytes()
    generated = values(env_file)['FSP_LOCAL_MODEL_API_KEY']
    second = run_init(script)

    assert first.returncode == 0, first.stderr
    assert len(generated) >= 48
    assert second.returncode == 0, second.stderr
    assert env_file.read_bytes() == after_first
    assert values(env_file)['FSP_LOCAL_MODEL_API_KEY'] == generated


def test_blank_local_key_fails_without_changing_configuration(tmp_path):
    script = isolated_script(tmp_path)
    env_file = tmp_path / '.env'
    original = ('FSP_DB_PASSWORD=existing-db\n'
                'FSP_RUNNER_TOKEN=existing-runner\n'
                'FSP_LOCAL_MODEL_API_KEY=   \n')
    env_file.write_text(original, encoding='utf-8')

    result = run_init(script)

    assert result.returncode != 0
    assert 'FSP_LOCAL_MODEL_API_KEY пуст' in result.stderr
    assert env_file.read_text(encoding='utf-8') == original


def test_env_symlink_is_rejected_without_touching_target(tmp_path):
    script = isolated_script(tmp_path)
    outside = tmp_path / 'outside.env'
    original = b'FSP_DB_PASSWORD=outside\n'
    outside.write_bytes(original)
    (tmp_path / '.env').symlink_to(outside)

    result = run_init(script)

    assert result.returncode != 0
    assert outside.read_bytes() == original
