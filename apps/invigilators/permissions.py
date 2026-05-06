from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.users.models import Role


class IsAdmin(BasePermission):
    """Admins have full CRUD on invigilator records."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and request.user.role == Role.ADMIN)


class IsAdminOrInvigilatorReadOnly(BasePermission):
    """
    - Admin  : full access.
    - Invigilator : read-only (e.g. listing peers, viewing own record).
    - Learner : denied.
    """
    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.role == Role.ADMIN:
            return True
        if u.role == Role.INVIGILATOR and request.method in SAFE_METHODS:
            return True
        return False


class IsSelfOrAdmin(BasePermission):
    """Object-level: an invigilator can only see/edit themselves; admin sees all."""
    def has_object_permission(self, request, view, obj):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.role == Role.ADMIN:
            return True
        return obj.pk == u.pk
