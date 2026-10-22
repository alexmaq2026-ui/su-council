# -*- coding: utf-8 -*-
"""
council/services/pdf_export.py
--------------------------------
Automated, official PDF generation service for University Council:
1. Session Outcomes & Decisions PDF (مخرجات وقرارات الجلسة - المواضيع والقرارات فقط بدون ديباجة الحضور)
2. Single Topic Official Decision PDF (قرار موضوع فردي معتمد)
3. Main Category Decisions Bulletin PDF (قرارات محور / باب رئيسي)

Strict Arabic RTL layout:
- Fully compliant Right-to-Left document direction (Strict RTL & BiDi).
- Native Arabic fonts (Traditional Arabic / Arial).
- Clean, non-reversed punctuation (الموضوع الأول: ... القرار: ...).
- Dual engine: High-fidelity DOCX-to-PDF via MS Word COM with pure Python ReportLab fallback.
"""

import os
import io
import tempfile
import logging
from datetime import datetime
from django.core.files.base import ContentFile
from django.conf import settings

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn, nsdecls
from docx.oxml import OxmlElement, parse_xml

from council.models import CouncilSession, Topic, TOPIC_CATEGORIES

logger = logging.getLogger(__name__)


# ── XML & RTL Helpers for DOCX ────────────────────────────────────────────────

def _set_rtl_paragraph(paragraph, align='right'):
    """Sets paragraph alignment cleanly and reliably on Arabic RTL pages."""
    if align == 'right':
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif align == 'center':
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == 'left':
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    elif align in ('justify', 'both'):
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _set_document_rtl(doc):
    """Set default document direction to RTL and default font to Arial."""
    settings_element = doc.settings.element
    bidi_default = OxmlElement('w:bidi')
    settings_element.append(bidi_default)

    normal = doc.styles['Normal']
    normal.font.name = 'Arial'
    normal.font.size = Pt(11.5)
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Arial')
    rFonts.set(qn('w:ascii'), 'Arial')
    rFonts.set(qn('w:hAnsi'), 'Arial')
    normal._element.get_or_add_rPr().append(rFonts)


def _set_table_rtl(table):
    """Configure table-level RTL visual direction."""
    tbl = table._tbl
    tblPr = tbl.find(qn('w:tblPr'))
    if tblPr is None:
        tblPr = OxmlElement('w:tblPr')
        tbl.insert(0, tblPr)
    bidiVisual = OxmlElement('w:bidiVisual')
    tblPr.append(bidiVisual)


def _shade_cell(cell, fill_hex: str):
    """Apply background shade to a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def _set_cell_borders(cell, border_size: int = 4, color: str = 'CCCCCC'):
    """Add clean borders around a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="{border_size}" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="single" w:sz="{border_size}" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="single" w:sz="{border_size}" w:space="0" w:color="{color}"/>'
        f'<w:right w:val="single" w:sz="{border_size}" w:space="0" w:color="{color}"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)


