# Qualifications App — DRF Serializers

**Project:** Lead Edge Ltd EPAO Exam Platform
**Django app:** `apps/qualifications/serializers.py`
**Mapped to UI:** every serializer below is anchored to a real screen in the React frontend so payloads stay lean.

---

## Design principles

1. **One serializer per use case, not per model.** A list view does not need the same payload as a detail view; an admin write form does not need the same shape as a learner read.
2. **Read fields are flat strings/IDs** matching the existing `src/services/api/types.ts` interfaces (e.g. `qualificationName`, `qualificationId`) so no frontend changes are needed.
3. **Write serializers accept FK IDs only** (`sector_id`, `level_id`); never nested writes — they are fragile and confuse the admin form code.
4. **Computed fields use `SerializerMethodField`** for derived UI values (bank health %, learner counts) so the frontend never recomputes business logic.
5. **All read serializers are cache-safe** — no per-request DB writes, no signals.

---

## 1. `SectorSerializer`

```python
class SectorSerializer(serializers.ModelSerializer):
    """
    Why: Powers the admin-managed Sector dropdowns and CRUD UI.
    Where:
      - GET  /api/sectors/                → AdminQualifications page filter dropdown
      - GET  /api/sectors/                → AdminExams "Create exam" form (sector chip)
      - POST /api/sectors/                → New "Sectors" admin settings page (to be added)
      - PATCH /api/sectors/{id}/          → Toggle is_active / rename
    Notes:
      - `qualification_count` is a denormalised read-only helper for the admin
        list so the table can show "12 qualifications" without an N+1.
    """
    qualification_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Sector
        fields = ["id", "name", "code", "slug", "sort_order",
                  "is_active", "qualification_count"]
        read_only_fields = ["id", "slug", "qualification_count"]
```

---

## 2. `LevelSerializer`

```python
class LevelSerializer(serializers.ModelSerializer):
    """
    Why: Same rationale as Sector — admin-managed list, drives dropdowns.
    Where:
      - GET  /api/levels/                 → AdminQualifications + AdminExams forms
      - POST/PATCH /api/levels/           → Admin "Levels" settings screen
    """
    class Meta:
        model = Level
        fields = ["id", "name", "numeric_value", "is_active"]
        read_only_fields = ["id"]
```

---

## 3. Qualification serializers (three variants)

The frontend reads qualifications in three different shapes. Building three small serializers is cheaper than one bloated one with `fields=` switching.

### 3.1 `QualificationListSerializer` — for dropdowns and filter chips

```python
class QualificationListSerializer(serializers.ModelSerializer):
    """
    Why: The most-called endpoint in the admin UI. Must be tiny.
    Where (matches existing `Qualification` interface in src/services/api/types.ts):
      - AdminExams.tsx          → exams filter + create-exam form dropdown
      - AdminLearners.tsx       → enrolment dropdown ("Select qualification")
      - AdminQuestionBank.tsx   → "Select qualification" picker (top of page)
      - AdminReports.tsx        → filter dropdown
    Payload kept ≤ 8 fields to stay under 5KB even with 200 quals.
    """
    sector = serializers.CharField(source="sector.name", read_only=True)
    questionCount = serializers.IntegerField(source="question_count", read_only=True)
    isActive = serializers.BooleanField(source="is_active", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Qualification
        fields = ["id", "title", "code", "sector",
                  "questionCount", "isActive", "createdAt"]
```

### 3.2 `QualificationDetailSerializer` — for the qualification edit page

```python
class QualificationDetailSerializer(serializers.ModelSerializer):
    """
    Why: Full record for admin edit/detail screens. Includes nested sector/level
         names so the page can render without a second request.
    Where:
      - GET /api/qualifications/{id}/     → AdminQualificationDetail page (planned)
      - GET /api/qualifications/{id}/     → AdminExams.tsx "Create exam" form
        uses defaults (default_questions_per_exam, default_time_limit_minutes,
        default_*_boundary) to PRE-FILL the form. This is critical: the form
        currently hardcodes 40 questions / 60 minutes — those defaults must
        come from here.
      - GET /api/qualifications/{id}/     → AdminQuestionBank.tsx reads
        min_bank_size + recommended_bank_size to drive the bank-health badge.
    """
    sector = SectorSerializer(read_only=True)
    level = LevelSerializer(read_only=True)
    units = serializers.SerializerMethodField()
    bankHealth = serializers.SerializerMethodField()

    class Meta:
        model = Qualification
        fields = [
            "id", "code", "title", "slug", "description",
            "sector", "level", "is_active",
            # Defaults (used by AdminExams create form)
            "default_questions_per_exam", "default_time_limit_minutes",
            "default_pass_boundary", "default_merit_boundary",
            "default_distinction_boundary",
            # Bank rules (used by AdminQuestionBank header)
            "min_bank_size", "recommended_bank_size", "bankHealth",
            # Resit rules (used by RetakeRequest auto-approve logic + learner UI)
            "resit_unseen_ratio", "resit_fail_margin_percent",
            "max_resit_attempts", "resit_cooldown_days",
            "units", "created_at", "updated_at",
        ]

    def get_units(self, obj):
        """Inline units to avoid a second request on the detail page."""
        return QualificationUnitSerializer(obj.units.all(), many=True).data

    def get_bankHealth(self, obj):
        """
        Computed: percentage of recommended bank filled.
        Drives the green/amber/red badge in AdminQuestionBank header.
        Frontend should NOT recompute — keeps the threshold logic server-side.
        """
        total = obj.questions.filter(is_active=True).count()
        target = obj.recommended_bank_size or 1
        return {
            "current": total,
            "target": target,
            "min": obj.min_bank_size,
            "percent": round(min(100, (total / target) * 100), 1),
            "status": "healthy" if total >= target
                       else "warning" if total >= obj.min_bank_size
                       else "critical",
        }
```

### 3.3 `QualificationWriteSerializer` — admin create/update

```python
class QualificationWriteSerializer(serializers.ModelSerializer):
    """
    Why: Separate write serializer keeps validation tight and avoids leaking
         computed/read-only fields into PATCH payloads.
    Where:
      - POST  /api/qualifications/         → "New Qualification" admin form
      - PATCH /api/qualifications/{id}/    → Edit form (same screen)
    Validation:
      - default_pass < default_merit < default_distinction
      - resit_unseen_ratio between 0 and 1
      - min_bank_size <= recommended_bank_size
    """
    sector_id = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.filter(is_active=True), source="sector")
    level_id = serializers.PrimaryKeyRelatedField(
        queryset=Level.objects.filter(is_active=True), source="level")

    class Meta:
        model = Qualification
        fields = [
            "code", "title", "description",
            "sector_id", "level_id", "is_active",
            "default_questions_per_exam", "default_time_limit_minutes",
            "default_pass_boundary", "default_merit_boundary",
            "default_distinction_boundary",
            "min_bank_size", "recommended_bank_size",
            "resit_unseen_ratio", "resit_fail_margin_percent",
            "max_resit_attempts", "resit_cooldown_days",
        ]

    def validate(self, attrs):
        p = attrs.get("default_pass_boundary")
        m = attrs.get("default_merit_boundary")
        d = attrs.get("default_distinction_boundary")
        if not (p < m < d):
            raise serializers.ValidationError(
                "Grade boundaries must satisfy: pass < merit < distinction.")
        if attrs.get("min_bank_size", 0) > attrs.get("recommended_bank_size", 0):
            raise serializers.ValidationError(
                "min_bank_size cannot exceed recommended_bank_size.")
        return attrs
```

---

## 4. `QualificationUnitSerializer`

```python
class QualificationUnitSerializer(serializers.ModelSerializer):
    """
    Why: Units drive (a) the unit picker in the question editor and
         (b) per-unit performance breakdown on the marksheet PDF.
    Where:
      - Nested in QualificationDetailSerializer (above)
      - GET  /api/qualifications/{id}/units/  → AdminQuestionBank "Tag units" picker
      - POST /api/qualifications/{id}/units/  → "Manage units" modal
    """
    questionCount = serializers.IntegerField(source="questions.count", read_only=True)

    class Meta:
        model = QualificationUnit
        fields = ["id", "code", "title", "description",
                  "weight", "sort_order", "questionCount"]
        read_only_fields = ["id", "questionCount"]
```

---

## 5. Enrollment serializers (two variants)

### 5.1 `EnrollmentReadSerializer` — for admin learner detail + reports

