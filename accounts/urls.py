"""
Accounts URL Configuration - University Council Management System
Defines all routes with both underscore and hyphenated names.
"""
from django.urls import path
from . import views

urlpatterns = [
    # ── Authentication ────────────────────────────────────────────────────────
    path('login/',  views.login_view,  name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Main Dashboard ────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # ── User Management ───────────────────────────────────────────────────────
    path('users/',                      views.user_list_view,                  name='user_list'),
    path('users/',                      views.user_list_view,                  name='user-list'),
    path('users/create/',               views.user_create_view,                name='user_create'),
    path('users/create/',               views.user_create_view,                name='user-create'),
    path('users/import/',               views.member_import_view,              name='member_import'),
    path('users/import/',               views.member_import_view,              name='member-import'),
    path('users/import/template/',      views.download_member_template_view,   name='member_import_template'),
    path('users/import/template/',      views.download_member_template_view,   name='member-import-template'),
    path('users/<int:pk>/edit/',        views.user_edit_view,                  name='user_edit'),
    path('users/<int:pk>/edit/',        views.user_edit_view,                  name='user-edit'),
    path('users/<int:pk>/permissions/', views.user_permissions_view,           name='user_permissions'),
    path('users/<int:pk>/permissions/', views.user_permissions_view,           name='user-permissions'),
    path('users/<int:pk>/grant-voting-permissions/', views.grant_voting_member_permissions_view, name='grant_voting_permissions'),
    path('users/<int:pk>/grant-voting-permissions/', views.grant_voting_member_permissions_view, name='grant-voting-permissions'),
    path('users/grant-voting-permissions-bulk/', views.grant_voting_member_permissions_bulk_view, name='grant_voting_permissions_bulk'),
    path('users/grant-voting-permissions-bulk/', views.grant_voting_member_permissions_bulk_view, name='grant-voting-permissions-bulk'),
    path('users/<int:pk>/delete/',      views.user_delete_view,                name='user_delete'),
    path('users/<int:pk>/delete/',      views.user_delete_view,                name='user-delete'),
    path('users/<int:pk>/activate/',    views.user_activate_view,              name='user_activate'),
    path('users/<int:pk>/activate/',    views.user_activate_view,              name='user-activate'),
    path('users/<int:pk>/reset-password/', views.user_reset_password_view,     name='user_reset_password'),
    path('users/<int:pk>/reset-password/', views.user_reset_password_view,     name='user-reset-password'),

    # ── Seat Deputies Management ──────────────────────────────────────────────
    path('seats/deputies/', views.seat_deputies_view, name='seat_deputies'),
    path('seats/deputies/', views.seat_deputies_view, name='seat-deputies'),

    # ── Personal Direct Gate & Token Authentication ───────────────────────────
    path('gate/<str:token>/', views.direct_gate_login_view, name='direct_gate_login'),
    path('users/<int:pk>/generate-token/', views.generate_user_token_view, name='generate_user_token'),
    path('users/<int:pk>/generate-token/', views.generate_user_token_view, name='generate-user-token'),

    # ── Personal Profile ──────────────────────────────────────────────────────
    path('profile/',         views.profile_view,         name='profile'),
    path('change-password/', views.change_password_view, name='change_password'),
    path('change-password/', views.change_password_view, name='change-password'),
]
