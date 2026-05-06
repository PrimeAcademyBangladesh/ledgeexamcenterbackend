# Qualifications App — Data Dictionary

**Project:** Lead Edge Ltd EPAO Exam Platform
**Django app:** `apps/qualifications`
**Audience:** DRF backend developers, QA, content team

---

## Table of contents

1. [`Sector`](#1-sector) — admin-managed category
2. [`Level`](#2-level) — admin-managed RQF level
3. [`Qualification`](#3-qualification) — core qualification record
4. [`QualificationUnit`](#4-qualificationunit) — sub-topics within a qualification
5. [`QualificationEnrollment`](#5-qualificationenrollment) — Learner ↔ Qualification link
6. [Cross-reference: business rules](#6-cross-reference-where-each-rule-fires)
7. [Entity relationship summary](#7-entity-relationship-summary)

---

## 1. `Sector`

Admin-editable list of sectors. Replaces a hardcoded enum so the office can add new sectors without a code release.

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `id` | UUIDField (PK) | Stable PK, safe to expose in URLs | `/api/sectors/{id}/`, FK target from `Qualification.sector` |
| `name` | CharField(120) | Human label shown in UI | Admin → Qualifications list filter, Learner dashboard chip, Reports group-by |
| `code` | CharField(16, unique) | Stable machine code (e.g. `HSC`) for imports/exports | CSV exports, marksheet PDF header, API filtering (`?sector_code=HSC`) |
| `slug` | SlugField(unique) | SEO-friendly URL segment | `/qualifications/?sector=health-social-care` deep links |
| `sort_order` | PositiveIntegerField | Admin controls display order without renaming | All `Sector` dropdowns (Create Qualification form, filters) |
| `is_active` | BooleanField | Soft-disable a sector without deleting historical data | Hidden from new-qualification dropdowns; still resolvable on old records |
| `created_at` | DateTimeField (auto) | Audit trail | Admin audit log only |
| `updated_at` | DateTimeField (auto) | Audit trail | Admin audit log only |

---

## 2. `Level`

Admin-editable RQF level list. Same rationale as `Sector` — flexibility without code changes.

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `id` | UUIDField (PK) | Stable PK | FK target from `Qualification.level` |
| `name` | CharField(80) | Display label (e.g. "Level 3 Diploma") | Qualification cards, certificates, marksheet PDF |
| `numeric_value` | PositiveSmallIntegerField | Sortable/filterable numeric tier (1–8 RQF) | Reports → "All Level 3+ pass rates", ordering dropdowns |
| `is_active` | BooleanField | Soft delete | Hides from create-qualification form |
| `created_at` | DateTimeField (auto) | Audit | Admin audit log |
| `updated_at` | DateTimeField (auto) | Audit | Admin audit log |

---

## 3. `Qualification`

The core record. Drives exam configuration defaults, question-bank health, and resit rules.

### 3.1 Identity

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `id` | UUIDField (PK) | PK | All FK relationships, `/api/qualifications/{id}/` |
| `code` | CharField(40, unique) | EPAO/Ofqual reference (e.g. `LE-HSC-L3-001`); used in exports, certificates, audits | Marksheet PDF, CSV reports, ESFA returns, learner enrolment letters |
| `title` | CharField(200) | Human name | Everywhere a qualification is shown (dashboards, exam picker, results) |
| `slug` | SlugField(unique) | Public URL segment | `/qualifications/{slug}` (if public catalogue page added) |
| `sector` | FK → `Sector` (PROTECT) | Categorisation for filtering & analytics | Admin filters, Reports group-by sector, Learner browse |
| `level` | FK → `Level` (PROTECT) | RQF level grouping | Reports, certificates, eligibility checks |
| `description` | TextField (blank) | Long-form info for admins/learners | Qualification detail page, enrolment confirmation email |
| `is_active` | BooleanField | Hide from new exam creation without deleting | New exam creation form, learner enrolment dropdown |
| `created_at` / `updated_at` | DateTimeField (auto) | Audit | Admin audit log |

### 3.2 Default exam settings (inherited by `ExamConfig` on creation)

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `default_questions_per_exam` | PositiveIntegerField | Most exams for one qualification share the same length — saves admin time | Pre-fills `ExamConfig.questions_per_exam` in Create Exam form |
| `default_time_limit_minutes` | PositiveIntegerField | Same — consistency across exam versions | Pre-fills `ExamConfig.time_limit_minutes` |
| `default_pass_boundary` | PositiveSmallIntegerField (0–100) | Per-qualification grade scheme often differs from system default | Pre-fills `ExamConfig.grade_boundaries.pass`; also used in resit eligibility check |
| `default_merit_boundary` | PositiveSmallIntegerField (0–100) | Same | Pre-fills exam config |
| `default_distinction_boundary` | PositiveSmallIntegerField (0–100) | Same | Pre-fills exam config |

**Validation:** `pass < merit < distinction` (model `clean()`).

### 3.3 Question bank rules

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `min_bank_size` | PositiveIntegerField | Health check — refuse to publish exam if bank too shallow | Validation on `ExamConfig.publish()`, Admin dashboard warning badge ("Bank low: 42/100") |
| `recommended_bank_size` | PositiveIntegerField | Target for content team | Admin question-bank page progress bar |

### 3.4 Resit policy (drives PIN + question selection logic)

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `resit_unseen_ratio` | DecimalField(3,2) (0–1) | Office mandates a % of fresh questions on every resit (fairness + integrity) | `ExamSession.create_resit()` → question selection algorithm; rejects resit if insufficient unseen |
| `resit_fail_margin_percent` | PositiveSmallIntegerField | Auto-eligibility for resit if learner failed by ≤ X% (no extra approval) | `RetakeRequest.auto_approve()` check; learner dashboard "Request resit" button visibility |
| `max_resit_attempts` | PositiveSmallIntegerField | Office cap (typically 2 resits) | Blocks 4th attempt at session creation; learner dashboard message |
| `resit_cooldown_days` | PositiveSmallIntegerField | Mandatory wait before retaking | `ExamSession.create_resit()` validation; shown on learner "Request resit" screen |

---

## 4. `QualificationUnit`

Optional sub-topic breakdown. Powers per-unit analytics and proportional question sampling.

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `id` | UUIDField (PK) | PK | FK target from `Question.units` (M2M) |
| `qualification` | FK → `Qualification` (CASCADE) | Scopes unit to its qualification | Admin question editor unit picker (filtered by qual) |
| `code` | CharField(20) | Stable reference for spec mapping (e.g. `U1.2`) | Marksheet PDF "Performance by unit" table, CSV exports |
| `title` | CharField(200) | Display label | Question editor, analytics charts |
| `description` | TextField (blank) | Spec text for content team | Admin unit management page only |
| `weight` | DecimalField(4,2) | Some units carry more marks/coverage than others | **Question selection algorithm** — proportional sampling per unit; analytics weighting |
| `sort_order` | PositiveIntegerField | Display ordering | Unit lists in admin + reports |

**Constraint:** `unique_together = ('qualification', 'code')`.

---

## 5. `QualificationEnrollment`

Learner ↔ Qualification link. One row per learner per qualification per cohort.

| Field | Type | Why it exists | Where it is used |
|---|---|---|---|
| `id` | UUIDField (PK) | PK | `/api/enrollments/{id}/` |
| `learner` | FK → `User` (CASCADE, role=learner) | Who is enrolled | Learner dashboard, Admin learner detail |
| `qualification` | FK → `Qualification` (PROTECT) | What they are enrolled on | Exam picker (only shows quals learner is enrolled in), reports |
| `cohort` | CharField(40) | Group reporting + employer batching (e.g. `2026-Spring`) | Reports group-by cohort, CSV exports, ESFA returns |
| `employer` | CharField(200, blank) | Apprenticeship employer for ESFA reporting | Reports, marksheet PDF, invoicing |
| `status` | CharField (choices: active / withdrawn / completed / suspended) | Lifecycle without deleting record | Blocks new exam booking if not `active`; reports filter; learner dashboard banner |
| `enrolled_at` | DateField | Start date for funding/progress tracking | Reports, ESFA returns |
| `expected_end_date` | DateField (null) | Planning + alerts for overdue learners | Admin dashboard "Overdue" widget |
| `completed_at` | DateField (null) | Set when learner passes final exam | Triggers certificate generation; reports |
| `withdrawn_at` | DateField (null) | Audit + ESFA reporting | Reports, audit log |
| `withdrawal_reason` | TextField (blank) | Audit trail | Admin learner detail page, reports |
| `notes` | TextField (blank) | Free-form admin notes | Admin learner detail page only |
| `created_at` / `updated_at` | DateTimeField (auto) | Audit | Admin audit log |

**Constraint:** `unique_together = ('learner', 'qualification', 'cohort')`.

---

## 6. Cross-reference: where each rule fires

| Business rule | Source field(s) | Trigger point |
|---|---|---|
| "Cannot publish exam — bank too small" | `Qualification.min_bank_size` vs question count | `ExamConfig.publish()` API |
| "Auto-approve resit (failed by ≤ margin)" | `resit_fail_margin_percent` + `default_pass_boundary` | `RetakeRequest.create()` |
| "Block resit — cooldown not elapsed" | `resit_cooldown_days` + last `ExamResult.submitted_at` | `ExamSession.create_resit()` |
| "Block resit — max attempts reached" | `max_resit_attempts` vs `ExamResult.attempt_number` | `ExamSession.create_resit()` |
| "Resit must contain X% unseen Qs" | `resit_unseen_ratio` + `LearnerSeenQuestion` | Question selection in `ExamSession.create()` |
| "Hide qualification from new bookings" | `Qualification.is_active` | Create Exam form, Learner enrolment form |
| "Learner cannot book exam" | `QualificationEnrollment.status != 'active'` | `ExamSession.create()` validation |
| "Proportional question sampling per unit" | `QualificationUnit.weight` | Question selection algorithm |
| "Per-unit performance breakdown" | `QualificationUnit` + `Question.units` M2M | Marksheet PDF, learner result page |
| "Cohort/employer reports" | `QualificationEnrollment.cohort`, `.employer` | Admin Reports page |
| "Pre-fill new exam form" | `Qualification.default_*` fields | `POST /api/exams/` (server-side merge) |

---

## 7. Entity relationship summary

```
Sector (1) ──────────┐
                     ├──< Qualification (N) ──< QualificationUnit (N)
Level  (1) ──────────┘            │
                                  │
                                  ├──< QualificationEnrollment (N) >── User (Learner)
                                  │
                                  └──< ExamConfig (N)        [apps/exams]
                                                │
                                                └──< ExamSession (N)
```

- **PROTECT** on `Qualification.sector`, `Qualification.level`, `QualificationEnrollment.qualification` — prevents accidental deletion of records that have history.
- **CASCADE** on `QualificationUnit.qualification`, `QualificationEnrollment.learner` — children are meaningless without parent.

---

_Last updated: 2026-05-06 — Lead Edge Ltd EPAO Platform_
