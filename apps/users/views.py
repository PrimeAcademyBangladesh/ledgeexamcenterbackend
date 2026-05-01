from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from rest_framework import generics, status
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema

from apps.users.models import Role
from apps.users.serializers import (
    LoginSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    MeResponseSerializer,
    LoginResponseSerializer,
    LogoutSerializer,
)


@extend_schema(
    tags=["Authentication"],
    request=LoginSerializer,
    responses=LoginResponseSerializer,
)
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


@extend_schema(
    tags=["Authentication"],
    responses=MeResponseSerializer,
)
class MeView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        profile = {}
        if user.role == Role.LEARNER:
            p = getattr(user, "learner_profile", None)
            if p:
                profile = {
                    "learnerId": p.learner_id,
                    "uln": p.uln,
                    "dateOfBirth": p.date_of_birth,
                    "phone": p.phone,
                    "photo": p.photo.url if p.photo else None,
                    "idVerified": p.id_verified,
                }
        elif user.role in [Role.INVIGILATOR, Role.ADMIN]:
            p = getattr(user, "staff_profile", None)
            if p:
                profile = {
                    "staffId": p.staff_id,
                    "jobTitle": p.job_title,
                    "phone": p.phone,
                    "photo": p.photo.url if p.photo else None,
                }

        return Response({
            "success": True,
            "message": "User data retrieved successfully",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "role": user.role,
                "profile": profile,
            },
        })


@extend_schema(
    tags=["Authentication"],
    request=ChangePasswordSerializer,
    responses={200: {"type": "object"}},
)
class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)

        return Response(
            {"success": True, "message": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Authentication"],
    request=ForgotPasswordSerializer,
    responses={200: {"type": "object"}},
)
class ForgotPasswordView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ForgotPasswordSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.get_user()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = PasswordResetTokenGenerator().make_token(user)
            reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

            send_mail(
                subject="Reset your password",
                message=f"Hi {user.first_name},\n\nClick the link below to reset your password:\n{reset_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

        return Response(
            {
                "success": True,
                "message": "If this email is registered, a reset link has been sent.",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Authentication"],
    request=ResetPasswordSerializer,
    responses={200: {"type": "object"}},
)
class ResetPasswordView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ResetPasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)

        return Response(
            {"success": True, "message": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Authentication"],
    request=LogoutSerializer,
    responses={200: {"type": "object"}},
)
class LogoutView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            token.blacklist()

            return Response(
                {"success": True, "message": "Logged out successfully."},
                status=status.HTTP_200_OK,
            )

        except Exception:
            return Response(
                {"success": False, "message": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )