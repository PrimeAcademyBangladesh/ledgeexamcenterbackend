# Frontend Integration Guide — Qualifications App

**Project:** Lead Edge Ltd EPAO Exam Platform
**Pairs with:** `qualifications-data-dictionary.md`, `qualifications-serializers.md`, `qualifications-views.md`
**Audience:** React frontend developers wiring screens to the live DRF API

---

## TL;DR — what changed and what to do

| Today (mock) | Tomorrow (live DRF) | Action |
|---|---|---|
| `questionService.listQualifications()` returns flat list | `qualificationService.list()` (same shape) | **Find/replace import.** No UI change. |
| `questionService.createQualification({ title, code, sector: "Business" })` | `qualificationService.create({ sector_id, level_id, ... })` | **Migrate** — sector is now a UUID. Need a sector picker. |
| `Learner.qualificationId` (flat field on user) | `QualificationEnrollment` row | **Split form save** into 2 calls: `learnerService.register` then `enrollmentService.create`. |
| `AdminExams` form hardcodes `questionsPerExam: 40, timeLimitMinutes: 60` | Pre-fill from `qualificationService.getDetail(id).default_*` | **On qualification select**, fetch detail → patch form state. |
| `AdminQuestionBank` shows raw question count | `qualificationService.getBankHealth(id)` returns `{ current, target, min, percent, status }` | **Add health badge** with green/amber/red. |
| Hardcoded `Sector` enum | `qualificationService.listSectors()` | **Replace dropdown** in any qualification create form. |
| No resit policy in UI | `QualificationDetail.resit_fail_margin_percent` etc. | **Admin-only** — never render for learners. |

---

## File-by-file migration plan

### 1. `src/pages/admin/AdminExams.tsx`

**Today (lines 18–29):**
```ts
const defaultForm: CreateExamRequest = {
  ...
  questionsPerExam: 40,        // ❌ hardcoded
  timeLimitMinutes: 60,        // ❌ hardcoded
  gradeBoundaries: { distinction: 85, merit: 70, pass: 60 },  // ❌ hardcoded
};
```

**Migration:**
```ts
import { qualificationService } from "@/services/api/qualifications";

// When user selects a qualification in the Create Exam dialog:
const onQualSelect = async (qualId: string) => {
  const detail = await qualificationService.getDetail(qualId);
  setForm(f => ({
    ...f,
    qualificationId: qualId,
    questionsPerExam: detail.default_questions_per_exam,
    timeLimitMinutes: detail.default_time_limit_minutes,
    gradeBoundaries: {
      pass: detail.default_pass_boundary,
      merit: detail.default_merit_boundary,
      distinction: detail.default_distinction_boundary,
    },
  }));
};
```

Also: replace `questionService.listQualifications()` on line 40 with `qualificationService.list()`.

---

### 2. `src/pages/admin/AdminLearners.tsx`

**Today (handleSave around line 175–200):** creates the learner with a flat `qualificationId`.

**Migration — two-step save:**
```ts
import { enrollmentService } from "@/services/api/qualifications";

const handleSave = async () => {
  // 1. Create the user
  const learner = await learnerService.register({
    firstName: form.firstName,
    lastName: form.lastName,
    email: form.email,
    uln: form.uln,
    password: defaultPassword,
  });

  // 2. Enrol them on the qualification
  await enrollmentService.create({
    learnerId: learner.id,
    qualificationId: form.qualificationId,
    cohort: currentCohort,                 // NEW field — add to form
    employer: form.employer ?? "",         // NEW optional field
    enrolledAt: new Date().toISOString().slice(0, 10),
  });
};
```

**Add to the form:** `cohort` text input (e.g. `2026-Spring`) and optional `employer` field.
**Withdraw button:** call `enrollmentService.withdraw(enrollmentId)` instead of toggling `isActive`.

---

### 3. `src/pages/admin/AdminQuestionBank.tsx`

**Today:** raw question count next to the qualification name.

**Migration — add bank health badge:**
```tsx
import { qualificationService, type BankHealth } from "@/services/api/qualifications";

const [health, setHealth] = useState<BankHealth | null>(null);

useEffect(() => {
  if (!selectedQual) return;
  qualificationService.getBankHealth(selectedQual).then(setHealth);
  const t = setInterval(() => qualificationService.getBankHealth(selectedQual).then(setHealth), 30_000);
  return () => clearInterval(t);
}, [selectedQual]);

{health && (
  <Badge variant={
    health.status === "healthy" ? "default" :
    health.status === "warning" ? "secondary" : "destructive"
  }>
    Bank: {health.current}/{health.target} ({health.percent}%)
  </Badge>
)}
```

