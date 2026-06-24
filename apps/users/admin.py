from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms
from .models import User, LearnerProfile, Role, StaffProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("first_name", "last_name", "email", "role", "is_active", "is_staff", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("role", "is_active", "is_staff")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )

    def save_model(self, request, obj, form, change):
        email_changed = change and "email" in form.changed_data
        super().save_model(request, obj, form, change)
        if email_changed and obj.role == Role.LEARNER:
            try:
                from core.email import build_set_password_url, send_email
                profile = obj.learner_profile
                send_email(
                    subject="Welcome to Lead Edge Exam Centre",
                    to_email=obj.email,
                    template_name="learner_welcome",
                    context={
                        "first_name": obj.first_name,
                        "username": obj.email,
                        "learner_id": profile.learner_id,
                        "uln": profile.uln,
                        "login_url": f"{settings.FRONTEND_URL}/test-centre",
                        "set_password_url": build_set_password_url(obj),
                    },
                )
                self.message_user(request, f"Welcome email re-sent to {obj.email}.", messages.SUCCESS)
            except Exception as e:
                self.message_user(request, f"Email update saved but welcome email failed: {e}", messages.WARNING)


class LearnerProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()

    class Meta:
        model = LearnerProfile
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def clean_email(self):
        value = self.cleaned_data["email"].lower()
        qs = User.objects.filter(email=value)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return value


@admin.register(LearnerProfile)
class LearnerProfileAdmin(admin.ModelAdmin):
    form = LearnerProfileForm
    list_display = ("learner_id", "full_name", "email_display", "uln", "phone")
    search_fields = ("user__email", "user__first_name", "user__last_name", "learner_id", "uln")
    readonly_fields = ("learner_id", "created_at", "updated_at")
    fieldsets = (
        ("Identity", {
            "fields": ("learner_id", "first_name", "last_name", "email"),
        }),
        ("Profile", {
            "fields": ("uln", "date_of_birth", "phone", "photo", "id_document", "id_verified"),
        }),
        ("Audit", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Name")
    def full_name(self, obj):
        return obj.user.full_name

    @admin.display(description="Email")
    def email_display(self, obj):
        return obj.user.email

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        user = obj.user
        user_changed = []
        for field in ("first_name", "last_name"):
            val = form.cleaned_data.get(field)
            if val and getattr(user, field) != val:
                setattr(user, field, val)
                user_changed.append(field)
        new_email = form.cleaned_data.get("email", "").lower()
        email_changed = new_email and user.email != new_email
        if email_changed:
            user.email = new_email
            user_changed.append("email")
        if user_changed:
            user.save(update_fields=user_changed)
        if email_changed:
            try:
                from core.email import build_set_password_url, send_email
                send_email(
                    subject="Welcome to Lead Edge Exam Centre",
                    to_email=user.email,
                    template_name="learner_welcome",
                    context={
                        "first_name": user.first_name,
                        "username": user.email,
                        "learner_id": obj.learner_id,
                        "uln": obj.uln,
                        "login_url": f"{settings.FRONTEND_URL}/test-centre",
                        "set_password_url": build_set_password_url(user),
                    },
                )
                self.message_user(request, f"Welcome email re-sent to {user.email}.", messages.SUCCESS)
            except Exception as e:
                self.message_user(request, f"Email saved but welcome email failed: {e}", messages.WARNING)


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "staff_id", "job_title", "staff_id", "phone")
    search_fields = ("user__email", "user__first_name", "user__last_name")
