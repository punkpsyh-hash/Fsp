"""Пересобрать canonical письменный комплект только в docs/delivery/gost/."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'docs/delivery/gost'


def build(evidence_dir=None):
    evidence_dir = evidence_dir or ROOT/'docs/release/current-documents'
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for script in ('build_gost_docx.py', 'build_gost_documents.py'):
        subprocess.run([sys.executable, str(ROOT/'scripts'/script)], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/build_api_guide.py'),
                    '--output', str(OUTPUT/'api-guide.pdf'),
                    '--report', str(evidence_dir/'api-pdf.json'),
                    '--check-reproducibility'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/verify_gost_artifacts.py'),
                    '--output', str(evidence_dir/'artifacts.json')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/package_gost_documents.py'),
                    '--report', str(evidence_dir/'package.json')], cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path)
    build(parser.parse_args().evidence_dir)