Also: replace the inline `qualForm` create modal (line 42 onward) — it currently posts `{ title, code, sector: "Business" }` which the DRF serializer will reject. Either disable the modal until a proper sector picker is added, or redirect to a new `AdminQualificationCreate` page.

---

### 4. `src/pages/admin/AdminReports.tsx`

**Today (line 43, 60):**
```ts
if (filterQual !== "all" && r.qualificationName !== filterQual) return false;
```
filtering by `qualificationName` is fragile (string match). Switch to ID.

**Migration:**
```ts
// Filter dropdown stores qualificationId, compare with r.qualificationId
{qualifications.map(q => (
  <SelectItem key={q.id} value={q.id}>{q.title}</SelectItem>
))}
// In filter:
if (filterQual !== "all" && r.qualificationId !== filterQual) return false;
```

Requires `ExamResult` to expose `qualificationId` — already in the type, just unused.

---

### 5. `src/pages/learner/LearnerDashboard.tsx`

**Add a top card** showing the learner's enrolment(s):
```tsx
import { enrollmentService } from "@/services/api/qualifications";

const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
useEffect(() => { enrollmentService.listMine().then(setEnrollments); }, []);

{enrollments.map(e => (
  <Card key={e.id}>
    <CardHeader><CardTitle>{e.qualificationName}</CardTitle></CardHeader>
    <CardContent>
      <p>Cohort: {e.cohort}</p>
      <p>Status: <Badge>{e.status}</Badge></p>
    </CardContent>
  </Card>
))}
```

**Important:** never call `qualificationService.getDetail()` from a learner screen — that endpoint is admin/invigilator only and exposes resit thresholds.

---

### 6. New screens to build

| Screen | Route | Calls |
|---|---|---|
| Sector management | `/admin/settings/sectors` | `listSectors`, `createSector`, `updateSector` |
| Level management | `/admin/settings/levels` | `listLevels` + create/update |
| Qualification list | `/admin/qualifications` | `qualificationService.list()` |
| Qualification create/edit | `/admin/qualifications/new` and `/admin/qualifications/:id` | `getDetail`, `create`, `update` |
| Unit management | inside qualification edit page | `listUnits` + nested CRUD |
| Bulk learner import | `/admin/learners/import` | `enrollmentService.bulkImport(file)` |

---

## Type-system changes (`src/services/api/types.ts`)

Add (or import from `qualifications.ts`):

```ts
// Replace the flat `sector: string` field on Qualification with a normalized shape
export interface Qualification {
  id: string;
  title: string;
  code: string;
  sector: string;          // keep for backward-compat in list shape
  questionCount: number;
  isActive: boolean;
  createdAt: string;
}
```

Re-export `Sector`, `Level`, `QualificationDetail`, `QualificationUnit`,
`Enrollment` from `qualifications.ts` to keep the import surface clean.

Remove the flat `qualificationId` from `Learner` once `EnrollmentReadSerializer`
is wired — replace with `enrollments: Enrollment[]` returned by the learner
detail endpoint.

---

## Migration checklist (in order)

1. ☐ Add `qualifications.ts` service file (done — see this commit).
2. ☐ Build `Sector` and `Level` admin pages so admins can populate the lists.
3. ☐ Build `Qualification` admin CRUD page.
4. ☐ Migrate `AdminExams` to pre-fill defaults from `getDetail()`.
5. ☐ Migrate `AdminQuestionBank` to use `getBankHealth()` and remove inline qual-create modal.
6. ☑ Migrated `AdminLearners` to two-step save (learner + enrollment) with cohort/employer fields.
7. ☑ Migrated `AdminReports` to filter by `qualificationId` instead of name.
8. ☑ Added enrolment card to `LearnerDashboard`.
9. ☐ Delete deprecated `questionService.listQualifications` / `createQualification`.

---

## How to find the right service method

Every method in `src/services/api/qualifications.ts` has a `🔌 WIRE INTO:` comment listing the screen(s) it powers. In your IDE, hover the method name or `Ctrl+Click` to see the exact call sites and HTTP endpoint.

To find all places that still need wiring:
```bash
rg "questionService\.listQualifications|questionService\.createQualification" src/
```

---

_Last updated: 2026-05-06 — Lead Edge Ltd EPAO Platform_
