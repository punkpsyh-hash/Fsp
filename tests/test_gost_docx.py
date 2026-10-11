import json
from pathlib import Path
import tempfile
import unittest

from docx import Document
from docx.oxml.ns import qn

from scripts.build_gost_docx import (
    HeadingNumberer,
    _add_body_section,
    _configure_document,
    DEFAULT_DOCUMENT_SET,
    ROOT,
    document_specs,
    parse_markdown_text,
)


class GostDocxTests(unittest.TestCase):
    def _manifest_payload(self):
        return json.loads(DEFAULT_DOCUMENT_SET.read_text(encoding="utf-8"))

    def _write_manifest(self, directory: Path, payload: dict) -> Path:
        path = directory / "document-set.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_parser_keeps_markdown_syntax_inside_fenced_code(self):
        blocks = parse_markdown_text(
            "# 18. API\n\n```bash\n# это комментарий, а не заголовок\n  curl http://localhost\n```\n"
        )

        self.assertEqual([(block.kind, block.level) for block in blocks], [("heading", 1), ("code", 0)])
        self.assertEqual(blocks[1].text, "# это комментарий, а не заголовок\n  curl http://localhost")

    def test_parser_preserves_table_pipes_inside_inline_code(self):
        blocks = parse_markdown_text("| Поле | Значение |\n|---|---|\n| режим | `GET|POST` |\n")

        self.assertEqual(blocks[0].rows, (("Поле", "Значение"), ("режим", "`GET|POST`")))

    def test_parser_recognizes_legacy_engineering_diagram_marker(self):
        blocks = parse_markdown_text("Текст.\n\n<!-- diagram_components -->\n")

        self.assertEqual([(block.kind, block.target) for block in blocks], [
            ("paragraph", ""),
            ("figure", "diagram_components"),
        ])

    def test_heading_numberer_preserves_explicit_instruction_numbers(self):
        blocks = parse_markdown_text(
            "# 53. Развёртывание\n\n## Выбор режима\n\n## 1. Подготовка\n\n### Проверка\n"
        )
        numberer = HeadingNumberer(blocks, "53")

        self.assertEqual(numberer.number(1, blocks[0].text), "53. Развёртывание")
        self.assertEqual(numberer.number(2, blocks[1].text), "Выбор режима")
        self.assertEqual(numberer.number(2, blocks[2].text), "1. Подготовка")
        self.assertEqual(numberer.number(3, blocks[3].text), "1.1. Проверка")

    def test_real_manifest_contains_seven_outputs_and_nineteen_published_sources(self):
        payload = self._manifest_payload()
        specs = document_specs()
        self.assertEqual({spec.key for spec in specs}, {
            "self-deployment-guide",
            "release-guide",
            "api-guide",
            "documentation",
            "technical-report",
            "project-report",
            "all-documents",
        })
        self.assertEqual(len(payload["published_sources"]), 19)
        all_documents = next(spec for spec in specs if spec.key == "all-documents")
        self.assertEqual(
            [source.relative_to(ROOT).as_posix() for source in all_documents.sources],
            payload["published_sources"],
        )

    def test_missing_manifest_fails_closed(self):
        with self.assertRaisesRegex(FileNotFoundError, "Манифест письменного комплекта"):
            document_specs(Path("D:/Codex/Temp/fsp-gost-documents/absent-document-set.json"))

    def test_duplicate_published_source_is_rejected(self):
        payload = self._manifest_payload()
        payload["published_sources"].append(payload["published_sources"][0])
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._write_manifest(Path(directory), payload)
            with self.assertRaisesRegex(ValueError, "повторяющиеся источники"):
                document_specs(manifest)

    def test_duplicate_document_source_is_rejected(self):
        payload = self._manifest_payload()
        release = next(item for item in payload["documents"] if item["id"] == "release-guide")
        release["sources"].append(release["sources"][0])
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._write_manifest(Path(directory), payload)
            with self.assertRaisesRegex(ValueError, "повторяющиеся источники"):
                document_specs(manifest)

    def test_path_traversal_is_rejected(self):
        payload = self._manifest_payload()
        payload["published_sources"][0] = "docs/../README.md"
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._write_manifest(Path(directory), payload)
            with self.assertRaisesRegex(ValueError, "внутри docs"):
                document_specs(manifest)

    def test_missing_source_is_rejected(self):
        payload = self._manifest_payload()
        payload["published_sources"][0] = "docs/99-missing.md"
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._write_manifest(Path(directory), payload)
            with self.assertRaisesRegex(FileNotFoundError, "источник не найден"):
                document_specs(manifest)

    def test_document_cannot_add_source_outside_published_set(self):
        payload = self._manifest_payload()
        release = next(item for item in payload["documents"] if item["id"] == "release-guide")
        release["sources"].append("docs/README.md")
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._write_manifest(Path(directory), payload)
            with self.assertRaisesRegex(ValueError, "неопубликованные источники"):
                document_specs(manifest)

    def test_numbered_file_is_not_auto_published(self):
        required_ids = [
            "self-deployment-guide", "release-guide", "api-guide", "documentation",
            "technical-report", "project-report", "all-documents",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            current = docs / "00-current.md"
            unpublished = docs / "99-internal.md"
            current.write_text("# Current\n", encoding="utf-8")
            unpublished.write_text("# Internal\n", encoding="utf-8")
            payload = {
                "formatting_source": "docs/00-current.md",
                "published_sources": ["docs/00-current.md"],
                "documents": [
                    {"id": document_id, "title": document_id, "sources": ["docs/00-current.md"]}
                    for document_id in required_ids
                ],
            }
            manifest = self._write_manifest(root, payload)
            specs = document_specs(manifest, root=root)

        selected = {source for spec in specs for source in spec.sources}
        self.assertIn(current.resolve(), selected)
        self.assertNotIn(unpublished.resolve(), selected)

    def test_cover_and_body_use_independent_footers_and_body_starts_at_two(self):
        document = Document()

        _configure_document(document, "Проверка")
        document.add_paragraph("Титул")
        _add_body_section(document)

        title_properties = document.styles["Title"].element.get_or_add_pPr()
        self.assertIsNone(title_properties.find(qn("w:pBdr")))
        self.assertEqual(len(document.sections), 2)
        cover_footer_xml = document.sections[0].footer._element.xml
        self.assertNotIn(" PAGE ", cover_footer_xml)
        body_section = document.sections[1]
        self.assertFalse(body_section.footer.is_linked_to_previous)
        page_numbering = body_section._sectPr.find(qn("w:pgNumType"))
        self.assertEqual(page_numbering.get(qn("w:start")), "2")
        footer_xml = body_section.footer._element.xml
        self.assertNotIn(" IF ", footer_xml)
        self.assertEqual(footer_xml.count(" PAGE "), 1)
        for element in document.styles.element.iter():
            for key, value in element.attrib.items():
                local_name = key.rsplit("}", 1)[-1]
                if local_name == "color":
                    self.assertEqual(value, "000000")
                self.assertNotIn(local_name, {"themeColor", "themeTint", "themeShade"})


if __name__ == "__main__":
    unittest.main()
