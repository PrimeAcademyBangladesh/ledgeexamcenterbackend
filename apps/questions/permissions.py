"""
Lead Edge Ltd — Questions permissions
=====================================
- Admin: full CRUD on /api/questions/.
- Invigilator: read-only (e.g. to spot-check the bank).
- Learner: NO direct access; learners only see questions through a frozen
  ExamSession.question_set delivered by the exam app.
"""

from rest_framework import permissions


class IsAdminOrStaffReadOnly(permissions.BasePermission):
    """Admin: full access. Invigilator: SAFE methods only. Others: denied."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        role = getattr(user, "role", None)
        if role == "admin":
            return True
        if role == "invigilator" and request.method in permissions.SAFE_METHODS:
            return True
        return False
