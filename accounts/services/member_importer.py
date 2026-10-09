"""
Member Bulk Importer Service
Supports Excel (.xlsx, .csv) and Word (.docx) formats.
Auto-generates usernames and initial passwords.
Assigns zero default permissions.
"""
import io
import csv
import re
from datetime import datetime
from django.db import transaction
from django.utils.text import slugify

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from docx import Document

from accounts.models import User, CouncilPermission


TITLE_MAP = {
    'مدير النظام الأعلى': 'مدير_النظام',
    'مدير النظام': 'مدير_النظام',
    'نائب رئيس الجامعة': 'نائب_رئيس',
    'نائب رئيس': 'نائب_رئيس',
    'مستشار رئيس الجامعة': 'مستشار',
    'مستشار': 'مستشار',
    'مساعد رئيس الجامعة': 'مساعد',
    'مساعد': 'مساعد',
    'رئيس الجامعة': 'رئيس_الجامعة',
    'رئيس جامعة': 'رئيس_الجامعة',
    'الأمين العام المساعد': 'امين_عام_مساعد',
    'أمين عام مساعد': 'امين_عام_مساعد',
    'امين عام مساعد': 'امين_عام_مساعد',
    'الأمين العام للجامعة': 'امين_عام',
    'الأمين العام': 'امين_عام',
    'أمين عام': 'امين_عام',
    'امين عام': 'امين_عام',
    'عميد كلية': 'عميد',
    'عميد': 'عميد',
    'مدير عام الإدارة المساعدة': 'مدير_عام_المساعدة',
    'مدير عام': 'مدير_عام_المساعدة',
    'موظف إدارة مساعدة': 'موظف_المساعدة',
    'موظف': 'موظف_المساعدة',
}


CATEGORY_MAP = {
    'مكتب رئيس الجامعة والمستشارون والمساعدون': 'presidency_office',
    'مكتب رئيس الجامعة': 'presidency_office',
    'المستشارون والمساعدون': 'presidency_office',
    'مستشار': 'presidency_office',
    'مساعد': 'presidency_office',
    'نواب رئيس الجامعة': 'vice_presidents',
    'نواب الرئيس': 'vice_presidents',
    'نيابات': 'vice_presidents',
    'فئة العمداء والكليات': 'deans',
    'العمداء والكليات': 'deans',
    'العمداء': 'deans',
    'الكليات': 'deans',
    'الأمانة العامة وإدارة المجلس': 'secretariat_admin',
    'الأمانة العامة': 'secretariat_admin',
    'الامانة العامة': 'secretariat_admin',
    'إدارة المجلس': 'secretariat_admin',
    'فئة الممثلين': 'representatives',
    'الممثلين': 'representatives',
    'الممثلون': 'representatives',
    'نقابة': 'representatives',
}


def normalize_title(title_raw, default='عميد'):
    if not title_raw:
        return default
    clean = str(title_raw).strip()
    for k, v in TITLE_MAP.items():
        if k in clean:
            return v
    valid_keys = [k for k, _ in User.TITLE_CHOICES]
    if clean in valid_keys:
        return clean
    return default


def normalize_category(category_raw, title_code='عميد', default_category=''):
    valid_keys = [k for k, _ in User.LOGIN_CATEGORY_CHOICES]
    if category_raw:
        clean = str(category_raw).strip()
        if clean in valid_keys:
            return clean
        for k, v in CATEGORY_MAP.items():
            if k in clean:
                return v
    if default_category and default_category in valid_keys:
        return default_category
    return User.infer_category_from_title(title_code)


def generate_unique_username(full_name, base_counter=1):
    """Generate a clean, unique username."""
    # Try using transliteration or numbers
    parts = re.findall(r'[a-zA-Z0-9]+', full_name)
    if parts:
        base = '_'.join(parts).lower()
    else:
        base = f"member_{int(datetime.now().timestamp()) % 10000}"

    candidate = base
    cnt = base_counter
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}_{cnt}"
        cnt += 1
    return candidate


