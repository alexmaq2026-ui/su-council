"""
Table Views - TopicTable Management (Create, Edit, Delete, Configure Auto-Sum)
University Council Management System
"""
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from council.models import Topic, TopicTable, TABLE_PRESET_CHOICES

PRESET_HEADERS_MAP = {
    'appointment': ['م', 'الاسم', 'تاريخ الميلاد', 'المؤهل', 'الكلية', 'الجامعة', 'البلد', 'تاريخ الحصول عليه', 'التقدير', 'التخصص', 'ملاحظات'],
    'confirmation': ['م', 'الاسم', 'المؤهل', 'الكلية / القسم', 'الرتبة المعين عليها', 'تاريخ التعيين', 'تاريخ انتهاء فترة التجربة', 'ملاحظات'],
    'settlement': ['م', 'الاسم', 'الكلية', 'المؤهل السابق', 'المؤهل الجديد', 'الوضع السابق', 'الوضع المقترح', 'تاريخ الاستحقاق'],
    'promotion': ['م', 'الاسم', 'الكلية', 'القسم', 'اللقب الحالي', 'اللقب المرقى إليه', 'تاريخ الترقية', 'ملاحظات'],
    'hourly_contract': ['م', 'الاسم', 'الدرجة العلمية', 'الكلية', 'القسم', 'المقرر الدراسي', 'عدد الساعات', 'ملاحظات'],
    'scopus_reward': ['م', 'اسم الباحث', 'الرتبة العلمية', 'الكلية', 'عنوان البحث', 'اسم المجلة', 'تصنيف المجلة Q', 'مبلغ الدعم ($)'],
    'phd_defense': ['م', 'اسم الطالب', 'الكلية', 'القسم / التخصص', 'عنوان الأطروحة', 'تاريخ المناقشة', 'النتيجة / التقدير'],
    'master_defense': ['م', 'اسم الطالب', 'الكلية', 'القسم / التخصص', 'عنوان الرسالة', 'تاريخ المناقشة', 'النتيجة / التقدير'],
    'diploma': ['م', 'اسم الطالب', 'الكلية / المركز', 'اسم الدبلوم', 'المعدل', 'التقدير', 'ملاحظات'],
    'graduates': ['م', 'القسم / الشعبة', 'النظام', 'الذكور', 'الإناث', 'الإجمالي', 'ملاحظات'],
    'court_correction': ['م', 'الاسم في الوثيقة الحالية', 'الاسم المعدل بموجب الحكم', 'الكلية', 'رقم الحكم القضائي وتاريخه', 'ملاحظات'],
    'grade_correction': ['م', 'اسم الطالب', 'الرقم الأكاديمي', 'الكلية', 'المقرر', 'الدرجة السابقة', 'الدرجة المعدلة', 'سبب التعديل'],
}

PRESET_SUM_COLS_MAP = {
    'scopus_reward': [7],
    'graduates': [5],
    'hourly_contract': [6],
}


