from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.password_validation import validate_password
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


# =========================
# USER BASE SERIALIZER
# =========================

class UserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    firstName = serializers.CharField(source="first_name")
    lastName = serializers.CharField(source="last_name")
    role = serializers.CharField()


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        attrs[self.username_field] = attrs[self.username_field].lower()
        data = super().validate(attrs)
        data["user"] = {
            "id": str(self.user.id),
            "email": self.user.email,
            "firstName": self.user.first_name,
            "lastName": self.user.last_name,
            "role": self.user.role,
        }
        return data


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


# =========================
# PASSWORD MANAGEMENT
# =========================

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({
                "confirm_password": "Passwords do not match."
            })
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.lower()
        self._user = User.objects.filter(email=value, is_active=True).first()
        return value

    def get_user(self):
        return getattr(self, "_user", None)


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({
                "confirm_password": "Passwords do not match."
            })

        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError):
            raise serializers.ValidationError({"uid": "Invalid reset link."})

        if not PasswordResetTokenGenerator().check_token(user, attrs["token"]):
            raise serializers.ValidationError({
                "token": "Reset link is invalid or has expired."
            })

        attrs["user"] = user
        return attrs


# =========================
# RESPONSE SCHEMAS (FOR DOCS)
# =========================

class ProfileSerializer(serializers.Serializer):
    # Learner fields
    learnerId = serializers.CharField(required=False)
    uln = serializers.CharField(required=False)
    dateOfBirth = serializers.DateField(required=False, allow_null=True)
    phone = serializers.CharField(required=False)
    photo = serializers.CharField(required=False, allow_null=True)
    idVerified = serializers.BooleanField(required=False)

    # Staff fields
    staffId = serializers.CharField(required=False)
    jobTitle = serializers.CharField(required=False)


class MeUserSerializer(UserSerializer):
    profile = ProfileSerializer()


class MeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    user = MeUserSerializer()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()