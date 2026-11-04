"""PySide6 PDF renderer for the pure report document builder."""
from pathlib import Path
import os
import tempfile
from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from reporting.pdf import report_html


def write_report_pdf(path, report, **options):
    """Print a paginated, searchable A4 document; propagate write failures."""
    path = Path(path)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                      QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter))
    doc = QTextDocument()
    families = set(QFontDatabase.families())
    family = next((f for f in ('Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC') if f in families), 'sans-serif')
    doc.setDefaultFont(QFont(family, 10))
    doc.setDefaultStyleSheet('h1 {font-size:18pt;color:#17344d;} h2 {font-size:12pt;color:#17344d;}'
                            'th {background:#e8eef4;text-align:left;} td {border-bottom:1px solid #dbe2e8;}'
                            'p {line-height:130%;} table {font-size:9pt;}')
    analysis = options.get('analysis') or {}
    chart_sources = {}
    charts = (analysis.get('presentation') or {}).get('charts', [])
    if charts:
        try:
            import pyqtgraph as pg
        except ImportError:
            pg = None
        from reporting.models import EvidenceChart
        from ui.report_analysis import chart_image
        for index, payload in enumerate(charts):
            chart = EvidenceChart.model_validate(payload)
            uri = f'analysis-chart://{index}'
            image = chart_image(chart, pg)
            doc.addResource(QTextDocument.ImageResource, QUrl(uri), image)
            chart_sources[chart.chart_id] = (uri, round(500 * image.height() / image.width()))
    doc.setHtml(report_html(report, **options, chart_sources=chart_sources))
    # Qt reports some output failures only to stderr. Render to a sibling file
    # and replace the destination only after the printer has produced a PDF.
    fd, temporary = tempfile.mkstemp(suffix='.pdf', dir=path.parent)
    os.close(fd)
    try:
        printer.setOutputFileName(temporary)
        doc.print_(printer)
        if Path(temporary).stat().st_size == 0:
            raise OSError('PDF 未写入，请检查文件权限和磁盘空间')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