def parse_and_import_members(uploaded_file, default_title='عميد', default_category='', auto_create_seats=True, manager=None):
    """
    Parse uploaded file (Excel or Word) and create user accounts.
    Returns:
        dict: {'created': count, 'skipped': count, 'users': list_of_users, 'errors': list_of_errs}
    """
    from council.models import EntitySeat

    filename = uploaded_file.name.lower()
    rows = []

    if filename.endswith('.xlsx') or filename.endswith('.xls'):
        rows = _read_excel(uploaded_file)
    elif filename.endswith('.csv'):
        rows = _read_csv(uploaded_file)
    elif filename.endswith('.docx') or filename.endswith('.doc'):
        rows = _read_word(uploaded_file)
    else:
        raise ValueError('صيغة الملف غير مدعومة. يرجى استخدام .xlsx أو .csv أو .docx')

    created_users = []
    skipped_count = 0
    errors = []

    with transaction.atomic():
        for idx, row in enumerate(rows, start=1):
            full_name = row.get('full_name', '').strip()
            if not full_name:
                continue

            username = row.get('username', '').strip()
            if not username:
                username = generate_unique_username(full_name, base_counter=idx)
            else:
                if User.objects.filter(username=username).exists():
                    username = generate_unique_username(username, base_counter=idx)

            title = normalize_title(row.get('title'), default=default_title)
            login_category = normalize_category(
                row.get('category'),
                title_code=title,
                default_category=default_category,
            )
            department = row.get('department', '').strip()
            phone = row.get('phone', '').strip()
            email = row.get('email', '').strip()

            try:
                user = User(
                    username=username,
                    full_name=full_name,
                    title=title,
                    login_category=login_category,
                    official_title=row.get('title', '').strip() or dict(User.TITLE_CHOICES).get(title, ''),
                    department=department,
                    phone=phone,
                    email=email,
                    manager=manager,
                    is_active=True,
                )
                user.set_password('123456')  # Default temporary password
                user.save()

                # Zero permissions default
                CouncilPermission.objects.get_or_create(user=user)

                # Optionally create/link EntitySeat so the member appears in their category on login
                if auto_create_seats and title not in ('مدير_النظام', 'موظف_المساعدة', 'ادارة_مساعدة'):
                    seat_type = User.category_to_seat_type(login_category, title)
                    seat_name = (department or user.official_title or full_name).strip()
                    existing_seat = EntitySeat.objects.filter(name=seat_name).first()
                    if existing_seat and not existing_seat.primary_rep_id:
                        existing_seat.primary_rep = user
                        existing_seat.seat_type = seat_type
                        existing_seat.is_active = True
                        existing_seat.save()
                    elif not existing_seat:
                        EntitySeat.objects.create(
                            name=seat_name,
                            seat_type=seat_type,
                            order=user.order if (user.order and user.order != 999) else 999,
                            primary_rep=user,
                            is_active=True,
                        )

                created_users.append(user)
            except Exception as e:
                errors.append(f"السطر {idx} ({full_name}): {str(e)}")
                skipped_count += 1

    return {
        'total': len(rows),
        'created': len(created_users),
        'skipped': skipped_count,
        'users': created_users,
        'errors': errors,
    }


