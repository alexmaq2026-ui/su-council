"""
council/services/word_import.py
---------------------------------
Parse an uploaded Word (.docx) file and extract university council topics.
Supports full council session minutes (with multiple sections and tables)
as well as standard lists of agenda items.

Features:
- Accurate detection of the 7 official system categories:
    ('general',      'المواضيع العامة'),
    ('appointments', 'مواضيع التعيينات'),
    ('academic',     'مواضيع الشؤون الأكاديمية وشؤون أعضاء هيئة التدريس'),
    ('postgrad',     'مواضيع الدراسات العليا والبحث العلمي'),
    ('students',     'مواضيع شؤون الطلاب'),
    ('centers',      'مواضيع شؤون المراكز'),
    ('new_business', 'ما استجد من أعمال'),
- Immunity against table-row splitting and date-splitting (dates like 21/7/2026
  or numbered student tables won't create fake topics).
- Extraction of topic titles, background, and decisions/priorities.
- Support for interactive preview and selective topic importing.
"""

import re
import io
import docx
import mammoth


# ── Official 7 Categories Mapping ─────────────────────────────────────────────
CATEGORY_MAP = [
    (re.compile(r'عام|العامة'), 'general', 'المواضيع العامة'),
    (re.compile(r'تعيين|التعيينات'), 'appointments', 'مواضيع التعيينات'),
    (re.compile(r'أكاديم|هيئة التدريس|مناهج|خطط'), 'academic', 'مواضيع الشؤون الأكاديمية وشؤون أعضاء هيئة التدريس'),
    (re.compile(r'عليا|البحث العلمي|ماجستير|دكتوراه|سكوبس|scopus'), 'postgrad', 'مواضيع الدراسات العليا والبحث العلمي'),
    (re.compile(r'طلاب|الطلاب|خريج|الخريجين|شهادات'), 'students', 'مواضيع شؤون الطلاب'),
    (re.compile(r'مراكز|المراكز'), 'centers', 'مواضيع شؤون المراكز'),
    (re.compile(r'استجد|أعمال|مستجد'), 'new_business', 'ما استجد من أعمال'),
]

ORDINALS = [
    'الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر',
    'الحادي عشر', 'الثاني عشر', 'الثالث عشر', 'الرابع عشر', 'الخامس عشر', 'السادس عشر', 'السابع عشر',
    'الثامن عشر', 'التاسع عشر', 'العشرون', 'الحادي والعشرون', 'الثاني والعشرون', 'الثالث والعشرون',
    'الرابع والعشرون', 'الخامس والعشرون', 'السادس والعشرون', 'السابع والعشرون', 'الثامن والعشرون',
    'التاسع والعشرون', 'الثلاثون', 'الحادي والثلاثون', 'الثاني والثلاثون', 'الثالث والثلاثون',
    'الرابع والثلاثون', 'الخامس والثلاثون'
]

_ORDINAL_PATTERN = '|'.join(ORDINALS)
_TOPIC_HEADER_RE = re.compile(
    rf'^(?:الموضوع|البند)\s+({_ORDINAL_PATTERN})[\s\:\-]+$',
    re.UNICODE
)
_COMBINED_TOPIC_RE = re.compile(
    rf'^(?:الموضوع|البند)\s+(?:{_ORDINAL_PATTERN}|\d+|[٠-٩]+)[\s\:\-]+\s*(.+)$',
    re.UNICODE
)

# Arabic-Indic digit mapping (٠١٢٣٤٥٦٧٨٩ → 0123456789)
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

def _normalize_digits(text: str) -> str:
    return text.translate(_AR_DIGITS)


def _detect_category(text: str) -> tuple:
    """Infer category slug and human display from text keywords."""
    for pattern, slug, display in CATEGORY_MAP:
        if pattern.search(text):
            return slug, display
    return 'general', 'المواضيع العامة'


