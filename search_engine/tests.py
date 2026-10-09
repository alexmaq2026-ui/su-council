from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, CouncilPermission
from council.models import CouncilSession, Topic, Decision, TopicTable
from search_engine.views import _search_topics_unified, normalize_arabic, extract_query_tokens


class UnifiedSmartSearchTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='search_admin',
            password='password123',
            full_name='مدير البحث',
            is_super=True,
        )
        self.person_only_user = User.objects.create_user(
            username='person_searcher',
            password='password123',
            full_name='باحث أشخاص',
            is_super=False,
        )
        CouncilPermission.objects.create(
            user=self.person_only_user,
            can_search_person=True,
            can_search_minutes=False,
        )

        self.session = CouncilSession.objects.create(
            session_number=10,
            title='الجلسة العاشرة',
            date=timezone.localdate(),
            academic_year='1448هـ - 2026/2027م',
            status='active',
            created_by=self.admin,
        )

        self.topic1 = Topic.objects.create(
            session=self.session,
            category='appointments',
            order_number=1,
            title='مناقشة مذكرة نيابة الشؤون الأكاديمية بشأن تعيين الدكتورة نبيلة حسن عبده الصرابي',
            background='بناءً على ترشيح كلية التربية لتعيين المذكورة في قسم علوم الحياة.',
            priorities='الموافقة على التعيين.',
            created_by=self.admin,
        )
        Decision.objects.create(
            topic=self.topic1,
            decision_text='إقرار تعيين الدكتورة نبيلة حسن عبده الصرابي في كلية التربية.',
            drafted_by=self.admin,
        )
        TopicTable.objects.create(
            topic=self.topic1,
            table_type='appointment',
            title='بيانات ومؤهلات الدكتورة نبيلة حسن عبده الصرابي',
            headers=['م', 'الاسم', 'الكلية', 'التخصص'],
            rows_data=[
                ['1', 'نبيلة حسن عبده الصرابي', 'التربية', 'علوم حياة'],
            ],
        )

        self.topic2 = Topic.objects.create(
            session=self.session,
            category='academic',
            order_number=2,
            title='ترقية أعضاء هيئة التدريس لدرجتي أستاذ مشارك وأستاذ',
            background='مذكرة الشؤون الأكاديمية بشأن ترقية كوكبة من الأساتذة.',
            created_by=self.admin,
        )
        TopicTable.objects.create(
            topic=self.topic2,
            table_type='promotion',
            title='جدول ترقيات أعضاء هيئة التدريس',
            headers=['م', 'الاسم', 'القسم العلمي', 'الكلية', 'الدرجة المطلوب الترقية إليها'],
            rows_data=[
                ['1', 'فائزة محمد عبدالهادي احمد المسني', 'المحاسبة', 'التجارة والاقتصاد', 'استاذ'],
                ['2', 'أ.م.د. عبد الوهاب عبد القدوس الوشلي', 'القانون العام', 'الشريعة والقانون', 'أستاذ'],
            ],
        )

    def test_arabic_normalization_and_tokenization(self):
        """Arabic normalization unifies hamzas, taa marbuta, compound Abd names, and strips titles."""
        self.assertEqual(normalize_arabic('أ.م.د. إبراهيم أحمد المطاع'), 'ابراهيم احمد المطاع')
        self.assertEqual(normalize_arabic('عبد الوهاب عبد القدوس'), 'عبدالوهاب عبدالقدوس')
        self.assertEqual(normalize_arabic('عبدالوهاب عبدالقدوس'), 'عبدالوهاب عبدالقدوس')

        tokens = extract_query_tokens('د. نبيلة الصرابي')
        self.assertEqual(tokens['core_tokens'], ['نبيله', 'الصرابي'])

    def test_non_adjacent_multi_token_person_search(self):
        """Searching 'نبيلة الصرابي' or 'فائزة المسني' matches full four-part names."""
        res1 = _search_topics_unified('نبيلة الصرابي', mode='person', include_drafts=True)
        self.assertEqual(res1['total_count'], 1)
        self.assertEqual(res1['results'][0]['topic'].pk, self.topic1.pk)

        res2 = _search_topics_unified('فائزة المسني', mode='person', include_drafts=True)
        self.assertEqual(res2['total_count'], 1)
        self.assertEqual(res2['results'][0]['topic'].pk, self.topic2.pk)
        # Only row 1 (فائزة) should match in the table, not row 2 (الوشلي)
        self.assertEqual(res2['results'][0]['matched_rows_count'], 1)

    def test_compound_abd_and_hamza_insensitive_search(self):
        """Searching 'عبدالوهاب الوشلي' matches 'عبد الوهاب عبد القدوس الوشلي' and 'أحمد' matches 'احمد'."""
        res_abd = _search_topics_unified('عبدالوهاب الوشلي', mode='all', include_drafts=True)
        self.assertEqual(res_abd['total_count'], 1)
        self.assertEqual(res_abd['results'][0]['matched_rows_count'], 1)

        res_hamza = _search_topics_unified('أحمد', mode='person', include_drafts=True)
        self.assertEqual(res_hamza['total_count'], 1)
        self.assertEqual(res_hamza['results'][0]['topic'].pk, self.topic2.pk)

    def test_unified_views_and_permissions(self):
        """Both /search/ and /search/person/ render properly and enforce permissions."""
        self.client.login(username='search_admin', password='password123')
        resp = self.client.get(reverse('search_engine:search') + '?q=فائزة+المسني')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('ترقية أعضاء هيئة التدريس', html)
        self.assertIn('المحاسبة', html)

        # Legacy /search/person/?name=... also works seamlessly
        resp_person = self.client.get(reverse('search_engine:person-search') + '?name=د.+نبيلة')
        self.assertEqual(resp_person.status_code, 200)
        html_person = resp_person.content.decode('utf-8')
        self.assertIn('تعيين', html_person)
        self.assertIn('إقرار تعيين', html_person)
