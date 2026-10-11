"""Скачать закреплённую базовую модель или проверить её без сети.

    python ml/fetch_model.py [--target ml/models/qwen3-4b-instruct-2507-serving-v3]
                             [--manifest ml/release/model-serving-v3-manifest.json]
                             [--verify-only]

Только стандартная библиотека. Файлы скачиваются в ``.part`` и атомарно заменяют
целевой файл только после совпадения SHA-256. Повторный запуск перезапишет
неполный ``.part``; уже верные файлы не изменяются.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = 'Qwen/Qwen3-4B-Instruct-2507'
MODEL_REVISION = 'cdbee75f17c01a7cc42f958dc650907174af0554'
SHA256_RE = re.compile(r'[0-9a-f]{64}')
NAME_RE = re.compile(r'[A-Za-z0-9._/-]+')


def digest(path):
    value = sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1 << 20), b''):
            value.update(chunk)
    return value.hexdigest()


def load_manifest(path):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or set(manifest) != {'model_id', 'revision', 'files'}:
        raise ValueError('Неверный manifest модели')
    if manifest['model_id'] != MODEL_ID or manifest['revision'] != MODEL_REVISION:
        raise ValueError('Manifest должен указывать закреплённую модель и commit')
    files = manifest['files']
    if not isinstance(files, dict):
        raise ValueError('Manifest не содержит списка файлов')
    for name, expected in files.items():
        pure = PurePosixPath(name) if isinstance(name, str) else None
        if (pure is None or not NAME_RE.fullmatch(name) or '\\' in name or pure.is_absolute()
                or pure.as_posix() != name or name == '.' or '..' in pure.parts or ':' in name
                or name.endswith('.part')):
            raise ValueError('Недопустимое имя файла в manifest')
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise ValueError('Недопустимый SHA-256 в manifest')
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError('Имена файлов в manifest не должны совпадать без учёта регистра')
    if not 3 <= len(files) <= 100 or 'config.json' not in files or not any(
            name.endswith('.safetensors') for name in files):
        raise ValueError('Manifest не содержит полного списка файлов')
    return manifest


def inspect_target(target, files, allow_parts=False):
    if target.is_symlink():
        raise ValueError('Каталог модели не должен быть ссылкой')
    actual = {}
    if target.exists():
        if not target.is_dir():
            raise ValueError('Путь модели не является каталогом')
        for path in target.rglob('*'):
            if path.is_symlink():
                raise ValueError('Ссылки в каталоге модели запрещены')
            if path.is_file():
                actual[path.relative_to(target).as_posix()] = path
    allowed_parts = {name + '.part' for name in files} if allow_parts else set()
    extra = sorted(set(actual) - set(files) - allowed_parts)
    missing = []
    changed = []
    for name, expected in files.items():
        path = actual.get(name)
        if path is None:
            missing.append(name)
        elif digest(path) != expected:
            changed.append(name)
    return missing, changed, extra


def _download(model, revision, name, expected, target):
    path = target.joinpath(*PurePosixPath(name).parts)
    part = path.with_name(path.name + '.part')
    if path.exists() and not path.is_file():
        raise ValueError(f'Целевой путь не является файлом: {name}')
    if part.is_symlink() or (part.exists() and not part.is_file()):
        raise ValueError(f'Недопустимый временный путь: {name}.part')
    path.parent.mkdir(parents=True, exist_ok=True)
    url = 'https://huggingface.co/{}/resolve/{}/{}'.format(
        model, revision, urllib.parse.quote(name, safe='/'))
    print('download', name, flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, part.open('wb') as output:
        while chunk := response.read(1 << 20):
            output.write(chunk)
    if digest(part) != expected:
        raise ValueError(f'SHA-256 не совпал: {name}')
    part.replace(path)


def run(target, manifest_path, verify_only=False):
    manifest = load_manifest(manifest_path)
    files = manifest['files']
    missing, changed, extra = inspect_target(target, files, allow_parts=not verify_only)
    if verify_only:
        for label, names in (('missing', missing), ('changed', changed), ('extra', extra)):
            for name in names:
                print(f'{label:8} {name}')
        if missing or changed or extra:
            return 1
        print('Модель полностью совпадает с manifest:', target)
        return 0
    if extra:
        raise ValueError('Лишние файлы в каталоге модели: ' + ', '.join(extra))
    target.mkdir(parents=True, exist_ok=True)
    pending = set(missing) | set(changed)
    for name, expected in files.items():
        if name not in pending:
            print('ok      ', name)
            continue
        _download(manifest['model_id'], manifest['revision'], name, expected, target)
    missing, changed, extra = inspect_target(target, files)
    if missing or changed or extra:
        raise ValueError('Каталог модели не совпадает с manifest')
    print('Модель полностью совпадает с manifest:', target)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path,
                        default=ROOT / 'ml/models/qwen3-4b-instruct-2507-serving-v3')
    parser.add_argument('--manifest', type=Path,
                        default=ROOT / 'ml/release/model-serving-v3-manifest.json')
    parser.add_argument('--verify-only', action='store_true',
                        help='только офлайн-проверка, без скачивания')
    args = parser.parse_args(argv)
    try:
        return run(args.target, args.manifest, args.verify_only)
    except (OSError, ValueError) as error:
        print('Ошибка:', error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