@login_required(login_url='/login/')
def table_create_view(request, topic_pk):
    """Create a new dynamic table for a topic."""
    if not (request.user.can_add_table or request.user.is_super or getattr(request.user, 'can_prepare_agenda', False)):
        messages.error(request, 'ليس لديك صلاحية لإضافة جداول.')
        return redirect('/dashboard/')

    topic = get_object_or_404(Topic, pk=topic_pk)
    session = topic.session

    if request.method == 'POST':
        table_type = request.POST.get('table_type', 'custom')
        title = request.POST.get('title', '').strip()
        headers_raw = request.POST.get('headers', '').strip()
        headers_json_raw = request.POST.get('headers_json', '').strip()
        rows_raw = request.POST.get('rows_data', '').strip()
        rows_json_raw = request.POST.get('rows_json', '').strip()
        sum_cols_raw = request.POST.get('sum_columns', '').strip()
        sum_cols_json_raw = request.POST.get('sum_columns_json', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Parse headers (prefer JSON if provided)
        headers = []
        if headers_json_raw:
            try:
                parsed_h = json.loads(headers_json_raw)
                if isinstance(parsed_h, list):
                    headers = [str(h).strip() for h in parsed_h if str(h).strip()]
            except Exception:
                pass

        if not headers and headers_raw:
            headers = [h.strip() for h in headers_raw.split(',') if h.strip()]

        if not headers:
            headers = PRESET_HEADERS_MAP.get(table_type, ['م', 'البيان', 'ملاحظات'])

        # Parse rows (prefer JSON if provided)
        rows_data = []
        if rows_json_raw:
            try:
                parsed_r = json.loads(rows_json_raw)
                if isinstance(parsed_r, list):
                    for r in parsed_r:
                        if isinstance(r, list):
                            rows_data.append([str(c) if c is not None else '' for c in r])
            except Exception:
                pass

        if not rows_data and rows_raw:
            for line in rows_raw.splitlines():
                line = line.strip()
                if line:
                    if '\t' in line:
                        row = [c.strip() for c in line.split('\t')]
                    else:
                        row = [c.strip() for c in line.split(',')]
                    rows_data.append(row)

        # Parse sum columns (prefer JSON if provided)
        sum_columns = []
        if sum_cols_json_raw:
            try:
                parsed_s = json.loads(sum_cols_json_raw)
                if isinstance(parsed_s, list):
                    for c in parsed_s:
                        if str(c).isdigit():
                            sum_columns.append(int(c))
            except Exception:
                pass

        if not sum_columns and sum_cols_raw:
            for c in sum_cols_raw.split(','):
                c = c.strip()
                if c.isdigit():
                    sum_columns.append(int(c))
        elif not sum_columns and table_type in PRESET_SUM_COLS_MAP:
            sum_columns = PRESET_SUM_COLS_MAP[table_type]

        order = topic.tables.count() + 1
        table = TopicTable.objects.create(
            topic=topic,
            table_type=table_type,
            title=title or dict(TABLE_PRESET_CHOICES).get(table_type, 'جدول'),
            headers=headers,
            rows_data=rows_data,
            sum_columns=sum_columns,
            order=order,
            notes=notes
        )
        messages.success(request, f'تمت إضافة الجدول «{table.title}» بنجاح.')
        if request.GET.get('next') == 'prepare' or session.status == 'draft':
            return redirect('council:session_prepare_edit', pk=session.pk)
        return redirect('council:topic_detail', pk=topic.pk)

    context = {
        'topic': topic,
        'session': session,
        'table': None,
        'preset_choices': TABLE_PRESET_CHOICES,
        'presets_json': json.dumps(PRESET_HEADERS_MAP, ensure_ascii=False),
        'preset_sum_cols_json': json.dumps(PRESET_SUM_COLS_MAP, ensure_ascii=False),
        'current_headers_json': json.dumps([], ensure_ascii=False),
        'current_rows_json': json.dumps([], ensure_ascii=False),
        'current_sum_cols_json': json.dumps([], ensure_ascii=False),
        'headers_text': '',
        'rows_text': '',
        'sum_columns_text': '',
        'page_title': f'إضافة جدول جديد – {topic.title[:40]}',
    }
    return render(request, 'council/table_form.html', context)


@login_required(login_url='/login/')
def table_edit_view(request, pk):
    """Edit an existing dynamic table (headers, rows, sum settings)."""
    if not (request.user.can_edit_table or request.user.is_super or getattr(request.user, 'can_prepare_agenda', False)):
        messages.error(request, 'ليس لديك صلاحية لتعديل الجداول.')
        return redirect('/dashboard/')

    table = get_object_or_404(TopicTable.objects.select_related('topic', 'topic__session'), pk=pk)
    topic = table.topic
    session = topic.session

    if request.method == 'POST':
        table.title = request.POST.get('title', '').strip() or table.title
        table.table_type = request.POST.get('table_type', table.table_type)
        headers_raw = request.POST.get('headers', '').strip()
        headers_json_raw = request.POST.get('headers_json', '').strip()
        rows_raw = request.POST.get('rows_data', '').strip()
        rows_json_raw = request.POST.get('rows_json', '').strip()
        sum_cols_raw = request.POST.get('sum_columns', '').strip()
        sum_cols_json_raw = request.POST.get('sum_columns_json', '').strip()
        table.notes = request.POST.get('notes', '').strip()

        # Parse headers
        headers = []
        if headers_json_raw:
            try:
                parsed_h = json.loads(headers_json_raw)
                if isinstance(parsed_h, list):
                    headers = [str(h).strip() for h in parsed_h if str(h).strip()]
            except Exception:
                pass

        if not headers and headers_raw:
            headers = [h.strip() for h in headers_raw.split(',') if h.strip()]

        if headers:
            table.headers = headers

        # Parse rows
        rows_data = []
        if rows_json_raw:
            try:
                parsed_r = json.loads(rows_json_raw)
                if isinstance(parsed_r, list):
                    for r in parsed_r:
                        if isinstance(r, list):
                            rows_data.append([str(c) if c is not None else '' for c in r])
            except Exception:
                pass

        if not rows_data and rows_raw:
            for line in rows_raw.splitlines():
                line = line.strip()
                if line:
                    if '\t' in line:
                        row = [c.strip() for c in line.split('\t')]
                    else:
                        row = [c.strip() for c in line.split(',')]
                    rows_data.append(row)

        table.rows_data = rows_data

        # Parse sum columns
        sum_columns = []
        if sum_cols_json_raw:
            try:
                parsed_s = json.loads(sum_cols_json_raw)
                if isinstance(parsed_s, list):
                    for c in parsed_s:
                        if str(c).isdigit():
                            sum_columns.append(int(c))
            except Exception:
                pass

        if not sum_columns and sum_cols_raw:
            for c in sum_cols_raw.split(','):
                c = c.strip()
                if c.isdigit():
                    sum_columns.append(int(c))

        table.sum_columns = sum_columns
        table.save()
        messages.success(request, f'تم تحديث الجدول «{table.title}» بنجاح.')
        if request.GET.get('next') == 'prepare' or session.status == 'draft':
            return redirect('council:session_prepare_edit', pk=session.pk)
        return redirect('council:topic_detail', pk=topic.pk)

    # Format current rows as text for textarea fallback
    rows_text_lines = []
    for r in table.rows_data:
        if isinstance(r, list):
            rows_text_lines.append(', '.join(str(c) for c in r))
    rows_text = '\n'.join(rows_text_lines)

    context = {
        'table': table,
        'topic': topic,
        'session': session,
        'preset_choices': TABLE_PRESET_CHOICES,
        'presets_json': json.dumps(PRESET_HEADERS_MAP, ensure_ascii=False),
        'preset_sum_cols_json': json.dumps(PRESET_SUM_COLS_MAP, ensure_ascii=False),
        'current_headers_json': json.dumps(table.headers if isinstance(table.headers, list) else [], ensure_ascii=False),
        'current_rows_json': json.dumps(table.rows_data if isinstance(table.rows_data, list) else [], ensure_ascii=False),
        'current_sum_cols_json': json.dumps(table.sum_columns if isinstance(table.sum_columns, list) else [], ensure_ascii=False),
        'headers_text': ', '.join(table.headers) if isinstance(table.headers, list) else '',
        'rows_text': rows_text,
        'sum_columns_text': ', '.join(str(c) for c in table.sum_columns) if isinstance(table.sum_columns, list) else '',
        'page_title': f'تعديل جدول: {table.title}',
    }
    return render(request, 'council/table_form.html', context)


@login_required(login_url='/login/')
def table_delete_view(request, pk):
    """Delete a table from a topic."""
    if not (request.user.can_delete_table or request.user.is_super or getattr(request.user, 'can_prepare_agenda', False)):
        messages.error(request, 'ليس لديك صلاحية لحذف الجداول.')
        return redirect('/dashboard/')

    table = get_object_or_404(TopicTable.objects.select_related('topic', 'topic__session'), pk=pk)
    topic_pk = table.topic.pk
    session = table.topic.session

    title = table.title
    table.delete()
    messages.success(request, f'تم حذف الجدول «{title}» بنجاح.')
    if request.GET.get('next') == 'prepare' or session.status == 'draft':
        return redirect('council:session_prepare_edit', pk=session.pk)
    return redirect('council:topic_detail', pk=topic_pk)
