import json
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User, CouncilPermission
from council.models import (
    CouncilSession, Topic, Attendance, SessionStageLog, NewSessionRequest,
    AuditLog, BackupLog, EntitySeat, SessionReadReceipt, Vote,
    SignedDecisionAttachment, SignedDecisionDispatch,
    InAppNotification, NotificationLog, SMSTemplate,
    SmartReaderSetting, SmartReaderLog
)


class Phase1LifecycleAndProtectionTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Super Admin
        self.superadmin = User.objects.create_user(
            username='super_admin',
            password='password123',
            full_name='المسؤول العام',
            title='مدير_النظام',
            is_super=True
        )

        # Secretary with advance & reopen permissions
        self.secretary = User.objects.create_user(
            username='secretary_user',
            password='password123',
            full_name='أمين عام المجلس',
            title='امين_عام',
            is_super=False
        )
        CouncilPermission.objects.create(
            user=self.secretary,
            can_add_session=True,
            can_edit_session=True,
            can_advance_session_stage=True,
            can_reopen_frozen_session=True,
            can_approve_new_session=True,
            can_view_audit_log=True,
        )

        # Regular Member (Zero lifecycle perms)
        self.member = User.objects.create_user(
            username='regular_member',
            password='password123',
            full_name='عضو المجلس',
            title='عميد',
            is_super=False
        )
        CouncilPermission.objects.create(
            user=self.member,
            can_vote=True,
        )

        # Data Entry Staff
        self.staff = User.objects.create_user(
            username='data_entry_staff',
            password='password123',
            full_name='مدخل البيانات',
            title='موظف_المساعدة',
            is_super=False
        )
        CouncilPermission.objects.create(
            user=self.staff,
            can_add_session=True,
            can_edit_session=True,
            can_add_topic=True,
        )

    def test_draft_session_visibility(self):
        """Draft session is hidden from regular members, visible to superadmin and stage managers."""
        session = CouncilSession.objects.create(
            session_number=101,
            title='جلسة تحضيرية مسودة',
            date=timezone.localdate(),
            status='draft',
            created_by=self.superadmin
        )

        # 1. Regular member cannot access detail
        self.client.login(username='regular_member', password='password123')
        resp = self.client.get(reverse('council:session_detail', args=[session.pk]))
        self.assertRedirects(resp, reverse('council:session_list'))

        # 2. Regular member does not see it in list
        resp_list = self.client.get(reverse('council:session_list'))
        self.assertNotIn('جلسة تحضيرية مسودة', resp_list.content.decode('utf-8'))
        self.client.logout()

        # 3. Secretary with can_advance_session_stage CAN access detail
        self.client.login(username='secretary_user', password='password123')
        resp_sec = self.client.get(reverse('council:session_detail', args=[session.pk]))
        self.assertEqual(resp_sec.status_code, 200)
        self.assertIn('جلسة تحضيرية مسودة', resp_sec.content.decode('utf-8'))
        self.client.logout()

    def test_lifecycle_stage_advancement(self):
        """Session correctly advances through 5 stages and records stage logs & audit."""
        session = CouncilSession.objects.create(
            session_number=102,
            title='جلسة التطوير',
            date=timezone.localdate(),
            status='draft',
            created_by=self.superadmin
        )

        self.client.login(username='secretary_user', password='password123')

        # Advance: draft -> publishing
        resp = self.client.post(reverse('council:session_advance_stage', args=[session.pk]), {'reason': 'جاهزة للاطلاع'})
        self.assertRedirects(resp, reverse('council:session_detail', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.status, 'publishing')

        # Advance: publishing -> active
        self.client.post(reverse('council:session_advance_stage', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.status, 'active')

        # Advance: active -> partial_close
        self.client.post(reverse('council:session_advance_stage', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.status, 'partial_close')

        # Advance: partial_close -> frozen
        self.client.post(reverse('council:session_advance_stage', args=[session.pk]), {'reason': 'اعتماد المحضر النهائي وتجميده'})
        session.refresh_from_db()
        self.assertEqual(session.status, 'frozen')
        self.assertTrue(session.is_frozen())
        self.assertIsNotNone(session.frozen_at)

        # Check stage logs count
        self.assertEqual(session.stage_logs.count(), 4)

    def test_frozen_session_protection(self):
        """Frozen session blocks edits and modifications via UI and Middleware."""
        session = CouncilSession.objects.create(
            session_number=103,
            title='جلسة مجمّدة تماماً',
            date=timezone.localdate(),
            status='frozen',
            created_by=self.superadmin
        )

        self.client.login(username='super_admin', password='password123')

        # Attempt to edit session
        resp_edit = self.client.post(reverse('council:session_edit', args=[session.pk]), {
            'session_number': 103,
            'title': 'محاولة تعديل عنوان',
            'date': timezone.localdate(),
        })
        self.assertRedirects(resp_edit, reverse('council:session_detail', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.title, 'جلسة مجمّدة تماماً')  # Unchanged

    def test_reopen_frozen_session_with_password(self):
        """Reopening a frozen session requires valid password and returns status to partial_close."""
        session = CouncilSession.objects.create(
            session_number=104,
            title='جلسة للتجربة',
            date=timezone.localdate(),
            status='frozen',
            created_by=self.superadmin
        )

        self.client.login(username='secretary_user', password='password123')

        # 1. Reopen with wrong password -> Fails
        resp_fail = self.client.post(reverse('council:session_reopen', args=[session.pk]), {
            'password': 'wrong_password',
            'reason': 'تعديل فقرة في قرار',
        })
        self.assertRedirects(resp_fail, reverse('council:session_detail', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.status, 'frozen')

        # 2. Reopen with correct password -> Success
        resp_ok = self.client.post(reverse('council:session_reopen', args=[session.pk]), {
            'password': 'password123',
            'reason': 'إعادة فتح لإجراء تعديل رسمي معتمد',
        })
        self.assertRedirects(resp_ok, reverse('council:session_detail', args=[session.pk]))
        session.refresh_from_db()
        self.assertEqual(session.status, 'partial_close')
        self.assertFalse(session.is_frozen())
        self.assertEqual(session.reopen_reason, 'إعادة فتح لإجراء تعديل رسمي معتمد')

    def test_previous_session_gating(self):
        """Non-approver user cannot create a new session if previous session is not frozen without approval."""
        # Create an un-frozen session
        CouncilSession.objects.create(
            session_number=105,
            title='جلسة غير مجمّدة',
            date=timezone.localdate(),
            status='active',
            created_by=self.superadmin
        )

        self.client.login(username='data_entry_staff', password='password123')

        # GET session create renders the request form instead
        resp = self.client.get(reverse('council:session_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('الجلسة السابقة رقم 105 لم تُجمَّد بعد', resp.content.decode('utf-8'))

        # Submit request
        resp_req = self.client.post(reverse('council:session_create'), {
            'request_reason': 'الحاجة للتحضير المبكر للجلسة القادمة',
        })
        self.assertRedirects(resp_req, reverse('council:session_list'))
        req_obj = NewSessionRequest.objects.filter(requested_by=self.staff).first()
        self.assertIsNotNone(req_obj)
        self.assertEqual(req_obj.status, 'pending')
        self.client.logout()

        # Secretary approves the request
        self.client.login(username='secretary_user', password='password123')
        resp_approve = self.client.post(reverse('council:new_session_request_review', args=[req_obj.pk]), {
            'decision': 'approve',
            'review_notes': 'موافق على البدء بالتحضير',
        })
        self.assertRedirects(resp_approve, reverse('council:session_list'))
        req_obj.refresh_from_db()
        self.assertEqual(req_obj.status, 'approved')
        self.client.logout()

        # Staff can now proceed and create the session
        self.client.login(username='data_entry_staff', password='password123')
        resp_new = self.client.post(reverse('council:session_create'), {
            'session_number': 106,
            'title': 'الجلسة الجديدة المصرح بها',
            'date': timezone.localdate(),
            'status': 'draft',
        })
        created_session = CouncilSession.objects.filter(session_number=106).first()
        self.assertIsNotNone(created_session)
        self.assertRedirects(resp_new, reverse('council:session_detail', args=[created_session.pk]))
        req_obj.refresh_from_db()
        self.assertTrue(req_obj.used)


class Phase2EntityAndAttendanceTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Primary Rep (Dean)
        self.dean = User.objects.create_user(
            username='dean_medicine',
            password='password123',
            full_name='أ.د. محمد الشهاري',
            title='عميد',
            department='كلية الطب والعلوم الصحية',
            order=13,
            is_active=True
        )
        CouncilPermission.objects.create(
            user=self.dean,
            can_vote=True,
        )

        # Deputy 1
        self.vice_dean = User.objects.create_user(
            username='vice_dean_med',
            password='password123',
            full_name='د. أحمد العريقي',
            title='نائب_عميد',
            department='كلية الطب والعلوم الصحية',
            order=13,
            is_active=True
        )
        CouncilPermission.objects.create(
            user=self.vice_dean,
            can_vote=True,
        )

        # Other Member (Engineering Dean)
        self.dean_eng = User.objects.create_user(
            username='dean_eng',
            password='password123',
            full_name='د. عادل صالح راوع',
            title='عميد',
            department='كلية الهندسة',
            order=14,
            is_active=True
        )
        CouncilPermission.objects.create(
            user=self.dean_eng,
            can_vote=True,
        )

        # Entity Seat for Medicine
        self.med_seat = EntitySeat.objects.create(
            name='كلية الطب والعلوم الصحية',
            seat_type='faculty',
            order=13,
            primary_rep=self.dean,
            deputy_rep_1=self.vice_dean,
            is_active=True
        )

        # Entity Seat for Engineering
        self.eng_seat = EntitySeat.objects.create(
            name='كلية الهندسة',
            seat_type='faculty',
            order=14,
            primary_rep=self.dean_eng,
            is_active=True
        )

    def test_entity_seat_representatives_mapping(self):
        """Verify seat correctly lists primary and proxy reps with proper metadata."""
        reps = self.med_seat.get_representatives()
        self.assertEqual(len(reps), 2)
        self.assertEqual(reps[0]['username'], 'dean_medicine')
        self.assertTrue(reps[0]['is_primary'])
        self.assertEqual(reps[0]['role_label'], 'أصيل (الممثل الأول)')

        self.assertEqual(reps[1]['username'], 'vice_dean_med')
        self.assertFalse(reps[1]['is_primary'])
        self.assertEqual(reps[1]['role_label'], 'إنابة (الممثل الثاني)')

        self.assertTrue(self.med_seat.has_user(self.dean))
        self.assertTrue(self.med_seat.has_user(self.vice_dean))
        self.assertFalse(self.med_seat.has_user(self.dean_eng))

    def test_entity_login_with_modal_and_password(self):
        """Test entity login with user selection and personal password authentication."""
        # 1. Invalid password fails
        resp_fail = self.client.post(reverse('accounts:login'), {
            'login_type': 'entity',
            'seat_id': self.med_seat.pk,
            'user_id': self.dean.pk,
            'password': 'wrong_password',
        })
        self.assertContains(resp_fail, 'كلمة المرور الشخصية غير صحيحة')
        self.assertNotIn('_auth_user_id', self.client.session)

        # 2. Correct password logs in successfully
        resp_ok = self.client.post(reverse('accounts:login'), {
            'login_type': 'entity',
            'seat_id': self.med_seat.pk,
            'user_id': self.dean.pk,
            'password': 'password123',
        })
        self.assertRedirects(resp_ok, reverse('accounts:dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.dean.pk)
        self.client.logout()

    def test_auto_attendance_on_login(self):
        """Test that logging in automatically records attendance and distinguishes primary vs deputy."""
        session = CouncilSession.objects.create(
            session_number=201,
            title='جلسة الانعقاد الفعلي',
            date=timezone.localdate(),
            status='active',
        )

        # Dean logs in -> marked present_primary
        self.client.post(reverse('accounts:login'), {
            'login_type': 'entity',
            'seat_id': self.med_seat.pk,
            'user_id': self.dean.pk,
            'password': 'password123',
        })
        self.client.logout()

        att = Attendance.objects.filter(session=session, member=self.dean).first()
        self.assertIsNotNone(att)
        self.assertEqual(att.status, 'present_primary')
        self.assertFalse(att.is_proxy)
        self.assertTrue(att.auto_registered)

        # Vice Dean logs in for Engineering seat test
        self.eng_seat.deputy_rep_1 = self.vice_dean
        self.eng_seat.save()

        self.client.post(reverse('accounts:login'), {
            'login_type': 'entity',
            'seat_id': self.eng_seat.pk,
            'user_id': self.vice_dean.pk,
            'password': 'password123',
        })
        self.client.logout()

        att_eng = Attendance.objects.filter(session=session, member=self.dean_eng).first()
        self.assertIsNotNone(att_eng)
        self.assertEqual(att_eng.status, 'present_deputy')
        self.assertTrue(att_eng.is_proxy)
        self.assertEqual(att_eng.proxy_user, self.vice_dean)

    def test_read_receipt_on_login_during_publishing(self):
        """Test recording read receipt (مقترح 1) when logging in while session is in publishing stage."""
        from council.models import SessionReadReceipt
        pub_session = CouncilSession.objects.create(
            session_number=202,
            title='جلسة منشورة للاطلاع',
            date=timezone.localdate(),
            status='publishing',
        )

        self.client.post(reverse('accounts:login'), {
            'login_type': 'entity',
            'seat_id': self.med_seat.pk,
            'user_id': self.dean.pk,
            'password': 'password123',
        })
        self.client.logout()

        receipt = SessionReadReceipt.objects.filter(session=pub_session, member=self.dean).first()
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.seat, self.med_seat)

    def test_single_vote_per_seat_integrity(self):
        """Verify that a seat cannot cast multiple votes on the same topic (منع ازدواجية التصويت)."""
        from council.models import Vote
        session = CouncilSession.objects.create(
            session_number=203,
            title='جلسة تصويت',
            date=timezone.localdate(),
            status='active',
        )
        topic = Topic.objects.create(
            session=session,
            category='general',
            order_number=1,
            title='مشروع اللائحة الأكاديمية الجديدة',
            status='pending',
        )

        # 1. Dean votes 'approve' -> OK
        self.client.login(username='dean_medicine', password='password123')
        resp_vote1 = self.client.post(
            reverse('council:topic_vote', args=[topic.pk]),
            {'choice': 'approve', 'notes': 'موافق تماماً'}
        )
        self.assertEqual(resp_vote1.status_code, 200)
        self.assertTrue(resp_vote1.json()['ok'])
        self.client.logout()

        # 2. Deputy from the SAME seat attempts to vote on the same topic -> blocked
        self.client.login(username='vice_dean_med', password='password123')
        resp_vote2 = self.client.post(
            reverse('council:topic_vote', args=[topic.pk]),
            {'choice': 'reject', 'notes': 'أنا معترض'}
        )
        self.assertEqual(resp_vote2.status_code, 403)
        self.assertFalse(resp_vote2.json()['ok'])
        self.assertIn('تم تسجيل تصويت هذا المقعد', resp_vote2.json()['error'])
        self.client.logout()

        # 3. Only 1 vote exists for this topic
        self.assertEqual(Vote.objects.filter(topic=topic).count(), 1)

    def test_seat_deputies_management_view(self):
        """Primary representative can view and manage their seat deputies."""
        self.client.login(username='dean_medicine', password='password123')

        # 1. GET page
        resp_get = self.client.get(reverse('accounts:seat_deputies'))
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn('كلية الطب والعلوم الصحية', resp_get.content.decode('utf-8'))

        # 2. Create new deputy via quick form
        resp_create = self.client.post(reverse('accounts:seat_deputies'), {
            'action': 'create_deputy',
            'seat_id': self.med_seat.pk,
            'full_name': 'د. سامي العبسي',
            'username': 'sami_absi',
            'password': 'password123',
            'official_title': 'نائب العميد لشؤون الجودة',
            'slot': '2',
        })
        self.assertRedirects(resp_create, f'/seats/deputies/?seat_id={self.med_seat.pk}')
        self.med_seat.refresh_from_db()
        self.assertIsNotNone(self.med_seat.deputy_rep_2)
        self.assertEqual(self.med_seat.deputy_rep_2.username, 'sami_absi')
        self.client.logout()


class Phase3LiveSessionTests(TestCase):
    def setUp(self):
        self.client = Client()

        # President
        self.president = User.objects.create_user(
            username='pre-sanaa',
            password='password123',
            full_name='أ.د. محمد أحمد البخيتي',
            title='رئيس_الجامعة',
            is_active=True
        )

        # Secretary General
        self.secretary = User.objects.create_user(
            username='eskander_maqaleh',
            password='password123',
            full_name='أ. إسكندر عبده محمد المقالح',
            title='امين_عام',
            is_active=True
        )

        # Member (Dean)
        self.dean = User.objects.create_user(
            username='dean_eng',
            password='password123',
            full_name='د. عادل صالح راوع',
            title='عميد',
            is_active=True
        )

        # Seat
        self.seat_eng = EntitySeat.objects.create(
            name='كلية الهندسة',
            seat_type='faculty',
            order=14,
            primary_rep=self.dean,
            is_active=True
        )

        # Permissions
        CouncilPermission.objects.create(
            user=self.dean,
            can_vote=True
        )
        CouncilPermission.objects.create(
            user=self.president,
            can_add_session=True,
            can_edit_session=True,
            can_advance_session_stage=True,
            can_vote=True
        )

        # Active Session
        self.session = CouncilSession.objects.create(
            session_number=301,
            title='جلسة حية تفاعلية',
            date=timezone.localdate(),
            status='active',
            created_by=self.president
        )

        # Attendance for dean
        Attendance.objects.create(
            session=self.session,
            member=self.dean,
            seat=self.seat_eng,
            status='present_primary',
            member_title_snapshot='عميد كلية الهندسة'
        )

        # Topic
        self.topic = Topic.objects.create(
            session=self.session,
            category='academic',
            order_number=1,
            title='إنشاء برنامج الذكاء الاصطناعي وهندسة البيانات',
            background='حيثيات مقدمة من عمادة كلية الهندسة والحاسوب',
            status='pending'
        )

    def test_topic_display_state_control_and_voting_gate(self):
        """Test topic display transitions: hidden -> shown -> voting -> closed, and voting gatekeeping."""
        state = self.topic.get_display_state()
        self.assertEqual(state.display_status, 'hidden')

        # 1. Dean attempts to vote while topic is hidden -> 403 blocked
        self.client.login(username='dean_eng', password='password123')
        resp_v1 = self.client.post(
            reverse('council:topic_vote', args=[self.topic.pk]),
            {'choice': 'approve'}
        )
        self.assertEqual(resp_v1.status_code, 403)
        self.assertIn('باب التصويت على هذا الموضوع مغلق', resp_v1.json()['error'])

        # 2. President shows topic for discussion (without voting)
        self.client.login(username='pre-sanaa', password='password123')
        resp_show = self.client.post(
            reverse('council:api_topic_control', args=[self.topic.pk]),
            json.dumps({'action': 'show'}),
            content_type='application/json'
        )
        self.assertEqual(resp_show.status_code, 200)
        self.assertEqual(resp_show.json()['display_status'], 'shown')

        # 3. Dean still cannot vote while 'shown' (discussion only)
        self.client.login(username='dean_eng', password='password123')
        resp_v2 = self.client.post(
            reverse('council:topic_vote', args=[self.topic.pk]),
            {'choice': 'approve'}
        )
        self.assertEqual(resp_v2.status_code, 403)

        # 4. President opens voting
        self.client.login(username='pre-sanaa', password='password123')
        resp_open = self.client.post(
            reverse('council:api_topic_control', args=[self.topic.pk]),
            json.dumps({'action': 'open_voting'}),
            content_type='application/json'
        )
        self.assertEqual(resp_open.status_code, 200)
        self.assertTrue(resp_open.json()['is_voting_open'])

        # 5. Dean votes -> Success
        self.client.login(username='dean_eng', password='password123')
        resp_v3 = self.client.post(
            reverse('council:topic_vote', args=[self.topic.pk]),
            {'choice': 'approve', 'notes': 'برنامج حيوي ومطلوب'}
        )
        self.assertEqual(resp_v3.status_code, 200)
        self.assertTrue(resp_v3.json()['ok'])

        # 6. President closes voting
        self.client.login(username='pre-sanaa', password='password123')
        resp_close = self.client.post(
            reverse('council:api_topic_control', args=[self.topic.pk]),
            json.dumps({'action': 'close_voting'}),
            content_type='application/json'
        )
        self.assertEqual(resp_close.status_code, 200)
        self.assertEqual(resp_close.json()['display_status'], 'closed')
        self.assertEqual(resp_close.json()['summary']['approve'], 1)

    def test_countdown_timer_allocated_minutes(self):
        """President can set and stop timer on topic."""
        self.client.login(username='pre-sanaa', password='password123')
        resp_t = self.client.post(
            reverse('council:api_topic_control', args=[self.topic.pk]),
            json.dumps({'action': 'set_timer', 'minutes': 8}),
            content_type='application/json'
        )
        self.assertEqual(resp_t.status_code, 200)
        self.assertEqual(resp_t.json()['allocated_minutes'], 8)
        self.assertGreater(resp_t.json()['remaining_seconds'], 0)

        # Stop timer
        resp_stop = self.client.post(
            reverse('council:api_topic_control', args=[self.topic.pk]),
            json.dumps({'action': 'stop_timer'}),
            content_type='application/json'
        )
        self.assertEqual(resp_stop.status_code, 200)
        self.assertEqual(resp_stop.json()['allocated_minutes'], 0)

    def test_speech_queue_lifecycle_and_offsets(self):
        """Test speak request creation, allowing floor, and completing speech."""
        # Dean requests speech
        self.client.login(username='dean_eng', password='password123')
        resp_req = self.client.post(reverse('council:api_speak_request_toggle', args=[self.session.pk]))
        self.assertEqual(resp_req.status_code, 200)
        self.assertEqual(resp_req.json()['action'], 'requested')
        req_id = resp_req.json()['request_id']

        # Queue API reflects pending request
        resp_q = self.client.get(reverse('council:api_speak_queue', args=[self.session.pk]))
        self.assertEqual(resp_q.status_code, 200)
        self.assertEqual(resp_q.json()['pending_count'], 1)

        # President grants floor
        self.client.login(username='pre-sanaa', password='password123')
        resp_allow = self.client.post(
            reverse('council:api_speak_request_action', args=[req_id]),
            json.dumps({'action': 'allow'}),
            content_type='application/json'
        )
        self.assertEqual(resp_allow.status_code, 200)
        self.assertEqual(resp_allow.json()['status'], 'speaking')

        # Active speaker in queue
        resp_q2 = self.client.get(reverse('council:api_speak_queue', args=[self.session.pk]))
        self.assertIsNotNone(resp_q2.json()['active_speaker'])
        self.assertEqual(resp_q2.json()['active_speaker']['name'], 'د. عادل صالح راوع')

        # President completes speech
        resp_comp = self.client.post(
            reverse('council:api_speak_request_action', args=[req_id]),
            json.dumps({'action': 'complete'}),
            content_type='application/json'
        )
        self.assertEqual(resp_comp.status_code, 200)
        self.assertEqual(resp_comp.json()['status'], 'completed')

    def test_session_continuous_recording_and_chunks(self):
        """Test continuous session recording controls and chunk upload."""
        self.client.login(username='pre-sanaa', password='password123')

        # 1. Start recording
        resp_rec = self.client.post(
            reverse('council:api_session_recording_action', args=[self.session.pk]),
            json.dumps({'action': 'start'}),
            content_type='application/json'
        )
        self.assertEqual(resp_rec.status_code, 200)
        self.assertTrue(resp_rec.json()['is_recording'])

        # 2. Upload chunk
        from django.core.files.uploadedfile import SimpleUploadedFile
        audio_blob = SimpleUploadedFile("chunk_01.webm", b"RIFFfakeaudiodata", content_type="audio/webm")
        resp_chunk = self.client.post(
            reverse('council:api_session_recording_chunk', args=[self.session.pk]),
            {'audio_chunk': audio_blob, 'duration_seconds': '30'}
        )
        self.assertEqual(resp_chunk.status_code, 200)
        self.assertEqual(resp_chunk.json()['chunk_count'], 1)

        # 3. Pause and Resume
        resp_pause = self.client.post(
            reverse('council:api_session_recording_action', args=[self.session.pk]),
            json.dumps({'action': 'pause'}),
            content_type='application/json'
        )
        self.assertTrue(resp_pause.json()['is_paused'])

        resp_resume = self.client.post(
            reverse('council:api_session_recording_action', args=[self.session.pk]),
            json.dumps({'action': 'resume'}),
            content_type='application/json'
        )
        self.assertFalse(resp_resume.json()['is_paused'])

        # 4. Stop recording
        resp_stop = self.client.post(
            reverse('council:api_session_recording_action', args=[self.session.pk]),
            json.dumps({'action': 'stop'}),
            content_type='application/json'
        )
        self.assertEqual(resp_stop.status_code, 200)
        self.assertFalse(resp_stop.json()['is_recording'])

    def test_exit_permit_lifecycle_and_voting_block(self):
        """Test member submitting exit permit, approval, and subsequent voting blockage."""
        # 1. Dean requests exit permit
        self.client.login(username='dean_eng', password='password123')
        resp_req = self.client.post(
            reverse('council:api_exit_permit_request', args=[self.session.pk]),
            {'reason': 'ارتباط رسمي عاجل برئاسة الوزراء'}
        )
        self.assertEqual(resp_req.status_code, 200)
        permit_id = resp_req.json()['permit_id']

        # 2. President reviews and approves
        self.client.login(username='pre-sanaa', password='password123')
        resp_app = self.client.post(
            reverse('council:api_exit_permit_action', args=[permit_id]),
            json.dumps({'action': 'approve'}),
            content_type='application/json'
        )
        self.assertEqual(resp_app.status_code, 200)
        self.assertEqual(resp_app.json()['status'], 'approved')

        # 3. Topic has voting opened
        state = self.topic.get_display_state()
        state.display_status = 'voting'
        state.save()

        # 4. Departed dean attempts to vote -> blocked (403)
        self.client.login(username='dean_eng', password='password123')
        resp_v = self.client.post(
            reverse('council:topic_vote', args=[self.topic.pk]),
            {'choice': 'approve'}
        )
        self.assertEqual(resp_v.status_code, 403)
        self.assertIn('تمت الموافقة على مغادرتك للجلسة مسبقاً', resp_v.json()['error'])

    def test_quorum_calculation_half_plus_one(self):
        """Legal Quorum rule: (active_seats // 2) + 1."""
        # Clear existing seats for pure calculation test
        EntitySeat.objects.all().delete()
        for i in range(1, 32):
            EntitySeat.objects.create(name=f'مقعد جهة {i}', order=i, is_active=True)

        q_info = self.session.get_quorum_info()
        self.assertEqual(q_info['total_seats'], 31)
        self.assertEqual(q_info['quorum_required'], 16) # (31 // 2) + 1 = 16
        self.assertFalse(q_info['is_achieved'])

    def test_live_session_views_render(self):
        """Test GET live session cockpit, projector mode, and analytics views return 200 OK."""
        self.client.login(username='pre-sanaa', password='password123')

        # 1. Live cockpit
        resp_live = self.client.get(reverse('council:session_live', args=[self.session.pk]))
        self.assertEqual(resp_live.status_code, 200)
        self.assertIn('غرفة إدارة الجلسة الحية', resp_live.content.decode('utf-8'))

        # 2. Projector
        resp_proj = self.client.get(reverse('council:session_projector', args=[self.session.pk]))
        self.assertEqual(resp_proj.status_code, 200)
        self.assertIn('شاشة العرض بالقاعة', resp_proj.content.decode('utf-8'))

        # 3. Analytics
        resp_ana = self.client.get(reverse('council:session_analytics', args=[self.session.pk]))
        self.assertEqual(resp_ana.status_code, 200)
        self.assertIn('التقرير التحليلي الشامل', resp_ana.content.decode('utf-8'))


class Phase4DecisionDispatchTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Superadmin / President
        self.superadmin = User.objects.create_user(
            username='admin_phase4',
            password='password123',
            full_name='أ.د. رئيس الجامعة',
            title='رئيس_الجامعة',
            is_super=True
        )

        # Secretary with dispatch management permissions
        self.secretary = User.objects.create_user(
            username='sec_phase4',
            password='password123',
            full_name='أمين عام المجلس',
            title='امين_عام',
            is_super=False
        )
        CouncilPermission.objects.create(
            user=self.secretary,
            can_add_session=True,
            can_edit_session=True,
            can_draft_decision=True,
            can_send_decisions=True,
            can_advance_session_stage=True,
            can_view_dispatch_log=True,
        )

        # Dean of Medicine
        self.dean_medicine = User.objects.create_user(
            username='dean_med',
            password='password123',
            full_name='أ.د. عميد كلية الطب',
            title='عميد',
            is_super=False
        )
        self.seat_medicine = EntitySeat.objects.create(
            name='كلية الطب البشري',
            seat_type='faculty',
            order=1,
            is_active=True,
            primary_rep=self.dean_medicine
        )

        # Dean of Engineering
        self.dean_engineering = User.objects.create_user(
            username='dean_eng',
            password='password123',
            full_name='أ.د. عميد كلية الهندسة',
            title='عميد',
            is_super=False
        )
        self.seat_engineering = EntitySeat.objects.create(
            name='كلية الهندسة',
            seat_type='faculty',
            order=2,
            is_active=True,
            primary_rep=self.dean_engineering
        )

        # Dean of Science (Not involved in decision)
        self.dean_science = User.objects.create_user(
            username='dean_sci',
            password='password123',
            full_name='أ.د. عميد كلية العلوم',
            title='عميد',
            is_super=False
        )
        self.seat_science = EntitySeat.objects.create(
            name='كلية العلوم',
            seat_type='faculty',
            order=3,
            is_active=True,
            primary_rep=self.dean_science
        )

        # Session
        self.session = CouncilSession.objects.create(
            session_number=40,
            title='جلسة اعتماد برامج الدراسات العليا واللوائح',
            date=timezone.localdate(),
            status='active',
            created_by=self.superadmin
        )

        # Topic
        self.topic = Topic.objects.create(
            session=self.session,
            title='استحداث برنامج ماجستير التكنولوجيا الحيوية الطبية',
            order_number=1,
            sub_order=1,
            status='approved',
            created_by=self.superadmin
        )
        self.topic.target_seats.add(self.seat_medicine, self.seat_engineering)

    def test_upload_signed_decision_attachment(self):
        """Upload official signed PDF for a topic and assign target seats."""
        self.client.login(username='sec_phase4', password='password123')

        pdf_content = b"%PDF-1.4 simulated official signed decision document"
        uploaded_file = SimpleUploadedFile("decision_40_1.pdf", pdf_content, content_type="application/pdf")

        url = reverse('council:upload_signed_decision', args=[self.topic.pk])
        resp = self.client.post(url, {
            'signed_file': uploaded_file,
            'decision_number': 'ق/2026/40/01',
            'decision_date': '2026-10-06',
            'notes': 'نسخة معتمدة بختم رئيس الجامعة',
            'target_seats': [self.seat_medicine.pk, self.seat_engineering.pk]
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['decision_number'], 'ق/2026/40/01')

        # Check model creation
        attachment = SignedDecisionAttachment.objects.get(topic=self.topic)
        self.assertEqual(attachment.decision_number, 'ق/2026/40/01')
        self.assertEqual(self.topic.target_seats.count(), 2)

    def test_dispatch_signed_decision_and_read_receipt(self):
        """Dispatch signed decision to target seats, and track smart receipt upon opening."""
        # Create attachment first
        attachment = SignedDecisionAttachment.objects.create(
            topic=self.topic,
            session=self.session,
            signed_file=SimpleUploadedFile("signed_doc.pdf", b"pdf content", content_type="application/pdf"),
            decision_number='ق/2026/40/02',
            uploaded_by=self.secretary
        )

        # Secretary dispatches to target seats
        self.client.login(username='sec_phase4', password='password123')
        dispatch_url = reverse('council:dispatch_signed_decision', args=[self.topic.pk])
        resp_dispatch = self.client.post(dispatch_url, {
            'seat_ids': [self.seat_medicine.pk, self.seat_engineering.pk],
            'dispatch_notes': 'يرجى العمل بموجب القرار ابتداءً من الفصل الدراسي القادم'
        })
        self.assertEqual(resp_dispatch.status_code, 200)
        self.assertTrue(resp_dispatch.json()['ok'])
        self.assertEqual(attachment.dispatches.count(), 2)

        # Dean of Medicine views correspondence cockpit
        self.client.login(username='dean_med', password='password123')
        resp_med = self.client.get(reverse('council:entity_correspondence'))
        self.assertEqual(resp_med.status_code, 200)
        self.assertIn('استحداث برنامج ماجستير التكنولوجيا الحيوية', resp_med.content.decode('utf-8'))
        self.assertIn('ق/2026/40/02', resp_med.content.decode('utf-8'))

        # Dean of Medicine downloads/views the file
        med_dispatch = attachment.dispatches.get(seat=self.seat_medicine)
        self.assertFalse(med_dispatch.is_viewed)
        self.assertEqual(med_dispatch.view_count, 0)

        view_url = reverse('council:view_signed_decision_file', args=[med_dispatch.pk])
        resp_file = self.client.get(view_url)
        self.assertEqual(resp_file.status_code, 302)

        # Verify read receipt recorded
        med_dispatch.refresh_from_db()
        self.assertTrue(med_dispatch.is_viewed)
        self.assertEqual(med_dispatch.view_count, 1)
        self.assertEqual(med_dispatch.viewed_by, self.dean_medicine)
        self.assertIsNotNone(med_dispatch.viewed_at)

        # Second download increments counter
        self.client.get(view_url)
        med_dispatch.refresh_from_db()
        self.assertEqual(med_dispatch.view_count, 2)

    def test_correspondence_faculty_isolation(self):
        """Ensure faculties can only see decisions dispatched to them and cannot view other seats."""
        attachment = SignedDecisionAttachment.objects.create(
            topic=self.topic,
            session=self.session,
            signed_file=SimpleUploadedFile("secret_med.pdf", b"pdf content", content_type="application/pdf"),
            decision_number='ق/خاص/طب/01',
            uploaded_by=self.secretary
        )
        SignedDecisionDispatch.objects.create(
            signed_decision=attachment,
            seat=self.seat_medicine,
            sent_by=self.secretary
        )

        # Dean of Science logs in - should see zero decisions
        self.client.login(username='dean_sci', password='password123')
        resp_sci = self.client.get(reverse('council:entity_correspondence'))
        self.assertEqual(resp_sci.status_code, 200)
        self.assertNotIn('ق/خاص/طب/01', resp_sci.content.decode('utf-8'))

        # Dean of Science tries to access Medicine seat's correspondence directly -> redirected
        resp_bypass = self.client.get(reverse('council:entity_correspondence', args=[self.seat_medicine.pk]))
        self.assertRedirects(resp_bypass, reverse('council:session_list'))

    def test_dispatch_log_access_and_filtering(self):
        """Secretary with can_view_dispatch_log can see full dispatch tracking."""
        # Secretary access -> 200
        self.client.login(username='sec_phase4', password='password123')
        resp_log = self.client.get(reverse('council:dispatch_log'))
        self.assertEqual(resp_log.status_code, 200)
        self.assertIn('سجل إرسال وتعميم القرارات الرسمية', resp_log.content.decode('utf-8'))

        # Regular dean without dispatch log permission -> redirected
        self.client.login(username='dean_sci', password='password123')
        resp_unauth = self.client.get(reverse('council:dispatch_log'))
        self.assertRedirects(resp_unauth, reverse('council:session_list'))

    def test_sha256_cryptographic_fingerprint_and_integrity(self):
        """Session SHA-256 hash generation on freeze and tamper detection."""
        # Advance session to frozen
        self.session.status = 'frozen'
        self.session.document_hash = self.session.calculate_document_hash()
        self.session.hashed_at = timezone.now()
        self.session.save()

        # 1. Verify hash length (64 hex characters)
        self.assertEqual(len(self.session.document_hash), 64)

        # 2. Check integrity verification API
        self.client.login(username='sec_phase4', password='password123')
        verify_url = reverse('council:verify_session_hash', args=[self.session.pk])
        resp_verify = self.client.get(verify_url)
        self.assertEqual(resp_verify.status_code, 200)
        data = resp_verify.json()
        self.assertTrue(data['is_valid'])
        self.assertEqual(data['stored_hash'], self.session.document_hash)

        # 3. Simulate unauthorized database tampering on topic title
        self.topic.title = 'تعديل غير مصرح به على نص الموضوع بعد الإغلاق'
        self.topic.save()

        # 4. Check integrity again -> should detect tampering!
        resp_tampered = self.client.get(verify_url)
        self.assertEqual(resp_tampered.status_code, 200)
        tampered_data = resp_tampered.json()
        self.assertFalse(tampered_data['is_valid'])
        self.assertNotEqual(tampered_data['stored_hash'], tampered_data['current_hash'])
        self.assertIn('تنبيه أمني', tampered_data['message'])


class Phase5NotificationAndSMSTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin / President
        self.admin = User.objects.create_user(
            username='admin_phase5',
            password='password123',
            full_name='أ.د. رئيس المجلس',
            title='رئيس_الجامعة',
            is_super=True
        )

        # Secretary with management permissions
        self.secretary = User.objects.create_user(
            username='sec_phase5',
            password='password123',
            full_name='أمين عام المجلس',
            title='امين_عام',
            phone='777111222',
            is_super=False
        )
        CouncilPermission.objects.create(
            user=self.secretary,
            can_add_session=True,
            can_edit_session=True,
            can_advance_session_stage=True,
            can_draft_decision=True,
            can_send_decisions=True,
            can_view_dispatch_log=True,
            can_manage_sms_template=True,
        )

        # Member (Dean of Medicine)
        self.dean_medicine = User.objects.create_user(
            username='med_phase5',
            password='password123',
            full_name='أ.د. عميد الطب',
            title='عميد',
            phone='777333444',
            order=10,
            is_super=False
        )
        self.seat_medicine = EntitySeat.objects.create(
            name='كلية الطب البشري',
            seat_type='faculty',
            order=1,
            is_active=True,
            primary_rep=self.dean_medicine
        )

        # Member (Dean of Engineering)
        self.dean_engineering = User.objects.create_user(
            username='eng_phase5',
            password='password123',
            full_name='أ.د. عميد الهندسة',
            title='عميد',
            phone='777555666',
            order=11,
            is_super=False
        )
        self.seat_engineering = EntitySeat.objects.create(
            name='كلية الهندسة',
            seat_type='faculty',
            order=2,
            is_active=True,
            primary_rep=self.dean_engineering
        )

        # Session
        self.session = CouncilSession.objects.create(
            session_number=50,
            title='جلسة إقرار الخطط الإستراتيجية والإشعارات',
            date=timezone.localdate(),
            status='draft',
            created_by=self.admin
        )

        # Topic
        self.topic = Topic.objects.create(
            session=self.session,
            title='تحديث لائحة الشؤون المالية لكلية الطب',
            order_number=1,
            sub_order=1,
            status='approved',
            created_by=self.admin
        )
        self.topic.target_seats.add(self.seat_medicine)

    def test_default_sms_templates_seeding(self):
        """Standard council SMS templates are seeded and formatable."""
        from council.services.notification_service import ensure_default_sms_templates
        ensure_default_sms_templates()

        self.assertTrue(SMSTemplate.objects.filter(code='session_publishing').exists())
        self.assertTrue(SMSTemplate.objects.filter(code='session_live_started').exists())
        self.assertTrue(SMSTemplate.objects.filter(code='decision_dispatched').exists())

        tmpl = SMSTemplate.objects.get(code='session_publishing')
        formatted = tmpl.format_message(name='أحمد', session_num='50', date='2026-10-06')
        self.assertIn('أحمد', formatted)
        self.assertIn('50', formatted)

    def test_in_app_notification_api_and_read_state(self):
        """In-App notifications can be fetched, unread count tracked, and marked as read."""
        from council.services.notification_service import create_in_app_notification
        create_in_app_notification(
            recipient=self.dean_medicine,
            title='تنبيه هام للجلسة',
            message='يرجى مراجعة المذكرات المرفقة قبل الجلسة.',
            category='session_publishing',
            target_url='/sessions/50/'
        )

        # Dean of Medicine logs in
        self.client.login(username='med_phase5', password='password123')

        # 1. API Unread
        resp = self.client.get(reverse('council:api_unread_notifications'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['unread_count'], 1)
        self.assertEqual(len(data['notifications']), 1)
        notif_id = data['notifications'][0]['id']

        # 2. Mark as read
        resp_read = self.client.post(reverse('council:api_mark_notification_read', args=[notif_id]))
        self.assertEqual(resp_read.status_code, 200)

        # 3. Check unread count is 0
        resp_after = self.client.get(reverse('council:api_unread_notifications'))
        self.assertEqual(resp_after.json()['unread_count'], 0)

        # 4. Mark all as read API
        resp_all = self.client.post(reverse('council:api_mark_all_notifications_read'))
        self.assertEqual(resp_all.status_code, 200)

    def test_stage_advancement_triggers_notifications(self):
        """Advancing session to publishing triggers In-App notifications and SMS delivery logs."""
        self.client.login(username='sec_phase5', password='password123')

        # Move from draft to publishing
        url = reverse('council:session_advance_stage', args=[self.session.pk])
        resp = self.client.post(url, {'reason': 'فتح الاطلاع المسبق لجدول الأعمال'})
        self.assertEqual(resp.status_code, 302)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'publishing')

        # Verify in-app notifications created for dean of medicine
        notifs = InAppNotification.objects.filter(recipient=self.dean_medicine)
        self.assertTrue(notifs.exists())
        self.assertIn('فتح الاطلاع المسبق', notifs.first().title)

        # Verify notification delivery log
        logs = NotificationLog.objects.filter(recipient=self.dean_medicine, session=self.session)
        self.assertTrue(logs.exists())

    def test_decision_dispatch_triggers_faculty_notification(self):
        """Dispatching signed decision creates targeted In-App and SMS logs for recipient faculty reps."""
        attachment = SignedDecisionAttachment.objects.create(
            topic=self.topic,
            session=self.session,
            signed_file=SimpleUploadedFile("doc.pdf", b"pdf content", content_type="application/pdf"),
            decision_number='ق/2026/50/01',
            uploaded_by=self.secretary
        )

        self.client.login(username='sec_phase5', password='password123')
        url = reverse('council:dispatch_signed_decision', args=[self.topic.pk])
        resp = self.client.post(url, {
            'seat_ids': [self.seat_medicine.pk],
            'dispatch_notes': 'للتنفيذ الفوري والعمل بموجبه'
        })
        self.assertEqual(resp.status_code, 200)

        # Medicine received notification
        med_notifs = InAppNotification.objects.filter(recipient=self.dean_medicine, category='decision_dispatch')
        self.assertTrue(med_notifs.exists())
        self.assertIn('قرار موجه لكليتكم', med_notifs.first().title)

        # Engineering did NOT receive notification
        eng_notifs = InAppNotification.objects.filter(recipient=self.dean_engineering, category='decision_dispatch')
        self.assertFalse(eng_notifs.exists())

    def test_notification_and_sms_views_access(self):
        """Secretariat can access notification log & SMS template list; regular members are blocked."""
        # Secretary access
        self.client.login(username='sec_phase5', password='password123')
        resp_log = self.client.get(reverse('council:notification_log'))
        self.assertEqual(resp_log.status_code, 200)

        resp_tmpl = self.client.get(reverse('council:sms_template_list'))
        self.assertEqual(resp_tmpl.status_code, 200)

        # Member access to notification list (personal) -> 200
        self.client.login(username='med_phase5', password='password123')
        resp_my = self.client.get(reverse('council:notification_list'))
        self.assertEqual(resp_my.status_code, 200)

        # Member blocked from notification_log -> redirect
        resp_blocked = self.client.get(reverse('council:notification_log'))
        self.assertRedirects(resp_blocked, reverse('council:session_list'))


class Phase6SmartReaderAndNeuralTTSTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Super Admin
        self.superadmin = User.objects.create_user(
            username='admin_phase6',
            password='password123',
            full_name='مدير النظام التقني',
            is_super=True
        )

        # Authorized Council Member (Dean with can_use_smart_reader, order < 100)
        self.dean_user = User.objects.create_user(
            username='dean_phase6',
            password='password123',
            full_name='أ.د. عميد الكلية الذكي',
            order=15
        )
        p = self.dean_user.get_permission()
        p.can_use_smart_reader = True
        p.save()

        # Unauthorized external / non-member user
        self.guest_user = User.objects.create_user(
            username='guest_phase6',
            password='password123',
            full_name='زائر بدون صلاحية',
            order=250
        )

        # Create Council Session & Topic
        self.session = CouncilSession.objects.create(
            session_number=60,
            academic_year='1448هـ',
            date=timezone.now().date(),
            chair_name='أ.د. رئيس مجلس الجامعة',
            opening_honors='استهلت الجلسة بالثناء على إنجازات الكليات والأقسام العلمية.'
        )

        self.topic = Topic.objects.create(
            session=self.session,
            category='academic',
            order_number=1,
            title='تطوير برنامج الماجستير في الذكاء الاصطناعي',
            presenting_entity='كلية الحاسوب وتكنولوجيا المعلومات',
            memo_number='م/2026/60',
            background='نظراً للتطور التقني المتسارع واحتياج سوق العمل، تقدمت الكلية بمشروع اللائحة.',
            priorities='اعتماد الخطة الدراسية، تشكيل لجان التحكيم والمصادقة.',
            mentioned_persons='أ.د. عميد الحاسوب، د. رئيس قسم الذكاء الاصطناعي'
        )

    def test_smart_reader_access_control(self):
        """Authorized user can fetch smart reader data; unauthorized user receives 403."""
        # 1. Authorized member access -> 200 OK
        self.client.login(username='dean_phase6', password='password123')
        url = reverse('council:api_smart_reader_data') + f'?topic_id={self.topic.pk}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['title'], self.topic.title)
        self.assertGreater(data['total_chunks'], 0)

        # 2. Unauthorized user access -> 403 Forbidden
        self.client.login(username='guest_phase6', password='password123')
        resp_unauth = self.client.get(url)
        self.assertEqual(resp_unauth.status_code, 403)

    def test_topic_verbatim_smart_text_extraction(self):
        """Verbatim topic text is extracted piece-by-piece without summarization."""
        from council.services.smart_reader_service import extract_topic_smart_text
        res = extract_topic_smart_text(self.topic)
        self.assertEqual(res['type'], 'topic')
        self.assertEqual(res['topic_id'], self.topic.id)

        labels = [c['label'] for c in res['chunks']]
        self.assertIn('عنوان الموضوع', labels)
        self.assertIn('بيانات الإحالة والمذكرة', labels)
        self.assertIn('حيثيات الموضوع', labels)
        self.assertIn('الأولويات والمطالب', labels)
        self.assertIn('الأشخاص المعنيون', labels)

        # Check exact words present
        all_text = " ".join([c['text'] for c in res['chunks']])
        self.assertIn('تطوير برنامج الماجستير', all_text)
        self.assertIn('كلية الحاسوب', all_text)
        self.assertIn('للتطور التقني المتسارع', all_text)

    def test_session_smart_text_extraction(self):
        """Full session text extraction contains preamble, attendance summary, and topics."""
        from council.services.smart_reader_service import extract_session_smart_text
        res = extract_session_smart_text(self.session)
        self.assertEqual(res['type'], 'session')
        self.assertEqual(res['session_id'], self.session.id)
        
        all_text = " ".join([c['text'] for c in res['chunks']])
        self.assertIn('محضر مجلس جامعة صنعاء للجلسة رقم (60)', all_text)
        self.assertIn('استهلت الجلسة بالثناء', all_text)
        self.assertIn('كشف الحضور والنصاب القانوني', all_text)

    def test_smart_reader_synthesis_api_response(self):
        """Synthesis API returns 200 with audio_url or graceful local fallback flag."""
        self.client.login(username='dean_phase6', password='password123')
        url = reverse('council:api_smart_reader_synthesize')
        resp = self.client.post(
            url,
            json.dumps({'text': 'جامعة صنعاء مجلس الجامعة الموقر', 'speed': 1.25}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertTrue('audio_url' in data or data.get('fallback_to_local'))

    def test_smart_reader_logging_and_settings_view(self):
        """Usage log is created via API and admin settings view allows configuration updates."""
        # 1. Log usage
        self.client.login(username='dean_phase6', password='password123')
        log_url = reverse('council:api_smart_reader_log')
        resp_log = self.client.post(
            log_url,
            json.dumps({
                'topic_id': self.topic.pk,
                'target_title': self.topic.title,
                'voice_mode': 'cloud_neural',
                'speed': 1.25,
                'chunks_count': 5
            }),
            content_type='application/json'
        )
        self.assertEqual(resp_log.status_code, 200)
        self.assertTrue(SmartReaderLog.objects.filter(user=self.dean_user, topic=self.topic).exists())

        # 2. Admin settings view GET -> 200
        self.client.login(username='admin_phase6', password='password123')
        sett_url = reverse('council:smart_reader_settings')
        resp_get = self.client.get(sett_url)
        self.assertEqual(resp_get.status_code, 200)

        # 3. Admin settings POST -> update settings
        resp_post = self.client.post(sett_url, {
            'voice_mode': 'browser_local',
            'neural_voice': 'ar-YE-SalehNeural',
            'default_speed': '1.25',
            'auto_scroll': 'on',
            'highlight_color': '#FEF08A'
        })
        self.assertEqual(resp_post.status_code, 302)

        s = SmartReaderSetting.get_settings()
        self.assertEqual(s.voice_mode, 'browser_local')
        self.assertEqual(s.neural_voice, 'ar-YE-SalehNeural')
        self.assertEqual(s.default_speed, 1.25)




