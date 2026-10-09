# -*- coding: utf-8 -*-
"""
council/services/word_export.py
--------------------------------
Generate official, high-fidelity Arabic Word (.docx) documents for University Council session minutes.
Follows the exact standards, fonts, preamble, attendance tables, categorized agenda,
embedded dynamic tables with auto-calculated totals, and dual official signatures of Sana'a University.
"""

import io
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn, nsdecls
from docx.oxml import OxmlElement, parse_xml

from council.models import TOPIC_CATEGORIES


# ── XML / RTL Helpers ─────────────────────────────────────────────────────────

def _set_rtl_paragraph(paragraph, align='right'):
    """Force a paragraph to RTL layout and alignment."""
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement('w:bidi')
    bidi.set(qn('w:val'), '1')
    pPr.append(bidi)
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), align)
    pPr.append(jc)


def _set_document_rtl(doc):
    """Set default document direction to RTL and default font to Times New Roman / Traditional Arabic."""
    settings_element = doc.settings.element
    bidi_default = OxmlElement('w:bidi')
    settings_element.append(bidi_default)

    normal = doc.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(12)
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Times New Roman')
    rFonts.set(qn('w:ascii'), 'Times New Roman')
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


def _mark_run_cs(run):
    """Tag a run as complex-script for proper Arabic rendering."""
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Times New Roman')
    rPr.insert(0, rFonts)


def _setup_page(doc):
    """Configure A4 page size with standard university margins."""
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)


# ── Builders ──────────────────────────────────────────────────────────────────

def _build_header_and_title(doc, session):
    """Official Sana'a University header block and minutes title."""
    p_header = doc.add_paragraph()
    _set_rtl_paragraph(p_header, align='center')
    p_header.paragraph_format.space_after = Pt(2)
    r_hdr = p_header.add_run(
        "الجمهورية اليمنية\n"
        "وزارة التعليم العالي والبحث العلمي والتعليم الفني\n"
        "جامعة صنعاء - الأمانة العامة\n"
        "الإدارة العامة لشؤون مجلس الجامعة\n"
    )
    r_hdr.bold = True
    r_hdr.font.size = Pt(12)
    r_hdr.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    _mark_run_cs(r_hdr)

    # Title Banner
    cum_str = f" {session.session_cumulative_number}" if session.session_cumulative_number else ""
    p_title = doc.add_paragraph()
    _set_rtl_paragraph(p_title, align='center')
    p_title.paragraph_format.space_before = Pt(6)
    p_title.paragraph_format.space_after = Pt(14)
    r_title = p_title.add_run(f"محضر الاجتماع الثاني {cum_str} لمجلس الجامعة للعام الجامعي {session.academic_year or '1448هـ'}")
    r_title.bold = True
    r_title.font.size = Pt(15)
    r_title.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    _mark_run_cs(r_title)


