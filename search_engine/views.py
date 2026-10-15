import re
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.html import escape

from council.models import Topic, CouncilSession, user_can_view_drafts


# ---------------------------------------------------------------------------
# Arabic NLP Normalization, Tokenization & Highlighting Utilities
# ---------------------------------------------------------------------------

_AR_DIGITS_MAP = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
_DIACRITICS_RE = re.compile(r'[\u0640\u064B-\u065F\u0670\u06D6-\u06ED]')

# Prefix titles like: أ.م.د. / أ.د. / د. / م. / أ. (with dot or slash, with or without space)
_ABBR_PREFIX_RE = re.compile(
    r'(?:^|(?<=\s))(?:[أاإآ]\s*[\.\/]\s*م\s*[\.\/]\s*د|[أاإآ]\s*[\.\/]\s*د|د|م|[أاإآ])\s*[\.\/]+\s*',
    re.UNICODE
)

# Standalone honorific words that users often type before a name (e.g. "الدكتور أحمد", "الطالب محمد")
# which might not be written inside a table cell that only stores the bare full name.
_HONORIFIC_STOPWORDS = {
    'دكتور', 'الدكتور', 'دكتوره', 'الدكتوره', 'دكاتره', 'الدكاتره',
    'استاذ', 'الاستاذ', 'استاذه', 'الاستاذه',
    'مشارك', 'المشارك', 'مساعد', 'المساعد',
    'طالب', 'الطالب', 'طالبه', 'الطالبه', 'طلاب', 'الطلاب',
    'مهندس', 'المهندس', 'مهندسه', 'المهندسه',
    'قاضي', 'القاضي', 'شيخ', 'الشيخ',
    'باحث', 'الباحث', 'باحثه', 'الباحثه',
    'اخ', 'الاخ', 'اخت', 'الاخت',
    'مقدم', 'المقدم', 'عقيد', 'العقيد', 'عميد', 'العميد',
}

