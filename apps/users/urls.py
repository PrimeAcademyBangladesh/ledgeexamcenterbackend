from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.utils import extend_schema

from apps.users.views import LoginView, LogoutView, MeView, ChangePasswordView, ForgotPasswordView, ResetPasswordView

TokenRefreshView = extend_schema(tags=["Authentication"])(TokenRefreshView)

urlpatterns = [
    path("login/", LoginView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("users/me/", MeView.as_view(), name="user_me"),
    path("users/change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("users/forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("users/reset-password/", ResetPasswordView.as_view(), name="reset_password"),
    path("users/logout/", LogoutView.as_view(), name="logout"),
]
