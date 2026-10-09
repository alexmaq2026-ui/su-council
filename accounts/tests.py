from django.test import TestCase, Client
from django.urls import reverse
from .models import User, CouncilPermission


class UserManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Super Admin
        self.superadmin = User.objects.create_user(
            username='super_test',
            password='password123',
            full_name='المسؤول العام التجريبي',
            title='رئيس_الجامعة',
            is_super=True
        )
        # Director of affairs
        self.director = User.objects.create_user(
            username='director_test',
            password='password123',
            full_name='مدير المساعدة التجريبي',
            title='مدير_عام_المساعدة',
            is_super=False
        )
        # Give director permission to grant/manage
        CouncilPermission.objects.create(
            user=self.director,
            can_grant_permissions=True,
            can_manage_users=True,
        )

        # Subordinate staff under director
        self.subordinate = User.objects.create_user(
            username='staff_test',
            password='password123',
            full_name='موظف تجريبي',
            title='موظف_المساعدة',
            manager=self.director,
            is_super=False
        )

        # Independent council member
        self.member = User.objects.create_user(
            username='dean_test',
            password='password123',
            full_name='عميد تجريبي',
            title='عميد',
            is_super=False
        )

    def test_new_user_has_zero_permissions(self):
        """Newly created user must have zero granted permissions."""
        perm = self.member.get_permission()
        self.assertEqual(perm.count_granted(), 0)
        self.assertFalse(self.member.can_add)
        self.assertFalse(self.member.can_vote)
        self.assertFalse(self.member.can_manage_users)

    def test_superadmin_can_deactivate_user(self):
        """Super Admin can softly deactivate a user."""
        self.client.login(username='super_test', password='password123')
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.member.pk]),
            {'action_type': 'deactivate'}
        )
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

    def test_superadmin_can_permanently_delete_user(self):
        """Super Admin can permanently delete a user from DB."""
        self.client.login(username='super_test', password='password123')
        member_pk = self.member.pk
        response = self.client.post(
            reverse('accounts:user_delete', args=[member_pk]),
            {'action_type': 'permanent_delete'}
        )
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.assertFalse(User.objects.filter(pk=member_pk).exists())

    def test_user_cannot_delete_self(self):
        """User cannot delete their own account."""
        self.client.login(username='super_test', password='password123')
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.superadmin.pk]),
            {'action_type': 'permanent_delete'}
        )
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.assertTrue(User.objects.filter(pk=self.superadmin.pk).exists())

    def test_director_can_delete_subordinate(self):
        """Director can delete staff reporting to them."""
        self.client.login(username='director_test', password='password123')
        sub_pk = self.subordinate.pk
        response = self.client.post(
            reverse('accounts:user_delete', args=[sub_pk]),
            {'action_type': 'permanent_delete'}
        )
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.assertFalse(User.objects.filter(pk=sub_pk).exists())

    def test_director_cannot_delete_independent_member(self):
        """Director cannot delete a member not under their supervision."""
        self.client.login(username='director_test', password='password123')
        response = self.client.post(
            reverse('accounts:user_delete', args=[self.member.pk]),
            {'action_type': 'permanent_delete'}
        )
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())

    def test_superadmin_can_reactivate_user(self):
        """Super Admin can reactivate a deactivated user."""
        self.member.is_active = False
        self.member.save()

        self.client.login(username='super_test', password='password123')
        response = self.client.post(reverse('accounts:user_activate', args=[self.member.pk]))
        self.assertRedirects(response, reverse('accounts:user_list'))
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
