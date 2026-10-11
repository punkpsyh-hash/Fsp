"""Совместимая сборка release-guide из единственного docs/document-set.json."""
import argparse
from pathlib import Path

from build_gost_documents import build_named
from gost_layout import ROOT


def build(
    output: Path,
    manifest: Path = ROOT / "docs/document-set.json",
) -> None:
    build_named("release-guide", output, manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs/delivery/gost/release-guide.pdf",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "docs/document-set.json",
    )
    arguments = parser.parse_args()
    build(arguments.out, arguments.manifest)