def _set_decision_box_borders(cell, border_color: str = '1B365D', fill_hex: str = 'F4F6F9'):
    """Format cell as an official indented decision card with a prominent right accent border."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        f'<w:left w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        f'<w:right w:val="single" w:sz="24" w:space="0" w:color="{border_color}"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)


def _add_run_rtl(paragraph, text: str, font_size: float = 11.5, bold: bool = False, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial'):
    """
    Adds a text run strictly configured for Arabic Right-to-Left complex script rendering.
    Ensures colons and punctuation never flip to the left edge.
    """
    run = paragraph.add_run(text)
    run.font.name = font_name
    run.font.size = Pt(font_size)
    run.bold = bold
    run.font.color.rgb = RGBColor(*color_rgb)

    rPr = run._r.get_or_add_rPr()
    # Explicit RTL run flag
    rtl = OxmlElement('w:rtl')
    rtl.set(qn('w:val'), '1')
    rPr.append(rtl)

    # Complex script fonts
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), font_name)
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)
    rPr.append(rFonts)

    return run


# ── DOCX to PDF Conversion via Word COM ───────────────────────────────────────

def convert_docx_bytes_to_pdf_bytes(docx_bytes: bytes) -> bytes:
    """
    Converts docx bytes to PDF bytes using Word COM automation on Windows.
    Returns PDF bytes if successful, or raises an Exception.
    """
    temp_dir = tempfile.gettempdir()
    unique_suffix = f"{os.getpid()}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    docx_path = os.path.join(temp_dir, f"council_{unique_suffix}.docx")
    pdf_path = os.path.join(temp_dir, f"council_{unique_suffix}.pdf")

    with open(docx_path, 'wb') as f:
        f.write(docx_bytes)

    word = None
    doc = None
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch('Word.Application')
        word.Visible = False
        word.DisplayAlerts = False
        doc = word.Documents.Open(os.path.abspath(docx_path))
        # 17 = wdFormatPDF
        doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
        doc.Close(False)
        doc = None
        word.Quit()
        word = None

        with open(pdf_path, 'rb') as pf:
            pdf_bytes = pf.read()
        return pdf_bytes
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        if os.path.exists(docx_path):
            try:
                os.remove(docx_path)
            except Exception:
                pass
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass


# ── Session Outcomes & Decisions DOCX Generator (No Attendance / No Preamble) ─

ARABIC_ORDER_WORDS = {
    1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
    6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع", 10: "العاشر",
    11: "الحادي عشر", 12: "الثاني عشر", 13: "الثالث عشر", 14: "الرابع عشر",
    15: "الخامس عشر", 16: "السادس عشر", 17: "السابع عشر", 18: "الثامن عشر",
    19: "التاسع عشر", 20: "العشرون", 21: "الحادي والعشرون", 22: "الثاني والعشرون",
    23: "الثالث والعشرون", 24: "الرابع والعشرون", 25: "الخامس والعشرون",
    26: "السادس والعشرون", 27: "السابع والعشرون", 28: "الثامن والعشرون",
    29: "التاسع والعشرون", 30: "الثلاثون", 31: "الحادي والثلاثون",
    32: "الثاني والثلاثون", 33: "الثالث والثلاثون", 34: "الرابع والثلاثون",
    35: "الخامس والثلاثون"
}


def build_session_decisions_docx(session: CouncilSession) -> io.BytesIO:
    """
    Builds a focused, official outcomes & decisions document for a session.
    EXCLUDES: Preamble, attendance roll calls, and raw top header metadata blocks.
    INCLUDES: Official title banner, structured topics organized by category ribbon, tables,
    and distinct framed decision boxes in their proper natural place.
    """
    doc = Document()
    _set_document_rtl(doc)

    # Page setup
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.0)
    sec.right_margin = Cm(2.0)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)

    # Document Title Banner (بدون الكتلة النصية العلوية المحذوفة)
    p_title = doc.add_paragraph()
    _set_rtl_paragraph(p_title, align='center')
    p_title.paragraph_format.space_before = Pt(10)
    p_title.paragraph_format.space_after = Pt(4)
    _add_run_rtl(p_title, f"مخرجات وقرارات الجلسة رقم ({session.session_number}) لمجلس جامعة صنعاء", font_size=16, bold=True, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial')

    # Subtitle: Session Metadata
    p_sub = doc.add_paragraph()
    _set_rtl_paragraph(p_sub, align='center')
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(16)
    date_str = session.date.strftime('%Y-%m-%d') if session.date else ''
    hijri_str = f" ({session.hijri_date})" if session.hijri_date else ""
    acad_year = session.academic_year or "1448هـ"
    _add_run_rtl(p_sub, f"المنعقدة بتاريخ: {date_str}م{hijri_str}  •  العام الجامعي: {acad_year}", font_size=10.5, bold=False, color_rgb=(0x66, 0x66, 0x66), font_name='Arial')

    # Categorized Topics & Decisions
    topics = session.topics.select_related('decision').prefetch_related('tables').order_by('category', 'sub_order', 'order_number')

    for cat_slug, cat_title in TOPIC_CATEGORIES:
        cat_topics = [t for t in topics if t.category == cat_slug]
        if not cat_topics:
            continue

        # Category Banner Ribbon (شريط المحور الرسمي بلون كحلي موحد وخط أبيض ناصع)
        tbl_cat = doc.add_table(rows=1, cols=1)
        _set_table_rtl(tbl_cat)
        tbl_cat.alignment = WD_TABLE_ALIGNMENT.CENTER
        c_cat = tbl_cat.cell(0, 0)
        _shade_cell(c_cat, "1B365D")
        _set_cell_borders(c_cat, border_size=4, color="1B365D")
        p_cp = c_cat.paragraphs[0]
        _set_rtl_paragraph(p_cp, align='center')
        p_cp.paragraph_format.space_before = Pt(4)
        p_cp.paragraph_format.space_after = Pt(4)
        _add_run_rtl(p_cp, f"محور: {cat_title}", font_size=12.5, bold=True, color_rgb=(255, 255, 255), font_name='Arial')

        p_after_cat = doc.add_paragraph()
        p_after_cat.paragraph_format.space_before = Pt(0)
        p_after_cat.paragraph_format.space_after = Pt(4)

        for topic_idx, t in enumerate(cat_topics, 1):
            order_word = ARABIC_ORDER_WORDS.get(topic_idx, str(topic_idx))

            # Topic Title & Order
            p_top = doc.add_paragraph()
            _set_rtl_paragraph(p_top, align='right')
            p_top.paragraph_format.space_before = Pt(8)
            p_top.paragraph_format.space_after = Pt(3)

            _add_run_rtl(p_top, f"الموضوع {order_word}: ", font_size=11.5, bold=True, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial')
            title_text = t.title if t.title else (t.background or "موضوع الجلسة")
            _add_run_rtl(p_top, title_text, font_size=11, bold=False, color_rgb=(0x22, 0x22, 0x22), font_name='Arial')

            # Embedded Topic Tables (if any)
            for tbl in t.tables.all():
                if tbl.title:
                    p_tt = doc.add_paragraph()
                    _set_rtl_paragraph(p_tt, align='right')
                    p_tt.paragraph_format.space_before = Pt(4)
                    p_tt.paragraph_format.space_after = Pt(2)
                    _add_run_rtl(p_tt, f"• {tbl.title}:", font_size=10, bold=True, color_rgb=(0x2E, 0x74, 0xB5), font_name='Arial')

                if tbl.headers and tbl.rows_data:
                    num_rows = len(tbl.rows_data) + 1
                    total_row = tbl.get_formatted_total_row()
                    if total_row:
                        num_rows += 1

                    doc_tbl = doc.add_table(rows=num_rows, cols=len(tbl.headers))
                    _set_table_rtl(doc_tbl)
                    doc_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

                    # Headers
                    for c_idx, h_text in enumerate(tbl.headers):
                        cell = doc_tbl.rows[0].cells[c_idx]
                        _shade_cell(cell, "1B365D")
                        _set_cell_borders(cell, border_size=4, color="1B365D")
                        cp = cell.paragraphs[0]
                        _set_rtl_paragraph(cp, align='center')
                        _add_run_rtl(cp, str(h_text), font_size=9, bold=True, color_rgb=(255, 255, 255), font_name='Arial')

                    # Data rows
                    for r_idx, row_vals in enumerate(tbl.rows_data):
                        row_cells = doc_tbl.rows[r_idx + 1].cells
                        shade_col = "F8FAFC" if r_idx % 2 == 0 else "FFFFFF"
                        for c_idx in range(len(tbl.headers)):
                            val_str = str(row_vals[c_idx]) if c_idx < len(row_vals) else ""
                            cell = row_cells[c_idx]
                            _shade_cell(cell, shade_col)
                            _set_cell_borders(cell, border_size=4, color="CCCCCC")
                            cp = cell.paragraphs[0]
                            align = 'center' if c_idx in (0, 1) or len(val_str) < 8 else 'right'
                            _set_rtl_paragraph(cp, align=align)
                            _add_run_rtl(cp, val_str, font_size=8.5, bold=False, color_rgb=(0x33, 0x33, 0x33), font_name='Arial')

                    # Total row
                    if total_row:
                        tot_cells = doc_tbl.rows[-1].cells
                        for c_idx, t_val in enumerate(total_row):
                            cell = tot_cells[c_idx]
                            _shade_cell(cell, "D9E1F2")
                            _set_cell_borders(cell, border_size=6, color="1B365D")
                            cp = cell.paragraphs[0]
                            _set_rtl_paragraph(cp, align='center')
                            _add_run_rtl(cp, str(t_val), font_size=9, bold=True, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial')

            # Official Decision in its NATURAL, PROPER PLACE (صندوق القرار الرسمي المعتمد والمميز بمحاذاة يمين صارمة)
            tbl_dec = doc.add_table(rows=1, cols=1)
            tbl_dec.alignment = WD_TABLE_ALIGNMENT.CENTER
            c_dec = tbl_dec.cell(0, 0)
            _set_decision_box_borders(c_dec, border_color="1B365D", fill_hex="F4F6F9")

            p_dec = c_dec.paragraphs[0]
            p_dec.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_dec.paragraph_format.space_before = Pt(4)
            p_dec.paragraph_format.space_after = Pt(4)
            p_dec.paragraph_format.line_spacing = 1.15

            _add_run_rtl(p_dec, "الـقــــــــرار: ", font_size=10.5, bold=True, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial')
            dec_text = t.decision.decision_text if getattr(t, 'decision', None) else "الموافقة والاعتماد رسمياً."
            _add_run_rtl(p_dec, dec_text, font_size=10.5, bold=False, color_rgb=(0x15, 0x57, 0x24), font_name='Arial')

            # Spacing between topics
            p_gap = doc.add_paragraph()
            p_gap.paragraph_format.space_before = Pt(0)
            p_gap.paragraph_format.space_after = Pt(6)

    # 3. Dual Official Signatures Footer (توقيع مقرر ورئيس المجلس)
    p_space = doc.add_paragraph()
    p_space.paragraph_format.space_before = Pt(18)

    t_sig = doc.add_table(rows=2, cols=2)
    _set_table_rtl(t_sig)
    t_sig.alignment = WD_TABLE_ALIGNMENT.CENTER

    c_sec = t_sig.cell(0, 0)
    c_pres = t_sig.cell(0, 1)

    pr_sec = c_sec.paragraphs[0]
    _set_rtl_paragraph(pr_sec, align='center')
    _add_run_rtl(pr_sec, "أمين عام الجامعة - مقرر المجلس", font_size=11, bold=True, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial')

    pr_pres = c_pres.paragraphs[0]
    _set_rtl_paragraph(pr_pres, align='center')
    _add_run_rtl(pr_pres, "رئيس مجلس الجامعة", font_size=11, bold=True, color_rgb=(0x1B, 0x36, 0x5D), font_name='Arial')

    c_sec_name = t_sig.cell(1, 0)
    c_pres_name = t_sig.cell(1, 1)

    pr_sn = c_sec_name.paragraphs[0]
    _set_rtl_paragraph(pr_sn, align='center')
    sec_name = session.secretary_name or "أ. إسكندر عبده محمد المقالح"
    _add_run_rtl(pr_sn, f"\n\n{sec_name}", font_size=11, bold=True, color_rgb=(0x33, 0x33, 0x33), font_name='Arial')

    pr_pn = c_pres_name.paragraphs[0]
    _set_rtl_paragraph(pr_pn, align='center')
    chair_name = session.chair_name or "أ.د/ محمد أحمد البخيتي"
    _add_run_rtl(pr_pn, f"\n\n{chair_name}", font_size=11, bold=True, color_rgb=(0x33, 0x33, 0x33), font_name='Arial')

    # Save to buffer
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
    return buf


# ── ReportLab Fallback Helpers ────────────────────────────────────────────────

def _arabic(text: str) -> str:
    """Reshape and reorder Arabic text for ReportLab rendering."""
    if not text:
        return ""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except Exception:
        return str(text)


def _build_reportlab_single_decision_pdf(topic: Topic, decision_number: str = "", decision_date: str = "") -> bytes:
    """
    Pure Python ReportLab generator for a Single Topic Official Decision letter.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = 'C:/Windows/Fonts/arial.ttf'
    if not os.path.exists(font_path):
        font_path = 'C:/Windows/Fonts/times.ttf'

    try:
        pdfmetrics.registerFont(TTFont('ArabicCouncilFont', font_path))
        used_font = 'ArabicCouncilFont'
    except Exception:
        used_font = 'Helvetica'

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Outer decorative border
    c.setStrokeColorRGB(0.11, 0.21, 0.36)  # Navy
    c.setLineWidth(2)
    c.rect(30, 30, width - 60, height - 60)
    c.setLineWidth(0.7)
    c.rect(34, 34, width - 68, height - 68)

    # Header block
    c.setFont(used_font, 12)
    c.setFillColorRGB(0.11, 0.21, 0.36)
    c.drawRightString(width - 55, height - 65, _arabic("الجمهورية اليمنية"))
    c.drawRightString(width - 55, height - 82, _arabic("وزارة التعليم العالي والبحث العلمي"))
    c.drawRightString(width - 55, height - 99, _arabic("جامعة صنعاء - الأمانة العامة"))
    c.drawRightString(width - 55, height - 116, _arabic("مجلس الجامعة"))

    # Metadata left side
    c.setFont(used_font, 10)
    c.drawString(55, height - 65, _arabic(f"الرقم: {decision_number or 'رسمي'}"))
    c.drawString(55, height - 82, _arabic(f"التاريخ: {decision_date or datetime.now().strftime('%Y-%m-%d')}م"))
    session = topic.session
    if session:
        c.drawString(55, height - 99, _arabic(f"الجلسة رقم: ({session.session_number})"))

    # Divider line
    c.setStrokeColorRGB(0.78, 0.65, 0.35)  # Gold
    c.setLineWidth(1.5)
    c.line(50, height - 130, width - 50, height - 130)

    # Title
    c.setFont(used_font, 16)
    c.setFillColorRGB(0.11, 0.21, 0.36)
    c.drawCentredString(width / 2.0, height - 165, _arabic("قـرار مجلـس الجامعـة"))

    c.setFont(used_font, 11)
    sub_title = f"بشأن: {topic.title[:70]}"
    c.drawCentredString(width / 2.0, height - 190, _arabic(sub_title))

    # Topic Subject Box
    y_pos = height - 230
    c.setFillColorRGB(0.96, 0.97, 0.98)
    c.rect(55, y_pos - 40, width - 110, 50, fill=True, stroke=False)
    c.setFillColorRGB(0.11, 0.21, 0.36)
    c.setFont(used_font, 11)
    c.drawRightString(width - 70, y_pos - 15, _arabic(f"الموضوع: {topic.title[:85]}"))
    if len(topic.title) > 85:
        c.drawRightString(width - 70, y_pos - 32, _arabic(topic.title[85:170]))
    y_pos -= 65

    # Decision Heading
    c.setFont(used_font, 13)
    c.setFillColorRGB(0.11, 0.21, 0.36)
    c.drawRightString(width - 60, y_pos, _arabic("« قـــــرر المجلــــس »"))
    y_pos -= 25

    # Decision Text Box
    decision_text = ""
    if hasattr(topic, 'decision') and topic.decision:
        decision_text = topic.decision.decision_text
    elif topic.decision_summary:
        decision_text = topic.decision_summary
    else:
        decision_text = f"الموافقة والاعتماد وفقاً للمذكرة المرفوعة والمقترحات المقدمة لمجلس الجامعة."

    c.setFillColorRGB(1.0, 1.0, 1.0)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(1)
    box_height = 160
    c.rect(55, y_pos - box_height, width - 110, box_height, fill=True, stroke=True)

    c.setFillColorRGB(0.08, 0.15, 0.25)
    c.setFont(used_font, 11)

    words = decision_text.split()
    line = []
    text_y = y_pos - 25
    for word in words:
        line.append(word)
        if len(' '.join(line)) > 75:
            c.drawRightString(width - 75, text_y, _arabic(' '.join(line)))
            text_y -= 20
            line = []
            if text_y < y_pos - box_height + 20:
                break
    if line and text_y >= y_pos - box_height + 15:
        c.drawRightString(width - 75, text_y, _arabic(' '.join(line)))

    # Signatures Footer
    sig_y = 100
    c.setFont(used_font, 11)
    c.setFillColorRGB(0.11, 0.21, 0.36)
    c.drawRightString(width - 80, sig_y + 35, _arabic("أمين عام مجلس الجامعة"))
    c.drawRightString(width - 80, sig_y + 15, _arabic("أ.د/ أمين المجلس"))

    c.drawString(80, sig_y + 35, _arabic("رئيس مجلس الجامعة"))
    c.drawString(80, sig_y + 15, _arabic("أ.د/ محمد أحمد البخيتي"))

    # Bottom stamp note
    c.setFont(used_font, 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width / 2.0, 45, _arabic("مستند رسمي معتمد وموثق رقمياً من نظام إدارة جلسات مجلس الجامعة — جامعة صنعاء"))

    c.save()
    buf.seek(0)
    return buf.getvalue()