def _read_excel(file_obj):
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb.active
    rows_data = []

    header_map = {}
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if not any(row):
            continue
        if row_idx == 1:
            # Map headers
            for col_idx, cell in enumerate(row):
                if not cell:
                    continue
                header = str(cell).strip()
                if 'اسم' in header and 'مستخدم' not in header:
                    header_map['full_name'] = col_idx
                elif 'فئة' in header or 'فئه' in header or 'بوابة' in header:
                    header_map['category'] = col_idx
                elif 'صفة' in header or 'لقب' in header or 'دور' in header:
                    header_map['title'] = col_idx
                elif 'جهة' in header or 'كلية' in header or 'إدارة' in header:
                    header_map['department'] = col_idx
                elif 'هاتف' in header or 'جوال' in header:
                    header_map['phone'] = col_idx
                elif 'بريد' in header or 'إيميل' in header or 'email' in header.lower():
                    header_map['email'] = col_idx
                elif 'مستخدم' in header or 'username' in header.lower():
                    header_map['username'] = col_idx
            continue

        # Data row
        full_name_idx = header_map.get('full_name', 0)
        full_name = str(row[full_name_idx] or '').strip() if full_name_idx < len(row) else ''
        if not full_name:
            continue

        item = {'full_name': full_name}
        if 'category' in header_map and header_map['category'] < len(row):
            item['category'] = str(row[header_map['category']] or '').strip()
        if 'title' in header_map and header_map['title'] < len(row):
            item['title'] = str(row[header_map['title']] or '').strip()
        if 'department' in header_map and header_map['department'] < len(row):
            item['department'] = str(row[header_map['department']] or '').strip()
        if 'phone' in header_map and header_map['phone'] < len(row):
            item['phone'] = str(row[header_map['phone']] or '').strip()
        if 'email' in header_map and header_map['email'] < len(row):
            item['email'] = str(row[header_map['email']] or '').strip()
        if 'username' in header_map and header_map['username'] < len(row):
            item['username'] = str(row[header_map['username']] or '').strip()

        rows_data.append(item)

    return rows_data


def _read_csv(file_obj):
    content = file_obj.read().decode('utf-8-sig', errors='replace')
    reader = csv.reader(io.StringIO(content))
    rows_data = []
    header_map = {}

    for row_idx, row in enumerate(reader, start=1):
        if not row or not any(row):
            continue
        if row_idx == 1:
            for col_idx, cell in enumerate(row):
                header = cell.strip()
                if 'اسم' in header and 'مستخدم' not in header:
                    header_map['full_name'] = col_idx
                elif 'فئة' in header or 'فئه' in header or 'بوابة' in header:
                    header_map['category'] = col_idx
                elif 'صفة' in header or 'لقب' in header:
                    header_map['title'] = col_idx
                elif 'جهة' in header or 'كلية' in header:
                    header_map['department'] = col_idx
                elif 'هاتف' in header:
                    header_map['phone'] = col_idx
                elif 'بريد' in header or 'email' in header.lower():
                    header_map['email'] = col_idx
                elif 'username' in header.lower():
                    header_map['username'] = col_idx
            continue

        name_idx = header_map.get('full_name', 0)
        full_name = row[name_idx].strip() if name_idx < len(row) else ''
        if not full_name:
            continue

        item = {'full_name': full_name}
        if 'category' in header_map and header_map['category'] < len(row):
            item['category'] = row[header_map['category']].strip()
        if 'title' in header_map and header_map['title'] < len(row):
            item['title'] = row[header_map['title']].strip()
        if 'department' in header_map and header_map['department'] < len(row):
            item['department'] = row[header_map['department']].strip()
        if 'phone' in header_map and header_map['phone'] < len(row):
            item['phone'] = row[header_map['phone']].strip()
        if 'email' in header_map and header_map['email'] < len(row):
            item['email'] = row[header_map['email']].strip()
        rows_data.append(item)

    return rows_data


