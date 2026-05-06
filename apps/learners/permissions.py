"""
apps/learners/permissions.py
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.users.models import Role


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == Role.ADMIN


class IsAdminOrReadOnlyStaff(BasePermission):
    """
    Admins: full CRUD.
    Invigilators: read-only (e.g. lookup learner by ULN at the test centre).
    Learners: blocked (use /api/me/* endpoints instead).
    """
    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if u.role == Role.ADMIN:
            return True
        if u.role == Role.INVIGILATOR and request.method in SAFE_METHODS:
            return True
        return False


class IsSelfLearner(BasePermission):
    """For /api/me/enrollments/ and similar — must be a learner."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == Role.LEARNER