# ── Public Export Services ────────────────────────────────────────────────────

def generate_session_minutes_pdf(session: CouncilSession) -> ContentFile:
    """
    Generates the official PDF document for session outcomes and decisions.
    EXCLUDES the meeting preamble, attendance roll-calls, and administrative intro.
    Strictly focuses on the topics and decisions in pristine Arabic RTL layout.
    """
    pdf_bytes = None

    # 1. Try DOCX -> Word COM conversion with strict RTL
    try:
        docx_buffer = build_session_decisions_docx(session)
        pdf_bytes = convert_docx_bytes_to_pdf_bytes(docx_buffer.getvalue())
        logger.info("Successfully generated Session %s decisions PDF via Word COM.", session.session_number)
    except Exception as exc:
        logger.warning("Word COM conversion failed for Session %s (%s). Generating ReportLab outcomes...", session.session_number, exc)

    # 2. Fallback if Word COM failed
    if not pdf_bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_path = 'C:/Windows/Fonts/arial.ttf'
        if not os.path.exists(font_path):
            font_path = 'C:/Windows/Fonts/times.ttf'
        try:
            pdfmetrics.registerFont(TTFont('ArabicOutcomesFont', font_path))
            f_name = 'ArabicOutcomesFont'
        except Exception:
            f_name = 'Helvetica'

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4

        c.setStrokeColorRGB(0.11, 0.21, 0.36)
        c.setLineWidth(1.5)
        c.rect(30, 30, w - 60, h - 60)

        c.setFont(f_name, 13)
        c.setFillColorRGB(0.11, 0.21, 0.36)
        c.drawCentredString(w / 2.0, h - 65, _arabic("الجمهورية اليمنية - جامعة صنعاء - مجلس الجامعة"))
        c.setFont(f_name, 15)
        c.drawCentredString(w / 2.0, h - 90, _arabic(f"مخرجات وقرارات الجلسة رقم ({session.session_number}) لمجلس الجامعة"))

        c.setFont(f_name, 10.5)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        date_str = session.date.strftime('%Y-%m-%d') if session.date else ''
        c.drawCentredString(w / 2.0, h - 110, _arabic(f"بتاريخ: {date_str}م | العام الجامعي: {session.academic_year or '1448هـ'}"))

        c.setStrokeColorRGB(0.78, 0.65, 0.35)
        c.setLineWidth(1)
        c.line(45, h - 122, w - 45, h - 122)

        # Topics list preview
        y = h - 150
        c.setFont(f_name, 11)
        c.setFillColorRGB(0.11, 0.21, 0.36)
        c.drawRightString(w - 55, y, _arabic("الموضوعات والقرارات المعتمدة:"))
        y -= 25

        c.setFont(f_name, 10)
        c.setFillColorRGB(0.15, 0.15, 0.15)
        for idx, t in enumerate(session.topics.all()[:20], 1):
            line_str = f"الموضوع {idx}: {t.title[:65]}"
            dec_str = f" — القرار: {t.decision.decision_text[:45]}" if hasattr(t, 'decision') and t.decision else " — القرار: الموافقة."
            c.drawRightString(w - 60, y, _arabic(line_str + dec_str))
            y -= 22
            if y < 90:
                break

        c.setFont(f_name, 9)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawCentredString(w / 2.0, 50, _arabic("وثيقة رسمية معتمدة ومصدرة من أمانة مجلس جامعة صنعاء"))
        c.save()
        buf.seek(0)
        pdf_bytes = buf.getvalue()

    filename = f"session_{session.session_number}_minutes.pdf"
    return ContentFile(pdf_bytes, name=filename)


