# `apps.invigilators`

Augments the `users` app with invigilator-specific operational data and
exposes the REST API consumed by:

- **Admin dashboard** — `/admin/invigilators` (list, register, edit,
  activate/deactivate, view assigned sessions).
- **Invigilator dashboard** — `/invigilator/dashboard` (lists assigned
  exam sessions for the logged-in user via `me/sessions`).
- **Admin → Exams "Assign invigilator" picker** — uses
  `/api/invigilators/?isActive=true` and `by-code/{code}/` lookup.

## Models

| Model                       | Purpose                                          |
| --------------------------- | ------------------------------------------------ |
| `ProviderCentre`            | Test centre / training-provider record           |
| `InvigilatorProviderLink`   | M2M for invigilators across multiple centres     |
| `InvigilatorAvailability`   | Weekly availability windows                      |

User account + `StaffProfile` (with `provider_code`) are still owned by the
`users` app — this app deliberately does **not** duplicate that data.

## Endpoints

```
GET    /api/invigilators/
POST   /api/invigilators/
GET    /api/invigilators/{id}/
PATCH  /api/invigilators/{id}/
DELETE /api/invigilators/{id}/                 -> soft delete (is_active=False)
POST   /api/invigilators/{id}/activate/
POST   /api/invigilators/{id}/deactivate/
POST   /api/invigilators/{id}/resend-welcome/
GET    /api/invigilators/by-code/{code}/

GET    /api/invigilators/me/sessions/          (invigilator only)
GET    /api/invigilators/me/availability/      (invigilator only)
POST   /api/invigilators/me/availability/

GET    /api/provider-centres/
POST   /api/provider-centres/                  (admin)
GET    /api/provider-centres/{id}/
PATCH  /api/provider-centres/{id}/             (admin)
DELETE /api/provider-centres/{id}/             -> soft delete (admin)
```

## Wire-up

`config/urls.py`:
```python
path("api/", include("apps.invigilators.urls")),
```

`config/settings.py` → `INSTALLED_APPS`:
```python
"apps.invigilators",
```

## Frontend ↔ Backend field map

| Frontend (`Invigilator`) | Backend source                          |
| ------------------------ | --------------------------------------- |
| `id`                     | `User.id` (UUID)                        |
| `firstName` / `lastName` | `User.first_name` / `last_name`         |
| `email`                  | `User.email`                            |
| `providerCode`           | `StaffProfile.provider_code`            |
| `isActive`               | `User.is_active`                        |
| `createdAt`              | `User.date_joined`                      |

## Cross-app dependencies

- **`users`** — `User`, `Role`, `StaffProfile`, `post_save` signal that
  creates `StaffProfile` automatically on new invigilator accounts.
- **`exams`** (lazy import in `views.my_sessions`) — `ExamSession` records.
  Failing import is tolerated so this app boots independently.
