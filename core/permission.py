"""
core/permission.py
Lead Edge Ltd EPAO Exam Platform

Role-based DRF permission classes for three roles:
    - admin       : full CRUD across the platform
    - invigilator : exam supervisor; reads most data, writes session-scoped data
    - learner     : end user; reads/writes only their own records

Object-level classes assume a `learner` or `invigilator` FK on the target
model. Override `owner_field` / `invigilator_field` on the view to customise.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


# ────────────────────────────────────────────────────────────
#  Role constants & helpers
# ────────────────────────────────────────────────────────────
ADMIN = "admin"
INVIGILATOR = "invigilator"
LEARNER = "learner"
ALL_ROLES = (ADMIN, INVIGILATOR, LEARNER)


def _role(user):
    if not (user and user.is_authenticated):
        return None
    return getattr(user, "role", None)


def _has_role(request, *roles):
    return _role(request.user) in roles


# ────────────────────────────────────────────────────────────
#  Single-role gates
# ────────────────────────────────────────────────────────────
class IsAdmin(BasePermission):
    """Admin only."""
    def has_permission(self, request, view):
        return _has_role(request, ADMIN)


class IsInvigilator(BasePermission):
    """Invigilator only."""
    def has_permission(self, request, view):
        return _has_role(request, INVIGILATOR)


class IsLearner(BasePermission):
    """Learner only."""
    def has_permission(self, request, view):
        return _has_role(request, LEARNER)


class IsStaff(BasePermission):
    """Admin or invigilator (any non-learner authenticated user)."""
    def has_permission(self, request, view):
        return _has_role(request, ADMIN, INVIGILATOR)


class IsAdminOrLearner(BasePermission):
    """Admin or learner — excludes invigilator."""
    def has_permission(self, request, view):
        return _has_role(request, ADMIN, LEARNER)


class IsInvigilatorOrLearner(BasePermission):
    """Invigilator or learner — excludes admin."""
    def has_permission(self, request, view):
        return _has_role(request, INVIGILATOR, LEARNER)


class IsAuthenticatedRole(BasePermission):
    """Any authenticated user with a recognised role."""
    def has_permission(self, request, view):
        return _has_role(request, *ALL_ROLES)


# ────────────────────────────────────────────────────────────
#  Aliases for convenience
# ────────────────────────────────────────────────────────────
class IsInvigilatorOrAdmin(BasePermission):
    """Alias for IsStaff — admin or invigilator."""
    def has_permission(self, request, view):
        return IsStaff().has_permission(request, view)


class IsSessionLearnerOwner(BasePermission):
    """Alias for IsLearnerSelfOrAdmin — learner owns the session."""
    def has_object_permission(self, request, view, obj):
        return IsLearnerSelfOrAdmin().has_object_permission(request, view, obj)


# ────────────────────────────────────────────────────────────
#  Read-only & mixed-method composites
# ────────────────────────────────────────────────────────────
class ReadOnly(BasePermission):
    """Any authenticated user, read-only."""
    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and request.method in SAFE_METHODS
        )


class IsAdminOrReadOnly(BasePermission):
    """Admin: full CRUD. Any authenticated role: read-only."""
    def has_permission(self, request, view):
        role = _role(request.user)
        if role is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return role == ADMIN


class IsAdminOrReadOnlyForStaff(BasePermission):
    """Admin: full CRUD. Invigilator: read-only. Learner: denied."""
    def has_permission(self, request, view):
        role = _role(request.user)
        if role == ADMIN:
            return True
        if role == INVIGILATOR and request.method in SAFE_METHODS:
            return True
        return False


class IsAdminOrReadOnlyForLearner(BasePermission):
    """Admin: full CRUD. Learner: read-only. Invigilator: denied."""
    def has_permission(self, request, view):
        role = _role(request.user)
        if role == ADMIN:
            return True
        if role == LEARNER and request.method in SAFE_METHODS:
            return True
        return False


class IsStaffOrReadOnlyForLearner(BasePermission):
    """Admin & invigilator: full CRUD. Learner: read-only."""
    def has_permission(self, request, view):
        role = _role(request.user)
        if role in (ADMIN, INVIGILATOR):
            return True
        if role == LEARNER and request.method in SAFE_METHODS:
            return True
        return False


class IsAdminWriteInvigilatorReadLearnerNone(BasePermission):
    """
    Explicit alias of IsAdminOrReadOnlyForStaff — kept for readability
    when the rule is being chosen for a specific reason.
    """
    def has_permission(self, request, view):
        return IsAdminOrReadOnlyForStaff().has_permission(request, view)


# ────────────────────────────────────────────────────────────
#  Object-level: generic ownership
# ────────────────────────────────────────────────────────────
class IsOwner(BasePermission):
    """
    Object owner only.
    Owner FK defaults to `learner`; override `owner_field` on the view.
    """
    def has_object_permission(self, request, view, obj):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        field = getattr(view, "owner_field", "learner")
        return getattr(obj, f"{field}_id", None) == u.id


class IsOwnerOrAdmin(BasePermission):
    """Object owner or admin."""
    def has_object_permission(self, request, view, obj):
        role = _role(request.user)
        if role is None:
            return False
        if role == ADMIN:
            return True
        field = getattr(view, "owner_field", "learner")
        return getattr(obj, f"{field}_id", None) == request.user.id


class IsOwnerOrReadOnly(BasePermission):
    """Owner: full CRUD. Any authenticated role: read-only."""
    def has_object_permission(self, request, view, obj):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        field = getattr(view, "owner_field", "learner")
        return getattr(obj, f"{field}_id", None) == u.id


# ────────────────────────────────────────────────────────────
#  Object-level: learner-scoped
# ────────────────────────────────────────────────────────────
class IsLearnerSelfOrAdmin(BasePermission):
    """
    Admin: any object.
    Learner: objects where `learner_id == self.id`.
    Invigilator: denied.
    """
    def has_object_permission(self, request, view, obj):
        role = _role(request.user)
        if role == ADMIN:
            return True
        if role == LEARNER:
            return getattr(obj, "learner_id", None) == request.user.id
        return False


class IsEnrollmentOwnerOrAdmin(BasePermission):
    """
    Admin: full access.
    Learner: read-only on their own enrolments.
    Invigilator: denied (use IsAssignedInvigilatorOrAdmin instead).
    """
    def has_object_permission(self, request, view, obj):
        role = _role(request.user)
        if role == ADMIN:
            return True
        if role == LEARNER and request.method in SAFE_METHODS:
            return getattr(obj, "learner_id", None) == request.user.id
        return False


# ────────────────────────────────────────────────────────────
#  Object-level: invigilator-scoped
# ────────────────────────────────────────────────────────────
class IsAssignedInvigilator(BasePermission):
    """Invigilator assigned to this object via `invigilator_id`."""
    def has_object_permission(self, request, view, obj):
        if _role(request.user) != INVIGILATOR:
            return False
        field = getattr(view, "invigilator_field", "invigilator")
        return getattr(obj, f"{field}_id", None) == request.user.id


class IsAssignedInvigilatorOrAdmin(BasePermission):
    """Admin: any object. Invigilator: only objects assigned to them."""
    def has_object_permission(self, request, view, obj):
        role = _role(request.user)
        if role == ADMIN:
            return True
        if role == INVIGILATOR:
            field = getattr(view, "invigilator_field", "invigilator")
            return getattr(obj, f"{field}_id", None) == request.user.id
        return False


class IsAssignedInvigilatorOrLearnerSelf(BasePermission):
    """
    Invigilator: object assigned to them.
    Learner: object where they are the learner.
    Admin: denied (use a separate admin-only route).
    """
    def has_object_permission(self, request, view, obj):
        role = _role(request.user)
        uid = getattr(request.user, "id", None)
        if role == INVIGILATOR:
            field = getattr(view, "invigilator_field", "invigilator")
            return getattr(obj, f"{field}_id", None) == uid
        if role == LEARNER:
            field = getattr(view, "owner_field", "learner")
            return getattr(obj, f"{field}_id", None) == uid
        return False


# ────────────────────────────────────────────────────────────
#  Compound: full role-aware policy
# ────────────────────────────────────────────────────────────
class RoleScopedAccess(BasePermission):
    """
    One-stop role policy:
        admin       → full CRUD on every object.
        invigilator → read any; write only objects assigned to them
                      (via `invigilator_id`).
        learner     → read & write only their own objects
                      (via `learner_id`).

    The view's queryset is still responsible for row-level visibility on
    list endpoints; this class only enforces per-object access for retrieve
    / update / destroy.
    """
    def has_permission(self, request, view):
        return _has_role(request, *ALL_ROLES)

    def has_object_permission(self, request, view, obj):
        role = _role(request.user)
        if role == ADMIN:
            return True

        uid = request.user.id
        owner_field = getattr(view, "owner_field", "learner")
        invigilator_field = getattr(view, "invigilator_field", "invigilator")

        if request.method in SAFE_METHODS:
            if role == INVIGILATOR:
                return True
            if role == LEARNER:
                return getattr(obj, f"{owner_field}_id", None) == uid
            return False

        if role == INVIGILATOR:
            return getattr(obj, f"{invigilator_field}_id", None) == uid
        if role == LEARNER:
            return getattr(obj, f"{owner_field}_id", None) == uid
        return False