def generate_single_topic_decision_pdf(topic: Topic, decision_number: str = "", decision_date: str = "") -> ContentFile:
    """
    Generates an official Single Topic Decision PDF.
    Returns a Django ContentFile.
    """
    if not decision_number and hasattr(topic, 'signed_decision') and topic.signed_decision:
        decision_number = topic.signed_decision.decision_number or ""
    if not decision_date and hasattr(topic, 'signed_decision') and topic.signed_decision and topic.signed_decision.decision_date:
        decision_date = topic.signed_decision.decision_date.strftime('%Y-%m-%d')
    if not decision_date:
        decision_date = datetime.now().strftime('%Y-%m-%d')

    pdf_bytes = _build_reportlab_single_decision_pdf(topic, decision_number, decision_date)
    filename = f"decision_topic_{topic.pk}.pdf"
    return ContentFile(pdf_bytes, name=filename)


def generate_category_topics_pdf(session: CouncilSession, category: str) -> ContentFile:
    """
    Generates a PDF compilation for all decisions under a specific category in a session.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = 'C:/Windows/Fonts/arial.ttf'
    if not os.path.exists(font_path):
        font_path = 'C:/Windows/Fonts/times.ttf'
    try:
        pdfmetrics.registerFont(TTFont('ArabicCatFont', font_path))
        f_name = 'ArabicCatFont'
    except Exception:
        f_name = 'Helvetica'

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    cat_dict = dict(TOPIC_CATEGORIES)
    category_label = cat_dict.get(category, category)

    c.setStrokeColorRGB(0.11, 0.21, 0.36)
    c.setLineWidth(1.5)
    c.rect(30, 30, w - 60, h - 60)

    c.setFont(f_name, 14)
    c.setFillColorRGB(0.11, 0.21, 0.36)
    c.drawCentredString(w / 2.0, h - 70, _arabic("الجمهورية اليمنية - جامعة صنعاء - مجلس الجامعة"))
    c.setFont(f_name, 16)
    c.drawCentredString(w / 2.0, h - 95, _arabic(f"قرارات محور: {category_label}"))
    c.setFont(f_name, 11)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    date_str = session.date.strftime('%Y-%m-%d') if session and session.date else ''
    c.drawCentredString(w / 2.0, h - 118, _arabic(f"الجلسة رقم ({session.session_number if session else '-'}) بتاريخ: {date_str}م"))

    c.setStrokeColorRGB(0.78, 0.65, 0.35)
    c.setLineWidth(1)
    c.line(45, h - 130, w - 45, h - 130)

    topics = session.topics.filter(category=category) if session else []
    y = h - 165
    for idx, t in enumerate(topics[:15], 1):
        c.setFont(f_name, 11)
        c.setFillColorRGB(0.11, 0.21, 0.36)
        c.drawRightString(w - 55, y, _arabic(f"الموضوع {idx}: {t.title[:65]}"))
        y -= 18

        dec_text = ""
        if hasattr(t, 'decision') and t.decision:
            dec_text = t.decision.decision_text[:90]
        else:
            dec_text = "الموافقة والاعتماد رسمياً."

        c.setFont(f_name, 10)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.drawRightString(w - 75, y, _arabic(f"القرار: {dec_text}"))
        y -= 26
        if y < 90:
            break

    c.setFont(f_name, 9)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(w / 2.0, 50, _arabic("مستند رسمي معتمد ومصدر من أمانة مجلس جامعة صنعاء"))

    c.save()
    buf.seek(0)
    filename = f"session_{session.session_number if session else 0}_category_{category}.pdf"
    return ContentFile(buf.getvalue(), name=filename)