```python
class EnrollmentReadSerializer(serializers.ModelSerializer):
    """
    Why: Drives the "Qualification" column in AdminLearners.tsx and the
         enrolment list on the learner detail drawer.
    Where:
      - GET /api/learners/{id}/enrollments/  → AdminLearners detail drawer
      - GET /api/me/enrollments/             → LearnerDashboard top card
                                               ("You are enrolled on …")
    Flat shape matches the existing `Learner.qualificationName` field on
    the frontend so no UI rewrite is needed.
    """
    qualificationId = serializers.UUIDField(source="qualification.id", read_only=True)
    qualificationName = serializers.CharField(source="qualification.title", read_only=True)
    qualificationCode = serializers.CharField(source="qualification.code", read_only=True)

    class Meta:
        model = QualificationEnrollment
        fields = ["id", "qualificationId", "qualificationName", "qualificationCode",
                  "cohort", "employer", "status",
                  "enrolled_at", "expected_end_date",
                  "completed_at", "withdrawn_at", "withdrawal_reason"]
```

### 5.2 `EnrollmentWriteSerializer` — admin create/update

```python
class EnrollmentWriteSerializer(serializers.ModelSerializer):
    """
    Why: Separate writer enforces office rules:
         - Only learners (User.role='learner') can be enrolled.
         - One active enrolment per (learner, qualification, cohort).
         - Status transitions are gated (e.g. cannot go from 'completed' back
           to 'active' without admin override).
    Where:
      - POST  /api/enrollments/      → AdminLearners "Add Learner" form
                                        currently sets `qualificationId` — this
                                        endpoint replaces that flat field.
      - PATCH /api/enrollments/{id}/ → AdminLearners "Edit" + "Withdraw" actions
    """
    learner_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role="learner"), source="learner")
    qualification_id = serializers.PrimaryKeyRelatedField(
        queryset=Qualification.objects.filter(is_active=True), source="qualification")

    class Meta:
        model = QualificationEnrollment
        fields = ["learner_id", "qualification_id", "cohort", "employer",
                  "status", "enrolled_at", "expected_end_date",
                  "withdrawal_reason", "notes"]

    def validate(self, attrs):
        # Block duplicate active enrolment in same cohort
        qs = QualificationEnrollment.objects.filter(
            learner=attrs["learner"],
            qualification=attrs["qualification"],
            cohort=attrs.get("cohort", ""),
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Learner already enrolled on this qualification + cohort.")
        return attrs
```

---

## 6. Mapping table — UI screen → serializer

| Frontend screen | Endpoint | Serializer |
|---|---|---|
| `AdminQuestionBank.tsx` — qual dropdown | `GET /api/qualifications/?is_active=true` | `QualificationListSerializer` |
| `AdminQuestionBank.tsx` — bank header | `GET /api/qualifications/{id}/` | `QualificationDetailSerializer` (uses `bankHealth`) |
| `AdminExams.tsx` — qual dropdown | `GET /api/qualifications/?is_active=true` | `QualificationListSerializer` |
| `AdminExams.tsx` — create form pre-fill | `GET /api/qualifications/{id}/` | `QualificationDetailSerializer` (defaults) |
| `AdminLearners.tsx` — qual dropdown | `GET /api/qualifications/?is_active=true` | `QualificationListSerializer` |
| `AdminLearners.tsx` — add/edit learner | `POST /api/enrollments/` | `EnrollmentWriteSerializer` |
| `AdminLearners.tsx` — table "Qualification" col | inline on `LearnerSerializer` (other app) | `EnrollmentReadSerializer` (nested) |
| `AdminReports.tsx` — qual filter | `GET /api/qualifications/?is_active=true` | `QualificationListSerializer` |
| `LearnerDashboard.tsx` — "Your qualification" card | `GET /api/me/enrollments/` | `EnrollmentReadSerializer` |
| Admin "Sectors" settings (planned) | `CRUD /api/sectors/` | `SectorSerializer` |
| Admin "Levels" settings (planned) | `CRUD /api/levels/` | `LevelSerializer` |
| Question editor — unit picker | `GET /api/qualifications/{id}/units/` | `QualificationUnitSerializer` |

---

## 7. Performance notes for the DRF view layer

- `QualificationListSerializer` view → `select_related("sector")` + `annotate(question_count=Count("questions", filter=Q(questions__is_active=True)))`.
- `QualificationDetailSerializer` view → `select_related("sector", "level").prefetch_related("units")`.
- `EnrollmentReadSerializer` view → `select_related("qualification")`.
- All list endpoints support `?page_size=` and DRF's default cursor pagination — frontend dropdowns request `page_size=200` with `is_active=true`.

---

_Last updated: 2026-05-06 — Lead Edge Ltd EPAO Platform_
