from django.core.management.base import BaseCommand
from datetime import date, time
from accounts.models import User, CouncilPermission
from council.models import CouncilSession, Attendance, Topic, Vote, Decision


class Command(BaseCommand):
    help = 'بناء وتحديث البيانات الأولية التجريبية لنظام إدارة مجلس الجامعة'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.NOTICE('بدء تحديث وبناء البيانات التجريبية...'))

        # 1. Super Admin (مدير النظام الأعلى)
        admin, _ = User.objects.get_or_create(
            username='admin',
            defaults={
                'full_name': 'مدير النظام الأعلى',
                'title': 'مدير_النظام',
                'department': 'مركز تقنية المعلومات والحاسوب',
                'email': 'admin@univ.edu',
                'is_super': True,
                'is_staff': True,
                'is_superuser': True,
            }
        )
        admin.set_password('admin123')
        admin.full_name = 'مدير النظام الأعلى'
        admin.title = 'مدير_النظام'
        admin.department = 'مركز تقنية المعلومات والحاسوب'
        admin.is_super = True
        admin.save()
        self.stdout.write(self.style.SUCCESS('تم إعداد السوبر أدمن (مدير النظام الأعلى): admin / admin123'))

        # 2. General Director of Council Affairs (مدير عام الإدارة العامة المساعدة لشؤون المجلس)
        director, _ = User.objects.get_or_create(
            username='director_affairs',
            defaults={
                'full_name': 'د. رضوان القباطي',
                'title': 'مدير_عام_المساعدة',
                'department': 'الإدارة العامة المساعدة لشؤون المجلس',
                'email': 'director.affairs@univ.edu',
            }
        )
        director.set_password('123456')
        director.title = 'مدير_عام_المساعدة'
        director.save()

        # Permissions for Director: Broad department management + permission delegation to subordinates
        perm_dir, _ = CouncilPermission.objects.get_or_create(user=director)
        perm_dir.can_add_session = True
        perm_dir.can_edit_session = True
        perm_dir.can_manage_attendance = True
        perm_dir.can_export_minutes = True
        perm_dir.can_add_topic = True
        perm_dir.can_edit_topic = True
        perm_dir.can_import_topics = True
        perm_dir.can_upload_attachments = True
        perm_dir.can_record_audio = True
        perm_dir.can_manage_users = True
        perm_dir.can_import_members = True
        perm_dir.can_grant_permissions = True  # Can grant permissions to his staff
        perm_dir.granted_by = admin
        perm_dir.notes = 'تخويل من السوبر أدمن بإدارة شؤون المجلس وتخويل موظفي الإدارة المساعدة'
        perm_dir.save()

        # 3. Staff members of Council Affairs (موظفو الإدارة المساعدة)
        staff_dataentry, _ = User.objects.get_or_create(
            username='staff_dataentry',
            defaults={
                'full_name': 'أ. مروان الحمادي',
                'title': 'موظف_المساعدة',
                'department': 'الإدارة العامة المساعدة لشؤون المجلس',
                'manager': director,
                'email': 'marwan@univ.edu',
            }
        )
        staff_dataentry.set_password('123456')
        staff_dataentry.manager = director
        staff_dataentry.save()

        # Staff 1 permissions: Data entry for topics & members
        perm_s1, _ = CouncilPermission.objects.get_or_create(user=staff_dataentry)
        perm_s1.can_add_topic = True
        perm_s1.can_edit_topic = True
        perm_s1.can_import_topics = True
        perm_s1.can_manage_users = True
        perm_s1.can_import_members = True
        perm_s1.granted_by = director
        perm_s1.notes = 'مفوّض من المدير العام بإدخال بيانات واستيراد الأعضاء والموضوعات'
        perm_s1.save()

        staff_scanner, _ = User.objects.get_or_create(
            username='staff_scanner',
            defaults={
                'full_name': 'أ. إبراهيم العبسي',
                'title': 'موظف_المساعدة',
                'department': 'الإدارة العامة المساعدة لشؤون المجلس',
                'manager': director,
                'email': 'ibrahim@univ.edu',
            }
        )
        staff_scanner.set_password('123456')
        staff_scanner.manager = director
        staff_scanner.save()

        # Staff 2 permissions: Scanner attachments and audio recordings in hall
        perm_s2, _ = CouncilPermission.objects.get_or_create(user=staff_scanner)
        perm_s2.can_upload_attachments = True
        perm_s2.can_delete_attachments = True
        perm_s2.can_record_audio = True
        perm_s2.can_manage_attendance = True
        perm_s2.granted_by = director
        perm_s2.notes = 'مفوّض من المدير العام بسحب أوليات الإسكانر والتسجيل الصوتي بالقاعة'
        perm_s2.save()

        # 4. Council Members (رئيس الجامعة، الأمين العام، الأمين العام المساعد، النواب، العمداء، المستشارون)
        members_data = [
            {
                'username': 'president',
                'full_name': 'أ.د. رئيس الجامعة',
                'title': 'رئيس_الجامعة',
                'department': 'رئاسة الجامعة',
                'perms': {'can_vote': True, 'can_view_vote_details': True, 'can_draft_decision': True, 'can_export_minutes': True},
            },
            {
                'username': 'secretary',
                'full_name': 'د. عبدالله الشامي',
                'title': 'امين_عام',
                'department': 'الأمانة العامة للجامعة',
                'perms': {'can_vote': True, 'can_view_vote_details': True, 'can_draft_decision': True, 'can_delete_decision': True, 'can_export_minutes': True},
            },
            {
                'username': 'asst_secretary',
                'full_name': 'د. صادق الشميري',
                'title': 'امين_عام_مساعد',
                'department': 'الأمانة العامة للجامعة',
                'perms': {'can_vote': True, 'can_view_vote_details': True, 'can_draft_decision': True, 'can_export_minutes': True},
            },
            {
                'username': 'vice_academic',
                'full_name': 'أ.د. عبدالكريم القاسمي',
                'title': 'نائب_رئيس',
                'department': 'نيابة رئاسة الجامعة للشؤون الأكاديمية',
                'perms': {'can_vote': True, 'can_view_vote_details': True},
            },
            {
                'username': 'dean_engineering',
                'full_name': 'أ.د. محمد طاهر',
                'title': 'عميد',
                'department': 'كلية الهندسة وتكنولوجيا المعلومات',
                'perms': {'can_vote': True, 'can_view_vote_details': True},
            },
            {
                'username': 'dean_medicine',
                'full_name': 'أ.د. نجوى الحكيمي',
                'title': 'عميد',
                'department': 'كلية الطب والعلوم الصحية',
                'perms': {'can_vote': True, 'can_view_vote_details': True},
            },
            {
                'username': 'advisor',
                'full_name': 'د. طارق الحبيشي',
                'title': 'مستشار',
                'department': 'مستشار رئيس الجامعة للشؤون القانونية',
                'perms': {'can_vote': True, 'can_view_vote_details': True},
            },
        ]

        created_members = {}
        for minfo in members_data:
            m, _ = User.objects.get_or_create(
                username=minfo['username'],
                defaults={
                    'full_name': minfo['full_name'],
                    'title': minfo['title'],
                    'department': minfo['department'],
                    'email': f"{minfo['username']}@univ.edu",
                }
            )
            m.set_password('123456')
            m.title = minfo['title']
            m.department = minfo['department']
            m.save()
            created_members[minfo['username']] = m

            perm, _ = CouncilPermission.objects.get_or_create(user=m)
            # Reset and set explicit
            for field in [f.name for f in CouncilPermission._meta.fields if f.name.startswith('can_')]:
                setattr(perm, field, False)
            for p_k, p_v in minfo['perms'].items():
                setattr(perm, p_k, p_v)
            perm.granted_by = admin
            perm.notes = 'تخويل رسمي من السوبر أدمن بمهام عضوية المجلس'
            perm.save()

        self.stdout.write(self.style.SUCCESS('تم تجهيز كافة المستخدمين وأعضاء المجلس والهيكل الهرمي للإدارة المساعدة.'))

        # 5. Council Session & Sample Topics
        session, _ = CouncilSession.objects.get_or_create(
            session_number=1,
            defaults={
                'title': 'الدورة الاعتيادية الأولى لمجلس الجامعة للعام الأكاديمي 2025-2026',
                'date': date.today(),
                'time': time(9, 30),
                'location': 'قاعة اجتماعات رئاسة الجامعة الكبرى',
                'academic_year': '2025-2026',
                'status': 'active',
                'agenda_notes': 'مناقشة الترقيات الأكاديمية واستحداث برامج الدراسات العليا واعتماد لوائح شؤون الطلاب.',
                'created_by': admin,
            }
        )

        for u in User.objects.filter(is_active=True):
            Attendance.objects.get_or_create(
                session=session,
                member=u,
                defaults={'status': 'present', 'notes': 'حضور الجلسة'}
            )

        self.stdout.write(self.style.SUCCESS('تم اكتمال تحديث البيانات الأولية بنجاح تام! 🚀'))