def _build_preamble_and_attendance(doc, session):
    """Meeting opening narrative, 3 attendance tables, and honors ceremony."""
    # Opening narrative paragraph
    p_preamble = doc.add_paragraph()
    _set_rtl_paragraph(p_preamble, align='both')
    p_preamble.paragraph_format.line_spacing = 1.2
    p_preamble.paragraph_format.space_after = Pt(6)
    
    hijri = session.hijri_date or '15/2/1448هـ'
    greg = session.date.strftime('%d/%m/%Yم') if session.date else '29/7/2026م'
    cum_txt = f" ({session.session_cumulative_number})" if session.session_cumulative_number else ""
    
    text_preamble = (
        f"عقـد مجلس الجامعة اجتماعه الثاني{cum_txt} للعام الجامعي {session.academic_year or '1448هـ - 2026/2027م'} "
        f"يوم الثلاثاء بتاريخ {hijri} الموافق {greg} بمبنى {session.location or 'رئاسة الجامعة'} في تمام الساعة 12:00 ظهراً "
        f"برئاسة {session.chair_name or 'الأستاذ الدكتور/ محمد احمد البخيتي - رئيس الجامعة ((رئيس المجلس))'} "
        f"وقد حضر الاجتماع الأخوة التالية أسماؤهم: -"
    )
    r_pre = p_preamble.add_run(text_preamble)
    r_pre.font.size = Pt(12)
    _mark_run_cs(r_pre)

    # Attendance Queries
    attendances = session.attendances.select_related('member').order_by('member__order', 'member__id')
    att_present = attendances.filter(status='present')
    att_excused = attendances.filter(status='excused')
    att_unexcused = attendances.filter(status='unexcused')

    # Table 1: Present (الحاضرون)
    if att_present.exists():
        tbl_p = doc.add_table(rows=att_present.count(), cols=2)
        _set_table_rtl(tbl_p)
        tbl_p.alignment = WD_TABLE_ALIGNMENT.CENTER
        for idx, att in enumerate(att_present):
            row = tbl_p.rows[idx]
            c0, c1 = row.cells[0], row.cells[1]
            _set_cell_borders(c0)
            _set_cell_borders(c1)
            _shade_cell(c0, "F8FAFC" if idx % 2 == 0 else "FFFFFF")
            _shade_cell(c1, "F8FAFC" if idx % 2 == 0 else "FFFFFF")
            
            p0 = c0.paragraphs[0]
            _set_rtl_paragraph(p0, align='right')
            r0 = p0.add_run(att.member.full_name)
            r0.font.size = Pt(10.5)
            r0.bold = True
            _mark_run_cs(r0)
            
            p1 = c1.paragraphs[0]
            _set_rtl_paragraph(p1, align='right')
            r1 = p1.add_run(att.member_title_snapshot or att.member.get_title_display())
            r1.font.size = Pt(10.5)
            _mark_run_cs(r1)

    # Section 2: Excused (وتغيب عن الاجتماع بعذر)
    p_exc = doc.add_paragraph()
    _set_rtl_paragraph(p_exc, align='right')
    p_exc.paragraph_format.space_before = Pt(8)
    p_exc.paragraph_format.space_after = Pt(4)
    r_exc = p_exc.add_run("وتغيب عن الاجتماع بعذر: -")
    r_exc.bold = True
    r_exc.font.size = Pt(11)
    _mark_run_cs(r_exc)

    if att_excused.exists():
        tbl_e = doc.add_table(rows=att_excused.count(), cols=2)
        _set_table_rtl(tbl_e)
        tbl_e.alignment = WD_TABLE_ALIGNMENT.CENTER
        for idx, att in enumerate(att_excused):
            row = tbl_e.rows[idx]
            c0, c1 = row.cells[0], row.cells[1]
            _set_cell_borders(c0)
            _set_cell_borders(c1)
            p0 = c0.paragraphs[0]
            _set_rtl_paragraph(p0, align='right')
            r0 = p0.add_run(att.member.full_name)
            r0.font.size = Pt(10.5)
            _mark_run_cs(r0)
            p1 = c1.paragraphs[0]
            _set_rtl_paragraph(p1, align='right')
            r1 = p1.add_run(att.member_title_snapshot or att.member.get_title_display())
            r1.font.size = Pt(10.5)
            _mark_run_cs(r1)

    # Section 3: Unexcused (وتغيب عن الاجتماع بغير عذر)
    p_unexc = doc.add_paragraph()
    _set_rtl_paragraph(p_unexc, align='right')
    p_unexc.paragraph_format.space_before = Pt(6)
    p_unexc.paragraph_format.space_after = Pt(4)
    r_unexc = p_unexc.add_run("وتغيب عن الاجتماع بغير عذر: -")
    r_unexc.bold = True
    r_unexc.font.size = Pt(11)
    _mark_run_cs(r_unexc)

    if att_unexcused.exists():
        tbl_u = doc.add_table(rows=att_unexcused.count(), cols=2)
        _set_table_rtl(tbl_u)
        tbl_u.alignment = WD_TABLE_ALIGNMENT.CENTER
        for idx, att in enumerate(att_unexcused):
            row = tbl_u.rows[idx]
            c0, c1 = row.cells[0], row.cells[1]
            _set_cell_borders(c0)
            _set_cell_borders(c1)
            p0 = c0.paragraphs[0]
            _set_rtl_paragraph(p0, align='right')
            r0 = p0.add_run(att.member.full_name)
            r0.font.size = Pt(10.5)
            _mark_run_cs(r0)
            p1 = c1.paragraphs[0]
            _set_rtl_paragraph(p1, align='right')
            r1 = p1.add_run(att.member_title_snapshot or att.member.get_title_display())
            r1.font.size = Pt(10.5)
            _mark_run_cs(r1)

    # Secretary, Assistant and Opening Honors paragraph
    p_sec = doc.add_paragraph()
    _set_rtl_paragraph(p_sec, align='both')
    p_sec.paragraph_format.space_before = Pt(8)
    p_sec.paragraph_format.space_after = Pt(10)
    p_sec.paragraph_format.line_spacing = 1.2
    
    sec_txt = (
        f"وتولى أمانة سر الاجتماع {session.secretary_name or 'الأستاذ/ إسكندر عبده محمد المقالح أمين عام الجامعة (مقرر المجلس)'} "
        f"وساعده في هذا الاجتماع {session.assistant_name or 'الأستاذ/ عبدالله عثمان محمد مدير عام شؤون مجلس الجامعة'}. "
    )
    if session.opening_honors:
        sec_txt += f"\n{session.opening_honors} "
    sec_txt += "\nثم ناقش المجلس الموضوعات المدرجة في جدول أعماله واتخذ إزاءها القرارات المناسبة وعلى النحو الآتي: -"
    
    r_sec = p_sec.add_run(sec_txt)
    r_sec.font.size = Pt(12)
    _mark_run_cs(r_sec)


