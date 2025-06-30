from exporters.base import Exporter
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from utils.logger import get_logger
from utils.exceptions import exception_handler
from utils.helpers import split_by_h2, extract_text_blocks

logger = get_logger("pdf_exporter")

class PdfExporter(Exporter):
    """PDF 檔案匯出"""

    @exception_handler
    def export(self, file_path: str):
        logger.info(f"Exporting PDF to {file_path}")

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="Section", fontSize=16, leading=20, spaceAfter=12))
        styles.add(ParagraphStyle(name="Subtitle", fontSize=13, leading=16, spaceAfter=8))
        styles.add(ParagraphStyle(name="Body", fontSize=11, leading=14, spaceAfter=6))

        story = [
            Paragraph(self.title, styles["Title"]),
            Spacer(1, 6),
            Paragraph(self.period, styles["Body"]),
            Spacer(1, 6),
            Paragraph(self.extra, styles["Body"]),
            PageBreak()
        ]

        for section, items in self.content.items():
            story.append(Paragraph(section, styles["Section"]))
            for subtitle, body in items.items():
                for sub_title, content in split_by_h2(body):
                    story.append(Paragraph(sub_title.strip(), styles["Subtitle"]))
                    for para in extract_text_blocks(content):
                        # 處理條列符號
                        if para.startswith("• "):
                            story.append(Paragraph(para, styles["Body"]))
                        else:
                            story.append(Paragraph(para, styles["Body"]))

        SimpleDocTemplate(
            file_path,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40,
        ).build(story)

        logger.info("PDF export completed")