# Compound "عبد ..." normalization (unifies "عبد الوهاب" and "عبدالوهاب", "عبد الله" and "عبدالله")
_ABD_COMPOUND_RE = re.compile(r'(^|\s)عبد\s+(?=ال|الله|ربه|ربهم)', re.UNICODE)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for high-precision, fault-tolerant search matching.

    - Converts Arabic-Indic numerals to standard digits
    - Strips tashkeel (diacritics) and tatweel (kashida)
    - Unifies Alef variants (أ, إ, آ, ٱ -> ا)
    - Unifies Taa Marbuta (ة -> ه)
    - Unifies Yaa / Alef Maqsura / Hamza-on-Yaa (ى, ئ -> ي)
    - Unifies Hamza-on-Waw (ؤ -> و)
    - Unifies compound 'عبد ال...' spacing ('عبد الوهاب' -> 'عبدالوهاب')
    - Lowercases Latin characters and collapses whitespace
    """
    if not text:
        return ''
    s = str(text).translate(_AR_DIGITS_MAP)
    s = _DIACRITICS_RE.sub('', s)
    s = _ABBR_PREFIX_RE.sub(' ', s)

    # Character unification
    s = re.sub(r'[أإآٱ]', 'ا', s)
    s = s.replace('ة', 'ه')
    s = re.sub(r'[ىئ]', 'ي', s)
    s = s.replace('ؤ', 'و')

    # Unify compound "عبد ال..." / "عبد الله"
    s = _ABD_COMPOUND_RE.sub(r'\1عبد', s)

    # Replace punctuation separators with space
    s = re.sub(r'[،,;؛:\-\(\)\[\]«»"\'\/\\|]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def extract_query_tokens(query: str) -> dict:
    """Parse a user search query into core tokens and optional honorific tokens.

    Returns dict:
        raw_query   : original stripped query
        norm_query  : full normalized query
        core_tokens : list of normalized mandatory tokens for matching
        all_tokens  : list of all normalized tokens (including honorifics)
        raw_tokens  : list of cleaned tokens for regex highlighting
    """
    raw_query = (query or '').strip()
    if not raw_query:
        return {
            'raw_query': '',
            'norm_query': '',
            'core_tokens': [],
            'all_tokens': [],
            'raw_tokens': [],
        }

    # Pre-clean abbreviated prefixes like "د." or "أ.م.د."
    cleaned = _ABBR_PREFIX_RE.sub(' ', raw_query)
    # Unify "عبد ال..." spacing before splitting into words
    cleaned = re.sub(r'(^|\s)عبد\s+(?=[أإآا]ل|[أإآا]لله|ربه)', r'\1عبد', cleaned)

    raw_words = [
        w.strip('،,;؛:.-()[]«»"\'/\\|')
        for w in re.split(r'\s+', cleaned)
        if w.strip('،,;؛:.-()[]«»"\'/\\|')
    ]

    norm_query = normalize_arabic(raw_query)
    all_tokens = [w for w in norm_query.split(' ') if w]

    # Separate honorific stopwords from core name/subject tokens
    non_honorific = [t for t in all_tokens if t not in _HONORIFIC_STOPWORDS and len(t) > 1]
    core_tokens = non_honorific if non_honorific else all_tokens

    # Keep raw tokens (without lone single-letter abbreviations) for highlighting
    raw_tokens = [w for w in raw_words if len(w) > 1 or w.isdigit()]
    if not raw_tokens and raw_words:
        raw_tokens = raw_words

    return {
        'raw_query': raw_query,
        'norm_query': norm_query,
        'core_tokens': core_tokens,
        'all_tokens': all_tokens,
        'raw_tokens': raw_tokens,
    }


def _chars_to_arabic_regex(text: str) -> str:
    """Map each character of *text* to its Arabic equivalence class with optional diacritics."""
    parts = []
    for ch in text:
        if ch in ('ا', 'أ', 'إ', 'آ', 'ٱ'):
            parts.append('[اأإآٱ]')
        elif ch in ('ة', 'ه'):
            parts.append('[ةه]')
        elif ch in ('ي', 'ى', 'ئ'):
            parts.append('[يىئ]')
        elif ch in ('و', 'ؤ'):
            parts.append('[وؤ]')
        elif ch.isspace():
            parts.append(r'\s+')
        else:
            parts.append(re.escape(ch))
    return r'[\u0640\u064B-\u065F\u0670]*'.join(parts)


def _token_to_arabic_regex(token: str) -> str:
    """Convert a single search token into an Arabic-tolerant regex pattern
    that matches regardless of hamzas, taa marbuta/haa, alef maqsura/yaa,
    tashkeel, tatweel, or 'عبد ' spacing.
    """
    clean_tok = _DIACRITICS_RE.sub('', token.strip())
    if not clean_tok:
        return ''

    norm_tok = normalize_arabic(clean_tok)
    if norm_tok.startswith('عبد') and len(norm_tok) > 4:
        rest = clean_tok[3:].lstrip()
        prefix_pat = r'ع[\u0640\u064B-\u065F\u0670]*ب[\u0640\u064B-\u065F\u0670]*د\s*'
        return prefix_pat + _chars_to_arabic_regex(rest)

    return _chars_to_arabic_regex(clean_tok)


def _build_highlight_regex(query: str):
    """Build a compiled regex that matches the full query or any of its meaningful tokens."""
    if not query or not query.strip():
        return None
    parsed = extract_query_tokens(query)
    patterns = []

    # 1. Full phrase pattern (highest priority in alternation)
    full_pat = _chars_to_arabic_regex(_DIACRITICS_RE.sub('', query.strip()))
    if full_pat:
        patterns.append(full_pat)

    # 2. Individual token patterns (sorted longest first)
    tokens_for_hl = sorted(set(parsed['raw_tokens'] + parsed['core_tokens']), key=len, reverse=True)
    for tok in tokens_for_hl:
        if len(tok) < 2 and not tok.isdigit():
            continue
        pat = _token_to_arabic_regex(tok)
        if pat and pat not in patterns:
            patterns.append(pat)
        # Also add bare form without leading 'ال' if token starts with 'ال'
        if tok.startswith('ال') and len(tok) >= 5:
            bare_pat = _token_to_arabic_regex(tok[2:])
            if bare_pat and bare_pat not in patterns:
                patterns.append(bare_pat)

    if not patterns:
        return None
    return re.compile('|'.join(f'(?:{p})' for p in patterns), re.IGNORECASE | re.UNICODE)


def _highlight(text: str, query: str) -> str:
    """Safely escape HTML in *text* and wrap every occurrence of *query* (or its
    Arabic-normalized tokens) inside <mark> tags for display.
    """
    if not text:
        return ''
    safe_text = escape(str(text))
    if not query or not query.strip():
        return safe_text

    regex = _build_highlight_regex(query)
    if not regex:
        return safe_text
    return regex.sub(lambda m: f'<mark>{m.group(0)}</mark>', safe_text)


def _extract_snippet(raw_text: str, query: str, window: int = 260) -> str:
    """Extract a clean, word-boundary-aligned snippet around the first match in *raw_text*
    and highlight all matched terms safely without ever breaking HTML tags.
    """
    if not raw_text:
        return ''
    text_str = str(raw_text).strip()
    if not query or not query.strip():
        snippet = text_str[:window]
        return escape(snippet) + ('…' if len(text_str) > window else '')

    regex = _build_highlight_regex(query)
    match = regex.search(text_str) if regex else None

    if match:
        first_pos = match.start()
        start = max(0, first_pos - 80)
        end = min(len(text_str), first_pos + (match.end() - match.start()) + (window - 80))
        if start > 0:
            space_idx = text_str.find(' ', start)
            if 0 <= space_idx < first_pos:
                start = space_idx + 1
        if end < len(text_str):
            space_idx = text_str.rfind(' ', first_pos, end)
            if space_idx > first_pos:
                end = space_idx
    else:
        start = 0
        end = min(len(text_str), window)

    snippet_raw = text_str[start:end].strip()
    prefix = '… ' if start > 0 else ''
    suffix = ' …' if end < len(text_str) else ''
    return prefix + _highlight(snippet_raw, query) + suffix


def _token_matches_norm_text(token: str, norm_text: str) -> bool:
    """Check whether a normalized token matches inside normalized text,
    accounting for optional definite article 'ال' on longer words.
    """
    if not token or not norm_text:
        return False
    if token in norm_text:
        return True
    if token.startswith('ال') and len(token) >= 5:
        bare = token[2:]
        if bare in norm_text:
            return True
    return False


def _all_tokens_match(tokens: list, norm_text: str) -> bool:
    """Return True if all tokens in *tokens* match inside *norm_text*."""
    if not tokens:
        return True
    if not norm_text:
        return False
    return all(_token_matches_norm_text(t, norm_text) for t in tokens)


def _any_token_matches(tokens: list, norm_text: str) -> bool:
    """Return True if at least one token in *tokens* matches inside *norm_text*."""
    if not tokens or not norm_text:
        return False
    return any(_token_matches_norm_text(t, norm_text) for t in tokens)


def _normalize_table_structure(headers: list, rows_data: list):
    """Detect if a TopicTable's `headers` list is actually the first data row
    (e.g. a committee member row containing academic titles or long names).
    If so, synthesize clean column headers and prepend the original `headers` to `rows_data`.
    """
    if not headers:
        return [], rows_data or []

    header_looks_like_data = False
    for h in headers:
        h_str = str(h).strip()
        if len(h_str) > 38 or any(p in h_str for p in ('أ.د', 'أ.م.د', 'ا.د', 'د.', 'د/', 'رئيساً', 'عضواً')):
            header_looks_like_data = True
            break

    if header_looks_like_data:
        default_labels = ['م', 'الاسم / البيان', 'الصفة / الجهة', 'الدور / الملاحظات']
        clean_headers = [
            default_labels[i] if i < len(default_labels) else f'بيان {i + 1}'
            for i in range(len(headers))
        ]
        return clean_headers, [headers] + list(rows_data or [])

    return headers, list(rows_data or [])


# ---------------------------------------------------------------------------
# Unified Search Engine Core
# ---------------------------------------------------------------------------

def _search_topics_unified(
    query: str,
    mode: str = 'all',
    scope: str = 'all',
    session_id: str = '',
    year: str = '',
    category: str = '',
    vote_result: str = '',
    topic_status: str = '',
    include_drafts: bool = False,
    include_past_sessions: bool = True,
    allowed_session_id: int = None,
) -> dict:
    """Execute unified smart search across Topics, Decisions, Smart Tables (TopicTable),
    Signed Decisions, Votes, Attachments, and Recordings.
    """
    qs = Topic.objects.select_related(
        'session', 'decision', 'signed_decision'
    ).prefetch_related(
        'tables', 'votes', 'votes__member', 'attachments', 'recordings', 'target_seats'
    ).order_by('-session__date', 'order_number')

    if not include_drafts:
        qs = qs.exclude(session__status='draft')

    if not include_past_sessions:
        if allowed_session_id:
            qs = qs.filter(session_id=allowed_session_id)
        else:
            latest_id = qs.order_by('-session__date', '-session__session_number').values_list('session_id', flat=True).first()
            if latest_id:
                qs = qs.filter(session_id=latest_id)
            else:
                qs = qs.none()

    if scope == 'session' and session_id:
        qs = qs.filter(session_id=session_id)
    elif scope == 'year' and year:
        qs = qs.filter(session__academic_year=year)

    if category:
        qs = qs.filter(category=category)

    if topic_status:
        qs = qs.filter(status=topic_status)

    if vote_result:
        qs = qs.filter(votes__choice=vote_result).distinct()

    parsed = extract_query_tokens(query)
    core_tokens = parsed['core_tokens']
    norm_query = parsed['norm_query']
    has_query = bool(core_tokens)

    results = []
    total_matched_table_rows = 0
    total_decisions_matched = 0

    for topic in qs:
        decision_text = ''
        try:
            if hasattr(topic, 'decision') and topic.decision:
                decision_text = topic.decision.decision_text or ''
        except Exception:
            pass

        signed_dec_num = ''
        signed_dec_notes = ''
        try:
            if hasattr(topic, 'signed_decision') and topic.signed_decision:
                signed_dec_num = topic.signed_decision.decision_number or ''
                signed_dec_notes = topic.signed_decision.notes or ''
        except Exception:
            pass

        memo_info = ' '.join(filter(None, [
            topic.presenting_entity,
            f'مذكرة رقم {topic.memo_number}' if topic.memo_number else '',
            topic.memo_date,
        ]))

        vote_notes_combined = ' '.join(
            v.notes for v in topic.votes.all() if v.notes
        )
        attachments_text = ' '.join(
            f'{a.file_name} {a.description}' for a in topic.attachments.all() if (a.file_name or a.description)
        )
        recordings_text = ' '.join(
            f'{r.label} {r.transcription_text}' for r in topic.recordings.all() if (r.label or r.transcription_text)
        )

        if mode == 'person':
            field_map = [
                ('عنوان الموضوع', topic.title, 35),
                ('الأشخاص المذكورون', topic.mentioned_persons, 45),
                ('نص القرار', decision_text, 30),
                ('خلفية الموضوع', topic.background, 20),
                ('الأولويات والمقترحات', topic.priorities, 15),
            ]
        elif mode == 'decisions':
            field_map = [
                ('عنوان الموضوع', topic.title, 40),
                ('نص القرار', decision_text, 45),
                ('رقم القرار الموقّع', f'{signed_dec_num} {signed_dec_notes}'.strip(), 35),
                ('بيانات المذكرة والجهة العارضة', memo_info, 25),
                ('خلفية الموضوع', topic.background, 20),
                ('الأولويات والمقترحات', topic.priorities, 20),
            ]
        elif mode == 'tables':
            field_map = []
        else:
            field_map = [
                ('عنوان الموضوع', topic.title, 40),
                ('الأشخاص المذكورون', topic.mentioned_persons, 35),
                ('نص القرار', decision_text, 35),
                ('بيانات المذكرة والجهة العارضة', memo_info, 25),
                ('رقم القرار الموقّع', f'{signed_dec_num} {signed_dec_notes}'.strip(), 25),
                ('خلفية الموضوع', topic.background, 20),
                ('الأولويات والمقترحات', topic.priorities, 15),
                ('ملاحظات التصويت', vote_notes_combined, 10),
                ('المرفقات والأوليات', attachments_text, 10),
                ('التفريغ الصوتي', recordings_text, 10),
            ]

        highlights = {}
        match_locations = []
        found_in = []
        relevance_score = 0

        norm_topic_title = normalize_arabic(topic.title)

        # ---- Check Text Fields ----
        if has_query:
            for label, raw_value, weight in field_map:
                if not raw_value:
                    continue
                norm_val = normalize_arabic(raw_value)
                if not norm_val:
                    continue

                full_field_match = _all_tokens_match(core_tokens, norm_val)
                combined_with_title_match = (
                    len(core_tokens) > 1
                    and _any_token_matches(core_tokens, norm_val)
                    and _all_tokens_match(core_tokens, f'{norm_topic_title} {norm_val}')
                )

                if full_field_match or combined_with_title_match:
                    match_locations.append(label)
                    snippet_html = _extract_snippet(raw_value, query)
                    highlights[label] = snippet_html
                    found_in.append({
                        'field_label': label,
                        'snippet': snippet_html,
                        'label': label,
                        'excerpt': snippet_html,
                    })
                    relevance_score += weight
                    if norm_query and norm_query in norm_val:
                        relevance_score += 25
        else:
            if mode != 'tables':
                for label, raw_value, _ in field_map[:3]:
                    if raw_value:
                        snippet_html = _extract_snippet(raw_value, '', window=200)
                        highlights[label] = snippet_html
                        found_in.append({
                            'field_label': label,
                            'snippet': snippet_html,
                            'label': label,
                            'excerpt': snippet_html,
                        })

        # ---- Check Smart Tables (TopicTable) ----
        matched_tables = []
        topic_tables = list(topic.tables.all()) if mode in ('all', 'person', 'tables') else []

        for tbl in topic_tables:
            tbl_title = tbl.title or tbl.get_table_type_display()
            raw_headers = tbl.headers if isinstance(tbl.headers, list) else []
            raw_rows = tbl.rows_data if isinstance(tbl.rows_data, list) else []
            headers, rows_data = _normalize_table_structure(raw_headers, raw_rows)
            tbl_notes = tbl.notes or ''

            norm_tbl_title = normalize_arabic(tbl_title)
            norm_headers_str = normalize_arabic(' '.join(str(h) for h in headers))
            norm_tbl_context = f'{norm_topic_title} {norm_tbl_title} {norm_headers_str}'

            if has_query:
                specific_row_tokens = [
                    t for t in core_tokens
                    if not _token_matches_norm_text(t, norm_tbl_context)
                ]
            else:
                specific_row_tokens = []

            matched_rows = []

            if has_query:
                for row_idx, row in enumerate(rows_data, start=1):
                    if not isinstance(row, list):
                        continue
                    row_str = ' | '.join(str(cell).strip() for cell in row if str(cell).strip())
                    norm_row = normalize_arabic(row_str)
                    if not norm_row:
                        continue

                    if _all_tokens_match(core_tokens, f'{norm_tbl_context} {norm_row}'):
                        if specific_row_tokens:
                            row_qualifies = _all_tokens_match(specific_row_tokens, norm_row)
                        else:
                            row_qualifies = _all_tokens_match(core_tokens, norm_row) or _any_token_matches(core_tokens, norm_row)

                        if row_qualifies:
                            cells_info = []
                            summary_parts = []
                            for col_i, cell_val in enumerate(row):
                                cell_str = str(cell_val).strip()
                                col_header = str(headers[col_i]).strip() if col_i < len(headers) else f'عمود {col_i + 1}'
                                cell_highlighted = _highlight(cell_str, query) if cell_str else '—'
                                is_cell_match = '<mark>' in cell_highlighted
                                cells_info.append({
                                    'header': col_header,
                                    'value': cell_highlighted,
                                    'raw_value': cell_str,
                                    'is_match': is_cell_match,
                                })
                                if cell_str:
                                    if col_header and col_header not in ('م', '#', ''):
                                        summary_parts.append(f'<strong>{escape(col_header)}:</strong> {cell_highlighted}')
                                    else:
                                        summary_parts.append(cell_highlighted)

                            row_excerpt = ' &nbsp;|&nbsp; '.join(summary_parts)
                            matched_rows.append({
                                'row_number': row_idx,
                                'cells': cells_info,
                                'excerpt': row_excerpt,
                            })
            else:
                if mode == 'tables' and rows_data:
                    for row_idx, row in enumerate(rows_data[:3], start=1):
                        if not isinstance(row, list):
                            continue
                        cells_info = []
                        for col_i, cell_val in enumerate(row):
                            cell_str = str(cell_val).strip()
                            col_header = str(headers[col_i]).strip() if col_i < len(headers) else f'عمود {col_i + 1}'
                            cells_info.append({
                                'header': col_header,
                                'value': escape(cell_str) if cell_str else '—',
                                'raw_value': cell_str,
                                'is_match': False,
                            })
                        matched_rows.append({
                            'row_number': row_idx,
                            'cells': cells_info,
                            'excerpt': '',
                        })

            table_title_matched = has_query and _all_tokens_match(core_tokens, f'{norm_topic_title} {norm_tbl_title} {normalize_arabic(tbl_notes)}')

            if matched_rows or table_title_matched or (not has_query and mode == 'tables'):
                highlighted_headers = [_highlight(str(h), query) for h in headers]
                matched_tables.append({
                    'table': tbl,
                    'title': tbl_title,
                    'title_highlighted': _highlight(tbl_title, query),
                    'headers': headers,
                    'headers_highlighted': highlighted_headers,
                    'matched_rows': matched_rows,
                    'matched_rows_count': len(matched_rows),
                    'total_rows_count': len(rows_data),
                })

                loc_label = f'جدول: {tbl_title}'
                if loc_label not in match_locations:
                    match_locations.append(loc_label)

                if matched_rows:
                    for mr in matched_rows[:5]:
                        found_in.append({
                            'field_label': loc_label,
                            'snippet': mr['excerpt'],
                            'label': loc_label,
                            'excerpt': mr['excerpt'],
                        })
                    highlights[loc_label] = matched_rows[0]['excerpt']
                    relevance_score += 50 + min(len(matched_rows) * 5, 25)
                    total_matched_table_rows += len(matched_rows)
                else:
                    tbl_summary = f'{_highlight(tbl_title, query)} ({len(rows_data)} سجل)'
                    found_in.append({
                        'field_label': 'عنوان الجدول',
                        'snippet': tbl_summary,
                        'label': 'عنوان الجدول',
                        'excerpt': tbl_summary,
                    })
                    highlights[loc_label] = tbl_summary
                    relevance_score += 30

        if has_query:
            topic_qualifies = bool(found_in or matched_tables)
        else:
            if mode == 'tables':
                topic_qualifies = bool(matched_tables)
            else:
                topic_qualifies = True

        if topic_qualifies:
            if decision_text:
                total_decisions_matched += 1

            results.append({
                'topic': topic,
                'session': topic.session,
                'title_highlighted': _highlight(topic.title, query),
                'decision_text': decision_text,
                'decision_highlighted': _extract_snippet(decision_text, query, window=280) if decision_text else '',
                'has_decision': bool(decision_text),
                'signed_decision_number': signed_dec_num,
                'highlights': highlights,
                'match_locations': match_locations,
                'found_in': found_in,
                'context': found_in,
                'matched_tables': matched_tables,
                'matched_rows_count': sum(mt['matched_rows_count'] for mt in matched_tables),
                'relevance_score': relevance_score,
                'category_display': (
                    topic.get_category_display()
                    if hasattr(topic, 'get_category_display')
                    else topic.category
                ),
                'status_display': (
                    topic.get_clear_status_display()
                    if hasattr(topic, 'get_clear_status_display')
                    else topic.get_status_display()
                ),
            })

    if has_query:
        results.sort(
            key=lambda r: (
                -r['relevance_score'],
                -r['session'].date.toordinal() if r['session'] and r['session'].date else 0,
                r['topic'].order_number,
            )
        )

    return {
        'results': results,
        'total_count': len(results),
        'total_matched_table_rows': total_matched_table_rows,
        'total_decisions_matched': total_decisions_matched,
        'parsed_query': parsed,
    }


# ---------------------------------------------------------------------------
# Legacy Helper Compatibility Wrappers
# ---------------------------------------------------------------------------

def _build_topic_queryset(query: str, scope: str, session_id: str, year: str,
                          category: str, vote_result: str, include_drafts: bool = False):
    """Backward-compatible wrapper returning a Topic queryset matching unified search."""
    data = _search_topics_unified(
        query=query, mode='all', scope=scope, session_id=session_id,
        year=year, category=category, vote_result=vote_result,
        include_drafts=include_drafts,
    )
    matched_ids = [r['topic'].id for r in data['results']]
    return Topic.objects.filter(id__in=matched_ids).select_related('session', 'decision').prefetch_related('votes')


def _build_result_list(topics, query: str) -> list:
    """Backward-compatible wrapper returning result dicts."""
    data = _search_topics_unified(query=query, mode='all', include_drafts=True)
    topic_id_set = {t.id for t in topics}
    return [r for r in data['results'] if r['topic'].id in topic_id_set]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _render_unified_search(request, default_mode: str = 'all'):
    """Shared controller for both /search/ and /search/person/."""
    user = request.user
    can_general = bool(user.is_super or getattr(user, 'can_search_minutes', False))
    can_person = bool(user.is_super or getattr(user, 'can_search_person', False))

    if not (can_general or can_person):
        messages.error(request, 'ليس لديك صلاحية لاستخدام محرك البحث في محاضر المجلس.')
        return redirect('/dashboard/')

    q_param = request.GET.get('q', '').strip()
    name_param = request.GET.get('name', '').strip()
    query = q_param or name_param

    requested_mode = request.GET.get('mode', '').strip()
    if not requested_mode:
        requested_mode = 'person' if (name_param and not q_param) else default_mode

    if requested_mode not in ('all', 'person', 'decisions', 'tables'):
        requested_mode = 'all'

    if not can_general and can_person:
        mode = 'person'
    elif can_general and not can_person and requested_mode == 'person':
        mode = 'all'
    else:
        mode = requested_mode

    scope = request.GET.get('scope', 'all').strip() or 'all'
    session_id = request.GET.get('session_id', '').strip()
    year = request.GET.get('year', '').strip()
    category = request.GET.get('category', '').strip()
    vote_result = request.GET.get('vote_result', '').strip()
    topic_status = request.GET.get('topic_status', '').strip()

    include_drafts = user_can_view_drafts(user)
    searched = bool(
        query or category or vote_result or topic_status
        or (scope == 'session' and session_id)
        or (scope == 'year' and year)
        or (mode == 'tables' and request.GET.get('mode'))
    )

    search_data = {
        'results': [],
        'total_count': 0,
        'total_matched_table_rows': 0,
        'total_decisions_matched': 0,
        'parsed_query': extract_query_tokens(query),
    }

    has_past_perm = bool(user.is_super or getattr(user, 'can_view_past_sessions', False))

    sessions_qs = CouncilSession.objects.order_by('-date', '-session_number')
    if not include_drafts:
        sessions_qs = sessions_qs.exclude(status='draft')

    latest_accessible_session = sessions_qs.first() if not has_past_perm else None
    if not has_past_perm:
        if latest_accessible_session:
            sessions_qs = sessions_qs.filter(pk=latest_accessible_session.pk)
        else:
            sessions_qs = sessions_qs.none()

    if searched:
        search_data = _search_topics_unified(
            query=query,
            mode=mode,
            scope=scope,
            session_id=session_id,
            year=year,
            category=category,
            vote_result=vote_result,
            topic_status=topic_status,
            include_drafts=include_drafts,
            include_past_sessions=has_past_perm,
            allowed_session_id=latest_accessible_session.pk if latest_accessible_session else None,
        )

    all_sessions = list(sessions_qs.values(
        'id', 'session_number', 'title', 'date', 'academic_year', 'status'
    ))
    all_years = [
        y for y in (
            sessions_qs.order_by('-academic_year')
            .values_list('academic_year', flat=True)
            .distinct()
        ) if y
    ]

    try:
        category_choices = Topic._meta.get_field('category').choices or []
    except Exception:
        category_choices = []

    try:
        status_choices = Topic._meta.get_field('status').choices or []
    except Exception:
        status_choices = []

    context = {
        'query': query,
        'name': query,
        'mode': mode,
        'scope': scope,
        'session_id': session_id,
        'year': year,
        'category': category,
        'vote_result': vote_result,
        'topic_status': topic_status,
        'searched': searched,
        'results': search_data['results'],
        'total_count': search_data['total_count'],
        'total': search_data['total_count'],
        'total_matched_table_rows': search_data['total_matched_table_rows'],
        'total_decisions_matched': search_data['total_decisions_matched'],
        'parsed_query': search_data['parsed_query'],
        'all_sessions': all_sessions,
        'sessions_list': all_sessions,
        'all_years': all_years,
        'years': all_years,
        'category_choices': category_choices,
        'status_choices': status_choices,
        'can_general_search': can_general,
        'can_person_search': can_person,
        'page_title': 'البحث الذكي الشامل في محاضر المجلس',
    }
    return render(request, 'search_engine/search.html', context)


@login_required(login_url='/login/')
def search_view(request):
    """Unified Smart Search across Topics, Decisions, Smart Tables, Persons, and Votes."""
    return _render_unified_search(request, default_mode='all')


@login_required(login_url='/login/')
def person_search_view(request):
    """Person-focused entry point using the Unified Smart Search Engine."""
    return _render_unified_search(request, default_mode='person')