def parse_word_file(file_obj) -> list:
    """
    Parse a Word (.docx) file and extract a structured list of council topic dicts.
    
    Returns:
        list of dicts, each containing:
            index            : int (0-based)
            order_number     : int (1-based)
            title            : str (Topic heading/title)
            category         : str (One of the 7 valid model slugs)
            category_display : str (Arabic display title of the category)
            background       : str (Context and background paragraphs)
            priorities       : str (Decisions or recommendations)
            decision         : str (Extracted decision text if any)
            mentioned_persons: str (Empty or extracted names)
    """
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    
    if hasattr(file_obj, 'read'):
        raw_bytes = file_obj.read()
    else:
        with open(file_obj, 'rb') as f:
            raw_bytes = f.read()

    # Attempt parsing with python-docx
    paragraphs = []
    try:
        doc = docx.Document(io.BytesIO(raw_bytes))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    except Exception:
        pass

    # Fallback to mammoth if python-docx returned no paragraphs
    if not paragraphs:
        try:
            res = mammoth.extract_raw_text(io.BytesIO(raw_bytes))
            paragraphs = [line.strip() for line in res.value.splitlines() if line.strip()]
        except Exception:
            return []

    if not paragraphs:
        return []

    # First pass: Check if document has Council Session Minutes structure (ordinal topic markers)
    has_ordinal_topics = any(_TOPIC_HEADER_RE.match(p) for p in paragraphs)

    topics = []
    current_category = 'general'
    current_category_display = 'المواضيع العامة'
    current_topic = None

    if has_ordinal_topics:
        # ── Mode A: Council Session Minutes Parser ─────────────────────────────
        for i, text in enumerate(paragraphs):
            # 1. Section Header Detection (e.g. -المواضيع العامة- or مواضيع شؤون المراكز-)
            is_sec = False
            if any(k in text for k in ['المواضيع', 'مواضيع', 'شؤون المراكز', 'شؤون الطلاب', 'ما استجد']) and len(text) < 70:
                for pat, cat_slug, cat_name in CATEGORY_MAP:
                    if pat.search(text):
                        current_category = cat_slug
                        current_category_display = cat_name
                        is_sec = True
                        break
            if is_sec:
                continue

            # 2. Topic Header Detection (e.g. الموضوع الأول: -)
            m_ord = _TOPIC_HEADER_RE.match(text)
            if m_ord:
                # Capture the actual title from the subsequent non-empty paragraph
                title = ''
                if i + 1 < len(paragraphs):
                    next_p = paragraphs[i + 1]
                    norm_next = re.sub(r'[\u0640]', '', next_p.strip())
                    if not _TOPIC_HEADER_RE.match(next_p) and not re.match(r'^[\s\-\*]*(?:ال+ق+رار|التوصيات)', norm_next):
                        title = next_p
                
                if current_topic:
                    topics.append(current_topic)
                
                current_topic = {
                    'index': len(topics),
                    'order_number': len(topics) + 1,
                    'title': title or f'الموضوع {m_ord.group(1)}',
                    'category': current_category,
                    'category_display': current_category_display,
                    'background': [],
                    'priorities': '',
                    'decision': '',
                }
                continue

            # 3. Combined Header on one line
            m_comb = _COMBINED_TOPIC_RE.match(text)
            if m_comb and len(text) > 15 and not any(text.startswith(d) for d in ['202', '144', '19', '20']):
                title = m_comb.group(1).strip()
                if current_topic:
                    topics.append(current_topic)
                current_topic = {
                    'index': len(topics),
                    'order_number': len(topics) + 1,
                    'title': title,
                    'category': current_category,
                    'category_display': current_category_display,
                    'background': [],
                    'priorities': '',
                    'decision': '',
                }
                continue

            # 4. Content inside the active topic
            if current_topic:
                if text == current_topic['title']:
                    continue  # Already captured as title
                
                # Check for decision / recommendation markers
                norm_marker = re.sub(r'[\u0640]', '', text.strip())
                if re.match(r'^[\s\-\*]*(?:ال+ق+رار|التوصيات)', norm_marker):
                    clean_dec = re.sub(r'^[\s\-\*]*(?:ال+ق+[\u0640]*رار|التوصيات)[\s\:\-\–]*', '', text).strip()
                    if clean_dec:
                        current_topic['decision'] = clean_dec
                        current_topic['priorities'] = clean_dec
                else:
                    current_topic['background'].append(text)

        if current_topic:
            topics.append(current_topic)

    else:
        # ── Mode B: Generic Numbered List or Heading Parser ───────────────────
        generic_numbered_re = re.compile(r'^[\(\s]*(?:[٠-٩\d]+)[\.\-\)\s]+\s*(.+)$')
        for text in paragraphs:
            # Check section keyword
            slug, display = _detect_category(text)
            if any(k in text for k in ['المواضيع', 'مواضيع', 'المحور', 'القطاع']) and len(text) < 60:
                current_category = slug
                current_category_display = display
                continue

            # Check numbered item
            num_m = generic_numbered_re.match(_normalize_digits(text))
            if num_m and len(text) > 5 and not any(text.startswith(d) for d in ['202', '144', '19']):
                if current_topic:
                    topics.append(current_topic)
                heading = num_m.group(1).strip()
                current_topic = {
                    'index': len(topics),
                    'order_number': len(topics) + 1,
                    'title': heading,
                    'category': current_category,
                    'category_display': current_category_display,
                    'background': [],
                    'priorities': '',
                    'decision': '',
                }
                continue

            if current_topic:
                norm_marker = re.sub(r'[\u0640]', '', text.strip())
                if re.match(r'^[\s\-\*]*(?:ال+ق+رار|التوصيات)', norm_marker):
                    clean_dec = re.sub(r'^[\s\-\*]*(?:ال+ق+[\u0640]*رار|التوصيات)[\s\:\-\–]*', '', text).strip()
                    if clean_dec:
                        current_topic['decision'] = clean_dec
                        current_topic['priorities'] = clean_dec
                else:
                    current_topic['background'].append(text)

        if current_topic:
            topics.append(current_topic)

    # If still no topics found, fallback to treating first paragraph as title
    if not topics and paragraphs:
        title = paragraphs[0]
        bg = '\n'.join(paragraphs[1:]).strip()
        slug, display = _detect_category(title + ' ' + bg)
        topics = [{
            'index': 0,
            'order_number': 1,
            'title': title,
            'category': slug,
            'category_display': display,
            'background': [bg],
            'priorities': '',
            'decision': '',
        }]

    # Format output
    result = []
    for t in topics:
        bg_text = '\n'.join(t['background']).strip() if isinstance(t['background'], list) else t['background']
        result.append({
            'index': t['index'],
            'order_number': t['order_number'],
            'title': t['title'],
            'category': t['category'],
            'category_display': t.get('category_display', 'المواضيع العامة'),
            'background': bg_text,
            'priorities': t.get('priorities', ''),
            'decision': t.get('decision', ''),
            'mentioned_persons': '',
        })

    return result