def _build_topics_by_categories(doc, session):
    """Build topics organized by the official 7 categories."""
    topics = session.topics.select_related('decision').prefetch_related('tables').order_by('category', 'sub_order', 'order_number')
    
    for cat_slug, cat_title in TOPIC_CATEGORIES:
        cat_topics = [t for t in topics if t.category == cat_slug]
        if not cat_topics:
            continue
        
        # Category Banner
        p_cat = doc.add_paragraph()
        _set_rtl_paragraph(p_cat, align='center')
        p_cat.paragraph_format.space_before = Pt(14)
        p_cat.paragraph_format.space_after = Pt(8)
        r_cat = p_cat.add_run(f"-{cat_title}-")
        r_cat.bold = True
        r_cat.font.size = Pt(13.5)
        r_cat.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
        _mark_run_cs(r_cat)

        ARABIC_ORDER_WORDS = {
            1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
            6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع", 10: "العاشر",
            11: "الحادي عشر", 12: "الثاني عشر", 13: "الثالث عشر", 14: "الرابع عشر",
            15: "الخامس عشر", 16: "السادس عشر", 17: "السابع عشر", 18: "الثامن عشر",
            19: "التاسع عشر", 20: "العشرون", 21: "الحادي والعشرون", 22: "الثاني والعشرون",
            23: "الثالث والعشرون", 24: "الرابع والعشرون", 25: "الخامس والعشرون"
        }

        for t in cat_topics:
            order_word = ARABIC_ORDER_WORDS.get(t.sub_order, str(t.sub_order))
            
            # Topic Sub-header
            p_top_order = doc.add_paragraph()
            _set_rtl_paragraph(p_top_order, align='right')
            p_top_order.paragraph_format.space_before = Pt(8)
            p_top_order.paragraph_format.space_after = Pt(2)
            r_ord = p_top_order.add_run(f"الموضوع {order_word}: -")
            r_ord.bold = True
            r_ord.font.size = Pt(12.5)
            r_ord.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
            _mark_run_cs(r_ord)

            # Topic Title / Background
            p_body = doc.add_paragraph()
            _set_rtl_paragraph(p_body, align='both')
            p_body.paragraph_format.line_spacing = 1.15
            p_body.paragraph_format.space_after = Pt(4)
            r_bg = p_body.add_run(t.title if t.title else t.background)
            r_bg.font.size = Pt(11.5)
            _mark_run_cs(r_bg)

            # Embedded Topic Tables
            for tbl in t.tables.all():
                if tbl.title:
                    p_tbl_title = doc.add_paragraph()
                    _set_rtl_paragraph(p_tbl_title, align='right')
                    p_tbl_title.paragraph_format.space_before = Pt(4)
                    p_tbl_title.paragraph_format.space_after = Pt(2)
                    r_tt = p_tbl_title.add_run(f"• {tbl.title}:")
                    r_tt.bold = True
                    r_tt.font.size = Pt(10.5)
                    r_tt.font.color.rgb = RGBColor(0x2E, 0x74, 0xB5)
                    _mark_run_cs(r_tt)

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
                        cr = cp.add_run(str(h_text))
                        cr.bold = True
                        cr.font.size = Pt(9)
                        cr.font.color.rgb = RGBColor(255, 255, 255)
                        _mark_run_cs(cr)

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
                            cr = cp.add_run(val_str)
                            cr.font.size = Pt(8.5)
                            _mark_run_cs(cr)

                    # Auto-sum total row if present
                    if total_row:
                        tot_cells = doc_tbl.rows[-1].cells
                        for c_idx, t_val in enumerate(total_row):
                            cell = tot_cells[c_idx]
                            _shade_cell(cell, "D9E1F2")
                            _set_cell_borders(cell, border_size=6, color="1B365D")
                            cp = cell.paragraphs[0]
                            _set_rtl_paragraph(cp, align='center')
                            cr = cp.add_run(str(t_val))
                            cr.bold = True
                            cr.font.size = Pt(9)
                            cr.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
                            _mark_run_cs(cr)

            # Decision text
            p_dec = doc.add_paragraph()
            _set_rtl_paragraph(p_dec, align='both')
            p_dec.paragraph_format.space_before = Pt(4)
            p_dec.paragraph_format.space_after = Pt(8)
            
            r_dec_label = p_dec.add_run("القــــــــرار: ")
            r_dec_label.bold = True
            r_dec_label.font.size = Pt(11.5)
            r_dec_label.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
            _mark_run_cs(r_dec_label)

            dec_text = t.decision.decision_text if hasattr(t, 'decision') and t.decision else "الموافقة وعلى مسؤولية الشؤون المختصة صحة البيانات وسلامة الإجراءات."
            r_dec_val = p_dec.add_run(dec_text)
            r_dec_val.font.size = Pt(11.5)
            _mark_run_cs(r_dec_val)


