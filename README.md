# Lead Edge Ltd — Architecture Plan

The API/backend advice has been merged into the single source of truth:

`src/services/api/API_CONTRACTS.md`

Use that document for the DRF backend build, endpoint payloads, response shapes, auth rules, PIN handling, autosave drafts, resume flow, resit eligibility, and question-bank generation requirements.

Latest backend guidance added:

- Create `ExamSession` server-side only.
- Select random unseen questions from the qualification question bank.
- Save selected IDs into `ExamSession.question_set` as a frozen paper.
- Mark selected questions as seen immediately via `LearnerSeenQuestion`.
- For resits, exclude all previously seen questions and block the resit if not enough fresh questions exist.

backend/
├── manage.py
├── requirements.txt
├── .env
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── apps/
│   ├── __init__.py
│   │
│   ├── accounts/                  # App 1: Auth & Users
│   │   ├── models.py              # User (custom), Role
│   │   ├── managers.py
│   │   ├── serializers.py
│   │   ├── views.py               # Login, Refresh, Me, Logout
│   │   ├── permissions.py         # IsAdmin, IsInvigilator, IsLearner
│   │   ├── urls.py
│   │   ├── admin.py
│   │   └── tests.py
│   │
│   ├── learners/                  # App 2: Learner profiles
│   │   ├── models.py              # Learner (ULN, qualification FK)
│   │   ├── serializers.py
│   │   ├── views.py               # CRUD + register
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── invigilators/              # App 3: Invigilator profiles
│   │   ├── models.py              # Invigilator (provider_code)
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── qualifications/            # App 4: Qualifications
│   │   ├── models.py              # Qualification
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── questions/                 # App 5: Question Bank
│   │   ├── models.py              # Question, QuestionOption, LearnerSeenQuestion
│   │   ├── serializers.py         # Admin + ExamQuestion (no answers)
│   │   ├── views.py               # CRUD, bulk import
│   │   ├── services.py            # pick_unseen_questions()
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── exams/                     # App 6: Exam configs
│   │   ├── models.py              # ExamConfig, GradeBoundaries
│   │   ├── serializers.py
│   │   ├── views.py               # CRUD + publish
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── sessions/                  # App 7: Exam Sessions / PIN / Drafts
│   │   ├── models.py              # ExamSession, ExamDraft
│   │   ├── serializers.py
│   │   ├── views.py               # schedule, validate_pin, save_draft, submit
│   │   ├── services.py            # generate_pin, freeze_paper, autosave
│   │   ├── permissions.py
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── results/                   # App 8: Results & Grading
│   │   ├── models.py              # ExamResult, IntegrityViolation
│   │   ├── serializers.py
│   │   ├── views.py               # list, detail, marksheet PDF
│   │   ├── services.py            # grade_attempt(), compute_score()
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── retakes/                   # App 9: Retake / Resit Requests
│   │   ├── models.py              # RetakeRequest
│   │   ├── serializers.py
│   │   ├── views.py               # request, approve, deny
│   │   ├── services.py            # check_resit_eligibility()
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── adjustments/               # App 10: Reasonable Adjustments
│   │   ├── models.py              # ReasonableAdjustment
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── integrity/                 # App 11: Anti-cheat / Violations
│   │   ├── models.py              # IntegrityViolation log
│   │   ├── serializers.py
│   │   ├── views.py               # report_violation
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── reports/                   # App 12: Reporting & Analytics
│   │   ├── serializers.py
│   │   ├── views.py               # aggregate stats, CSV/PDF export
│   │   ├── services.py
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   ├── settings_app/              # App 13: System Settings
│   │   ├── models.py              # SystemSettings (singleton), OrgBranding
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── tests.py
│   │
│   └── core/                      # App 14: Shared utilities
│       ├── pagination.py
│       ├── permissions.py
│       ├── exceptions.py
│       ├── mixins.py
│       ├── validators.py
│       └── middleware.py
│
├── media/                         # uploads (question images, logo)
├── static/
├── templates/
│   └── pdf/
│       └── marksheet.html
└── tests/
    └── integration/