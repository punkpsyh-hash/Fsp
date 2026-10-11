"""Безопасная офлайн-проверка и атомарная загрузка закреплённой модели."""
from hashlib import sha256
import io
import json

import pytest

from ml import fetch_model


FILES = {
    'config.json': b'config',
    'model.safetensors': b'weights',
    'tokenizer.json': b'tokenizer',
}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def write_manifest(tmp_path, files=FILES, **changes):
    manifest = {
        'model_id': fetch_model.MODEL_ID,
        'revision': fetch_model.MODEL_REVISION,
        'files': {name: sha256(content).hexdigest() for name, content in files.items()},
    }
    manifest.update(changes)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return path


def write_model(target, files=FILES):
    for name, content in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def test_release_manifest_uses_the_runtime_pinned_model():
    assert fetch_model.MODEL_ID == 'Qwen/Qwen3-4B-Instruct-2507'
    assert fetch_model.MODEL_REVISION == 'cdbee75f17c01a7cc42f958dc650907174af0554'
    manifest = fetch_model.load_manifest(
        fetch_model.ROOT / 'ml/release/model-serving-v3-manifest.json')
    assert manifest['model_id'] == fetch_model.MODEL_ID
    assert manifest['revision'] == fetch_model.MODEL_REVISION


def test_existing_correct_model_and_verify_only_never_use_network(tmp_path, monkeypatch):
    target = tmp_path / 'model'
    write_model(target)
    manifest = write_manifest(tmp_path)
    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda *args, **kwargs: pytest.fail('network used'))
    assert fetch_model.run(target, manifest) == 0
    assert fetch_model.run(target, manifest, verify_only=True) == 0


@pytest.mark.parametrize('problem', ['missing', 'changed', 'extra'])
def test_verify_only_reports_incomplete_model_without_network(tmp_path, monkeypatch, problem, capsys):
    target = tmp_path / 'model'
    write_model(target)
    if problem == 'missing':
        (target / 'tokenizer.json').unlink()
    elif problem == 'changed':
        (target / 'tokenizer.json').write_bytes(b'changed')
    else:
        (target / 'extra.txt').write_bytes(b'extra')
    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda *args, **kwargs: pytest.fail('network used'))
    assert fetch_model.main(['--target', str(target), '--manifest', str(write_manifest(tmp_path)),
                             '--verify-only']) == 1
    assert problem in capsys.readouterr().out


def test_interrupted_download_is_recovered_on_rerun(tmp_path, monkeypatch):
    target = tmp_path / 'model'
    manifest = write_manifest(tmp_path)

    class Interrupted(Response):
        def read(self, size=-1):
            if self.tell():
                raise OSError('synthetic interruption')
            return super().read(2)

    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda *args, **kwargs: Interrupted(b'partial'))
    with pytest.raises(OSError, match='interruption'):
        fetch_model.run(target, manifest)
    assert (target / 'config.json.part').read_bytes() == b'pa'
    assert not (target / 'config.json').exists()

    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda url, **kwargs: Response(FILES[url.rsplit('/', 1)[-1]]))
    assert fetch_model.run(target, manifest) == 0
    assert not list(target.rglob('*.part'))
    assert {path.name: path.read_bytes() for path in target.iterdir()} == FILES


def test_hash_mismatch_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    target = tmp_path / 'model'
    write_model(target)
    original = b'existing-invalid-file'
    (target / 'model.safetensors').write_bytes(original)
    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda *args, **kwargs: Response(b'bad-response'))
    with pytest.raises(ValueError, match='SHA-256'):
        fetch_model.run(target, write_manifest(tmp_path))
    assert (target / 'model.safetensors').read_bytes() == original


@pytest.mark.parametrize('name', ['../outside', '/absolute', r'dir\file', 'C:/absolute'])
def test_manifest_rejects_unsafe_paths_before_network_or_write(tmp_path, monkeypatch, name):
    files = dict(FILES)
    files[name] = b'unsafe'
    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda *args, **kwargs: pytest.fail('network used'))
    with pytest.raises(ValueError, match='имя файла'):
        fetch_model.run(tmp_path / 'model', write_manifest(tmp_path, files))
    assert not (tmp_path / 'model').exists()
    assert not (tmp_path / 'outside').exists()


def test_unpinned_revision_and_symlink_targets_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_model.urllib.request, 'urlopen',
                        lambda *args, **kwargs: pytest.fail('network used'))
    unpinned = write_manifest(tmp_path, revision='main')
    with pytest.raises(ValueError, match='commit'):
        fetch_model.run(tmp_path / 'model', unpinned)

    manifest = write_manifest(tmp_path)
    target = tmp_path / 'model'
    target.mkdir()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'outside')
    (target / 'config.json').symlink_to(outside)
    with pytest.raises(ValueError, match='Ссылки'):
        fetch_model.run(target, manifest)
    assert outside.read_bytes() == b'outside'