def _read_word(file_obj):
    doc = Document(file_obj)
    rows_data = []

    # If Word document has tables:
    for table in doc.tables:
        header_map = {}
        for row_idx, row in enumerate(table.rows):
            cells = [c.text.strip() for c in row.cells]
            if not any(cells):
                continue
            if row_idx == 0:
                for col_idx, cell in enumerate(cells):
                    if 'اسم' in cell and 'مستخدم' not in cell:
                        header_map['full_name'] = col_idx
                    elif 'فئة' in cell or 'فئه' in cell or 'بوابة' in cell:
                        header_map['category'] = col_idx
                    elif 'صفة' in cell or 'لقب' in cell or 'دور' in cell:
                        header_map['title'] = col_idx
                    elif 'كلية' in cell or 'جهة' in cell:
                        header_map['department'] = col_idx
                    elif 'هاتف' in cell:
                        header_map['phone'] = col_idx
                    elif 'بريد' in cell:
                        header_map['email'] = col_idx
                continue

            name_idx = header_map.get('full_name', 0)
            full_name = cells[name_idx] if name_idx < len(cells) else ''
            if not full_name:
                continue

            item = {'full_name': full_name}
            if 'category' in header_map and header_map['category'] < len(cells):
                item['category'] = cells[header_map['category']]
            if 'title' in header_map and header_map['title'] < len(cells):
                item['title'] = cells[header_map['title']]
            if 'department' in header_map and header_map['department'] < len(cells):
                item['department'] = cells[header_map['department']]
            if 'phone' in header_map and header_map['phone'] < len(cells):
                item['phone'] = cells[header_map['phone']]
            if 'email' in header_map and header_map['email'] < len(cells):
                item['email'] = cells[header_map['email']]
            rows_data.append(item)

    # If no tables, read bullet points or numbered paragraphs
    if not rows_data:
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text or len(text) < 3:
                continue
            # Strip leading numbers/bullets like "1-", "1.", "-", "*"
            clean_name = re.sub(r'^[0-9\-\.\*\s\)]+', '', text).strip()
            if clean_name and len(clean_name) >= 3:
                rows_data.append({'full_name': clean_name})

    return rows_data


def generate_sample_excel_template():
    """
    Generate an elegant Excel template (.xlsx) with Arabic styling.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'أعضاء مجلس الجامعة'
    ws.views.sheetView[0].rightToLeft = True

    # Header styling (Navy + Gold)
    header_fill = PatternFill(start_color='0F3460', end_color='0F3460', fill_type='solid')
    header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
    border_thin = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    headers = [
        'الاسم الكامل واللقب الأكاديمي (إلزامي)',
        'الموقع في بوابة الدخول (اختياري)',
        'الصفة / الدور في المجلس',
        'الكلية / الجهة / الإدارة',
        'رقم الهاتف',
        'البريد الإلكتروني',
        'اسم المستخدم المقترح (إنجليزي - اختياري)'
    ]

    ws.append(headers)

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border_thin

    # Sample rows
    samples = [
        ['أ.د. رئيس الجامعة', 'مكتب رئيس الجامعة والمستشارون والمساعدون', 'رئيس الجامعة', 'رئاسة الجامعة', '777000111', 'president@univ.edu', 'president'],
        ['أ.د. محمد عبدالله الحكيمي', 'نواب رئيس الجامعة', 'نائب رئيس الجامعة', 'نيابة رئاسة الجامعة للشؤون الأكاديمية', '777111222', 'm.hakimi@univ.edu', 'vice_academic2'],
        ['د. أحمد صالح القباطي', 'الأمانة العامة وإدارة المجلس', 'الأمين العام المساعد', 'الأمانة العامة للجامعة', '777222333', 'asst.sec@univ.edu', 'asst_sec'],
        ['أ.د. يحيى أحمد طاهر', 'عمداء الكليات', 'عميد كلية', 'كلية الهندسة وتكنولوجيا المعلومات', '777333444', 'y.taher@univ.edu', 'dean_eng2'],
        ['أ.د. نادية قاسم المنصوري', 'عمداء الكليات', 'عميد كلية', 'كلية الطب والعلوم الصحية', '777555666', 'n.mansoori@univ.edu', 'dean_med2'],
        ['د. رشيد حمود البريهي', 'مكتب رئيس الجامعة والمستشارون والمساعدون', 'مستشار رئيس الجامعة', 'رئاسة الجامعة', '777888999', 'r.boraihi@univ.edu', 'advisor_rashid'],
    ]

    for row_data in samples:
        ws.append(row_data)

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 5, 20)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
