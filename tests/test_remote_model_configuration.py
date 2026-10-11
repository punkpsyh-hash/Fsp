"""Настройка модели сохраняет независимые настройки и не принимает чужой stdin."""
import pytest

from scripts.configure_remote_model import configure


def test_configuration_preserves_other_values_and_updates_only_model_policy(tmp_path):
    path = tmp_path / '.env'
    path.write_text('FSP_DB_PASSWORD=synthetic-db-value\nFSP_RUNNER_TOKEN=synthetic-runner-value\n'
                    'FSP_INTEGRITY_ENFORCE=0\nFSP_LLM_API_KEY=obsolete-synthetic-key\n# local comment\n')
    configure(path, 'FSP_LOCAL_MODEL_API_KEY=' + 'a' * 48 + '\n')
    content = path.read_text()
    assert 'FSP_DB_PASSWORD=synthetic-db-value\n' in content
    assert 'FSP_RUNNER_TOKEN=synthetic-runner-value\n' in content
    assert '# local comment\n' in content
    assert content.count('FSP_LLM_API_KEY=') == 1 and 'obsolete-synthetic-key' not in content
    assert 'FSP_INTEGRITY_ENFORCE=1\n' in content


@pytest.mark.parametrize('line', ['', 'FSP_LOCAL_MODEL_API_KEY=short',
                               'FSP_LOCAL_MODEL_API_KEY=' + 'a' * 48 + '\nANOTHER_KEY=value'])
def test_invalid_configuration_does_not_change_env(tmp_path, line):
    path = tmp_path / '.env'
    path.write_text('FSP_DB_PASSWORD=synthetic-db-value\n')
    original = path.read_bytes()
    with pytest.raises(ValueError):
        configure(path, line)
    assert path.read_bytes() == original


def test_configuration_cannot_follow_env_symlink(tmp_path):
    target = tmp_path / 'other.env'
    target.write_text('FSP_DB_PASSWORD=synthetic-db-value\n')
    link = tmp_path / '.env'
    link.symlink_to(target)
    with pytest.raises(OSError):
        configure(link, 'FSP_LOCAL_MODEL_API_KEY=' + 'a' * 48)
    assert target.read_text() == 'FSP_DB_PASSWORD=synthetic-db-value\n'


def test_replace_failure_preserves_original_configuration_and_cleans_temp(tmp_path, monkeypatch):
    from scripts import configure_remote_model
    path = tmp_path / '.env'
    path.write_text('FSP_DB_PASSWORD=synthetic-db-value\nFSP_RUNNER_TOKEN=synthetic-runner-value\n')
    original = path.read_bytes()
    def fail_replace(*args):
        raise OSError('synthetic replace failure')
    monkeypatch.setattr(configure_remote_model.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='synthetic replace failure'):
        configure(path, 'FSP_LOCAL_MODEL_API_KEY=' + 'a' * 48)
    assert path.read_bytes() == original
    assert list(tmp_path.glob('.env.model-*')) == []
