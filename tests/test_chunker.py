import unittest

from app.types import Paragraph
from ingestion.chunker import chunk_paragraphs


class ChunkerTests(unittest.TestCase):
    def test_preserves_heading_and_respects_approximate_size(self):
        paragraphs = [
            Paragraph("员工年假为十天。转正后可以申请。", heading="休假制度", page_number=2),
            Paragraph("申请需要先由直属主管审批。审批通过后在人事系统登记。", heading="申请流程", page_number=3),
        ]
        chunks = chunk_paragraphs(paragraphs, chunk_size=18, overlap=4)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].heading, "休假制度")
        self.assertEqual(chunks[0].page_number, 2)
        self.assertTrue(all(chunk.content.strip() for chunk in chunks))

    def test_rejects_invalid_overlap(self):
        with self.assertRaises(ValueError):
            chunk_paragraphs([Paragraph("测试")], chunk_size=10, overlap=10)

    def test_never_mixes_different_headings_in_one_chunk(self):
        paragraphs = [
            Paragraph(
                "P0事故需要临时购买云资源，预计费用24000元。",
                heading="生产事故中的紧急采购",
            ),
            Paragraph(
                "员工计划连续休假七天，应至少提前十个工作日申请。",
                heading="长假与项目发布冲突",
            ),
        ]

        chunks = chunk_paragraphs(paragraphs, chunk_size=320, overlap=60)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].heading, "生产事故中的紧急采购")
        self.assertNotIn("连续休假", chunks[0].content)
        self.assertEqual(chunks[1].heading, "长假与项目发布冲突")
        self.assertNotIn("24000", chunks[1].content)


if __name__ == "__main__":
    unittest.main()
