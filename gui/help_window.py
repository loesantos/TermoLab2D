"""Janela do manual de uso (gui/manual/manual.html)."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

MANUAL = Path(__file__).resolve().parent / "manual" / "manual.html"


class ManualWindow(QtWidgets.QDialog):
    """Navegador simples do manual: voltar/avançar, início, busca e abrir no navegador."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual de uso — TermoLab2D")
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
        self.resize(1000, 780)

        self.browser = QtWidgets.QTextBrowser()
        self.browser.setOpenLinks(True)
        self.browser.setOpenExternalLinks(True)
        self.browser.setSearchPaths([str(MANUAL.parent)])

        style = self.style()
        bar = QtWidgets.QToolBar()
        bar.setIconSize(QtCore.QSize(18, 18))
        bar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.act_back = bar.addAction(style.standardIcon(QtWidgets.QStyle.SP_ArrowBack), "Voltar", self.browser.backward)
        self.act_fwd = bar.addAction(style.standardIcon(QtWidgets.QStyle.SP_ArrowForward), "Avançar", self.browser.forward)
        bar.addAction(style.standardIcon(QtWidgets.QStyle.SP_ArrowUp), "Índice", lambda: self.show_section("topo"))
        bar.addSeparator()
        self.search = QtWidgets.QLineEdit(placeholderText="Procurar no manual…", clearButtonEnabled=True)
        self.search.setMaximumWidth(260)
        self.search.returnPressed.connect(self.find_next)
        bar.addWidget(self.search)
        bar.addAction("Próximo", self.find_next)
        bar.addSeparator()
        bar.addAction(style.standardIcon(QtWidgets.QStyle.SP_DesktopIcon), "Abrir no navegador", self.open_external)
        bar.addAction(style.standardIcon(QtWidgets.QStyle.SP_DialogSaveButton), "Salvar PDF…", self.save_pdf)
        self.act_back.setEnabled(False)
        self.act_fwd.setEnabled(False)
        self.browser.backwardAvailable.connect(self.act_back.setEnabled)
        self.browser.forwardAvailable.connect(self.act_fwd.setEnabled)
        QtGui.QShortcut(QtGui.QKeySequence.Find, self, activated=self.search.setFocus)
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, activated=self.close)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(self.browser)

        if MANUAL.is_file():
            self.browser.setSource(QtCore.QUrl.fromLocalFile(str(MANUAL)))
        else:
            self.browser.setHtml(f"<h2>Manual não encontrado</h2><p>Esperado em {MANUAL}.</p>")

    def show_section(self, anchor: str | None = None):
        self.show()
        self.raise_()
        self.activateWindow()
        if anchor:
            # depois que o documento estiver diagramado na janela visível
            QtCore.QTimer.singleShot(0, lambda: self.browser.scrollToAnchor(anchor))

    def find_next(self):
        text = self.search.text()
        if not text:
            return
        if not self.browser.find(text):
            # recomeça do início do documento
            cursor = self.browser.textCursor()
            cursor.movePosition(QtGui.QTextCursor.Start)
            self.browser.setTextCursor(cursor)
            if not self.browser.find(text):
                QtWidgets.QToolTip.showText(self.search.mapToGlobal(QtCore.QPoint(0, self.search.height())),
                                            "Não encontrado.", self.search)

    def save_pdf(self, path: str | None = None):
        if not path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Salvar manual em PDF",
                                                            str(Path.home() / "Manual_TermoLab2D.pdf"), "PDF (*.pdf)")
        if not path:
            return
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageMargins(QtCore.QMarginsF(15, 15, 15, 15), QtGui.QPageLayout.Millimeter)
        # Versão para impressão: imagens largas reduzidas à largura útil da página.
        # o documento é diagramado em pontos (72 por polegada); a impressora, em pixels de tela (96)
        page_w = int(printer.pageRect(QPrinter.Point).width())
        html = MANUAL.read_text(encoding="utf-8").replace('width="900"', f'width="{page_w}"')
        doc = QtGui.QTextDocument()
        for img in sorted((MANUAL.parent / "img").glob("*.png")):
            doc.addResource(QtGui.QTextDocument.ImageResource, QtCore.QUrl(f"img/{img.name}"), QtGui.QImage(str(img)))
        doc.setHtml(html)
        doc.print_(printer)

    def open_external(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(MANUAL)))
