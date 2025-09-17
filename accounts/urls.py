from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    # Auth
    path("login/", views.RoleLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("post-login/", views.post_login_redirect, name="post_login_redirect"),
    # Password change (logged-in)
    path(
        "password_change/",
        auth_views.PasswordChangeView.as_view(
            success_url=reverse_lazy("accounts:password_change_done")
        ),
        name="password_change",
    ),
    path(
        "password_change/done/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    # Password reset (public)
    path(
        "password_reset/",
        auth_views.PasswordResetView.as_view(
            success_url=reverse_lazy("accounts:password_reset_done"),
            email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy("accounts:password_reset_complete")
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    # Custom
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
]