def _build_official_signatures(doc, session):
    """Dual signature table at the end of the minutes."""
    doc.add_paragraph().paragraph_format.space_after = Pt(14)
    
    t_sig = doc.add_table(rows=2, cols=2)
    _set_table_rtl(t_sig)
    t_sig.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Row 0: Titles
    c_right_title = t_sig.cell(0, 0)
    c_left_title = t_sig.cell(0, 1)
    
    pr = c_right_title.paragraphs[0]
    _set_rtl_paragraph(pr, align='center')
    rr = pr.add_run("أمين عام الجامعة - مقرر المجلس")
    rr.bold = True
    rr.font.size = Pt(12)
    rr.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    _mark_run_cs(rr)

    pl = c_left_title.paragraphs[0]
    _set_rtl_paragraph(pl, align='center')
    rl = pl.add_run("رئيس الجامعة - رئيس المجلس")
    rl.bold = True
    rl.font.size = Pt(12)
    rl.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    _mark_run_cs(rl)

    # Row 1: Names
    c_right_name = t_sig.cell(1, 0)
    c_left_name = t_sig.cell(1, 1)

    pr2 = c_right_name.paragraphs[0]
    _set_rtl_paragraph(pr2, align='center')
    pr2.paragraph_format.space_before = Pt(30) # Space for physical signature
    rr2 = pr2.add_run("أ/ إسكندر عبده محمد المقالح")
    rr2.bold = True
    rr2.font.size = Pt(12)
    _mark_run_cs(rr2)

    pl2 = c_left_name.paragraphs[0]
    _set_rtl_paragraph(pl2, align='center')
    pl2.paragraph_format.space_before = Pt(30) # Space for physical signature
    rl2 = pl2.add_run("أ.د/ محمد أحمد البخيتي")
    rl2.bold = True
    rl2.font.size = Pt(12)
    _mark_run_cs(rl2)


def generate_session_minutes(session) -> io.BytesIO:
    """
    Generate an official Word document for CouncilSession and return io.BytesIO buffer.
    """
    doc = Document()
    _set_document_rtl(doc)
    _setup_page(doc)

    # Document blocks
    _build_header_and_title(doc, session)
    _build_preamble_and_attendance(doc, session)
    _build_topics_by_categories(doc, session)
    _build_official_signatures(doc, session)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
