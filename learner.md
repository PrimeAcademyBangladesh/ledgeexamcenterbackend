# Learners App — Lead Edge Ltd

Manages **Learner profiles** (extended attributes for users with `role=learner`),
**Enrollments** (Learner ↔ Qualification linkage with cohort/employer), and
**Reasonable Adjustments** (per-learner accommodations applied at session creation).

## Dependencies (build order)

1. `users` ✅ — provides `User`, `LearnerProfile`, `Role`
2. `qualifications` ✅ — provides `Qualification`
3. **`learners`** ← THIS APP
4. `invigilators` (next)
5. `exams` / `sessions` / `results` …

> ⚠️ `LearnerProfile` already lives in `users/models.py`.
> This app **does not redefine it** — it adds Enrollment + ReasonableAdjustment,
> plus the admin-facing endpoints used by the React UI screens:
>
> - `/admin/learners` → `AdminLearners.tsx`
> - `/learner/dashboard` → `LearnerDashboard.tsx` (enrollments, profile)
> - Invigilator dashboard (read learner by ULN)

## Frontend screens this powers

| UI Screen | Endpoint(s) |
|---|---|
| AdminLearners — list + search | `GET /api/learners/` |
| AdminLearners — register modal | `POST /api/learners/` (creates User + LearnerProfile + Enrollment) |
| AdminLearners — edit modal | `PATCH /api/learners/{id}/` |
| AdminLearners — activate / deactivate | `POST /api/learners/{id}/activate/` · `POST /api/learners/{id}/deactivate/` |
| AdminLearners — view detail | `GET /api/learners/{id}/` |
| AdminLearners — past results | `GET /api/learners/{id}/results/` (delegates to results app) |
| LearnerDashboard — "Your Enrolment" cards | `GET /api/me/enrollments/` |
| LearnerDashboard — profile header | `GET /api/auth/me/` (already in users app) |
| Invigilator — verify ID | `GET /api/learners/by-uln/{uln}/` |

## Files

- `models.py` — Enrollment, ReasonableAdjustment
- `serializers.py` — camelCase serializers + write/read split
- `views.py` — LearnerViewSet, EnrollmentViewSet, MyEnrollmentsView, ReasonableAdjustmentViewSet
- `urls.py` — REST routes
- `permissions.py` — IsAdmin / IsAdminOrReadOnlyStaff / IsSelfLearner
- `signals.py` — (optional) post-save hooks
- `filters.py` — search/filter for AdminLearners table
