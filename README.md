# Clinic Booking API

REST API for a small clinic (5 doctors) where patients view free 30-minute slots, book, cancel and reschedule appointments. Built with **FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL**, tested with **pytest** against real Postgres, deployed on **Render** with **GitHub Actions** CI/CD.

- **Live URL:** `https://clinic-booking-api-0uyy.onrender.com/` (interactive docs at `/docs`)
- **Repo:** https://github.com/Imman9/clinic-booking-api
- **Deploy branch:** `main`

**Contents:** [1. System design](#1-system-design) · [2. Running and using the API](#2-running-and-using-the-api) · [3. Deployment and CI/CD](#3-deployment-and-cicd) · [4. AI reflection](#4-ai-reflection)

---

## 1. System design

### 1.1 Scope

One clinic, 5 doctors, fixed 30-minute slots. Patients can see a doctor's free slots for a date, book one, cancel with a reason, and reschedule. The system must stay correct under concurrent bookings and be able to grow (more doctors, more clinics, time off, notifications) without a rewrite.

### 1.2 Components

| Layer | Responsibility |
|---|---|
| **Routers** (`app/routers/`) | HTTP only: parse requests, call a service, map results and domain errors to status codes. |
| **Services** (`app/services/`) | All booking rules: slot generation, working-hours check, past check, lead-time buffer, conflict handling. No HTTP knowledge, so it is unit-testable directly. |
| **Models / DB** (`app/models.py`, Alembic) | SQLAlchemy models, migrations, and the database constraints that act as the final concurrency guard. |
| **PostgreSQL** | Single source of truth. It also decides who wins a race. |

### 1.3 Data model

```
doctors        (id, name, specialization)
patients       (id, name, contact)
working_hours  (id, doctor_id -> doctors, day_of_week 0=Mon..6=Sun,
                start_time, end_time)           -- weekly recurring template
appointments   (id, doctor_id -> doctors, patient_id -> patients,
                start_time timestamptz, end_time timestamptz,
                status BOOKED | CANCELLED,
                cancel_reason, cancelled_at,
                created_at, updated_at)
```

- `working_hours` is a **weekly template**, not per-day rows. A doctor can have several blocks on one weekday (for example 08:00-12:00 and 14:00-17:00), which gives lunch breaks without any schema change.
- Working-hour times are **clinic-local wall-clock times** (see 1.6). Appointment times are stored as UTC `timestamptz`.
- A `CHECK (end_time > start_time)` on `working_hours`, and `end_time = start_time + 30 min` enforced in the service.

### 1.4 The key constraint: no double booking

```sql
CREATE UNIQUE INDEX uniq_active_slot
ON appointments (doctor_id, start_time)
WHERE status = 'BOOKED';
```

- Two **booked** rows cannot share a doctor and start time. A **cancelled** row does not block the slot, so cancelling frees it automatically. There is no separate "release slot" step to forget.
- The service runs a friendly pre-check so most conflicts get a clean message, but **the index is the real guarantee**. Two concurrent requests can both pass an application-level check; the second one fails at commit with `IntegrityError`, which the API maps to **409 Conflict**.
- Because slots are always aligned to the 30-minute grid and slot length is fixed, "same start time" is equivalent to "overlapping". If variable slot lengths are added later, this becomes an exclusion constraint on a time range (see 1.9).
- An index on `(patient_id, start_time)` supports the patient-appointments endpoint.

### 1.5 Booking rules and validation order

For a booking (and for the target of a reschedule), checks run in this order, so the error a client sees is predictable:

1. Doctor or patient does not exist: **404**
2. `start_time` has no timezone offset: **422**
3. Not on a 30-minute boundary: **422**
4. In the past: **422**
5. Less than `BOOKING_BUFFER_MINUTES` (default 60) from now: **422**
6. Outside the doctor's working hours for that weekday (evaluated in clinic time): **422**
7. Slot already taken: **409** (pre-check, then the index as the final word)

**Availability** for a doctor on a clinic-local date: take that weekday's working-hour blocks, cut them into 30-minute slots, remove slots that start in the past or inside the buffer, remove slots already `BOOKED`. Nothing is stored; cancelled or rescheduled slots reappear automatically.

**Reschedule** runs in a single transaction on the same row. The new slot is validated like a fresh booking, except the appointment's own current slot is excluded from the "already taken" check. If the new slot is taken, the index rejects the update, the transaction rolls back, and the original booking is untouched.

### 1.6 Time and timezones

- The clinic timezone is configurable (`CLINIC_TIMEZONE`, default `Africa/Nairobi`, UTC+3, no DST).
- Clients must send ISO-8601 datetimes **with an offset** (`+03:00` or `Z`). Naive datetimes are rejected with 422, because guessing the timezone is how booking bugs happen.
- Working hours are interpreted in clinic time. So `09:30Z` is 12:30 in Nairobi and is checked against the doctor's hours as 12:30, not 09:30.
- The `date` for availability is a **clinic-local calendar date**. Responses return times in clinic time with the offset included.
- Everything is stored and compared in UTC internally.

### 1.7 Decisions and trade-offs

| Decision | Chosen | Alternative considered | Why / trade-off |
|---|---|---|---|
| Slots | Computed on read from working hours minus bookings | Pre-generated `slots` table | No generation jobs, no drift when hours change. Cost: recomputed per request, negligible at 5 doctors. Cache per (doctor, day) later if needed. |
| Concurrency | Partial unique index + map `IntegrityError` to 409 | App locks or `SELECT ... FOR UPDATE` | Correct across multiple app instances with no extra infrastructure. Cost: Postgres-specific, which is why tests also run on Postgres. |
| Cancel | Soft cancel (status + reason + timestamp) | Delete the row | Keeps history; the index ignores cancelled rows so the slot reopens. |
| Reschedule | Update the same row in one transaction | Cancel + insert a new row | Keeps one appointment identity for the patient and is atomic. **Trade-off:** the previous time is overwritten, so there is no history of moves. Growth path: an append-only `appointment_events` table. |
| Time | UTC storage, clinic-local rules | Naive local times | Avoids offset bugs and keeps multi-clinic growth open. |
| Database | PostgreSQL | SQLite | Partial indexes, real transactions, and the same engine locally, in CI and in production. |
| Sync vs async | Synchronous SQLAlchemy | Async SQLAlchemy | Simpler sessions and tests; no real benefit at this scale. Async is a later optimisation. |
| Migrations | Alembic everywhere | `create_all()` on startup | The partial index and schema changes are versioned and identical in every environment. |

### 1.8 Assumptions (ambiguities I resolved)

1. Slot length is fixed at 30 minutes; a booking's `start_time` must sit on a 30-minute boundary.
2. "In the past" means `start_time <= now`; the bonus rule also requires at least 60 minutes of lead time (`BOOKING_BUFFER_MINUTES`). It applies to booking and to the reschedule target.
3. Unknown doctor or patient returns **404**. A doctor with no hours that day returns **200** with an empty list, because "no slots" is a valid answer and "no such doctor" is not.
4. Cancelling an already cancelled appointment returns **409**, not an idempotent 200. The brief says to return an error.
5. Rescheduling a cancelled appointment returns **409**. Rescheduling to the slot it already holds returns **422** (no-op).
6. Reschedule is for the **same doctor** only. Changing doctor means cancel plus a new booking.
7. A cancellation reason is required and non-empty.
8. There is no cancellation cutoff window; a patient can cancel any time before the appointment.
9. `GET /patients/{id}/appointments` returns **upcoming, non-cancelled** appointments sorted by start time ascending.
10. **No authentication.** `patient_id` is passed in the request. Real auth (JWT, patient-scoped access, doctor/admin roles) is the first next step.

### 1.9 Growth path

- **More clinics:** add `clinic_id` to doctors and working hours, and a timezone per clinic. The uniqueness index is unchanged.
- **Doctor time off and holidays:** an `availability_exceptions` table subtracted during slot generation.
- **Variable appointment lengths:** store duration per appointment type, and replace the unique index with a Postgres exclusion constraint on `tstzrange(start_time, end_time)`.
- **Read load:** cache availability per (doctor, day); invalidate on book, cancel, reschedule.
- **Notifications:** emit events (booked, cancelled, rescheduled) to a queue for SMS or email reminders.
- **Audit history:** an append-only `appointment_events` table.
- **Auth and roles:** patient, doctor, admin.

---

## 2. Running and using the API

### 2.1 Run locally

```bash
cp .env.example .env
docker compose up --build        # API on http://localhost:8000, Postgres included
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed   # 5 doctors, working hours, sample patients
```

Interactive docs: `http://localhost:8000/docs`

Without Docker (you need a local Postgres):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/clinic
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload
```

### 2.2 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | none (required) | Postgres connection string |
| `CLINIC_TIMEZONE` | `Africa/Nairobi` | Timezone used for working hours and the availability `date` |
| `BOOKING_BUFFER_MINUTES` | `60` | Minimum lead time before a booking or reschedule target |

### 2.3 Endpoints

| Method and path | Purpose | Success |
|---|---|---|
| `GET /doctors/{id}/availability?date=YYYY-MM-DD` | Free 30-minute slots for that clinic-local date | 200 |
| `POST /appointments` | Book a slot (`doctor_id`, `patient_id`, `start_time`) | 201 |
| `PATCH /appointments/{id}/cancel` | Cancel with a `reason` | 200 |
| `PATCH /appointments/{id}/reschedule` | Move to `new_start_time` (same doctor) | 200 |
| `GET /patients/{id}/appointments` | Upcoming, non-cancelled appointments sorted by date (bonus) | 200 |

### 2.4 Status codes and error format

| Code | When |
|---|---|
| 200 / 201 | Success / appointment created |
| 404 | Doctor, patient or appointment not found |
| 409 | Slot already taken; appointment already cancelled; rescheduling a cancelled appointment |
| 422 | Invalid input: naive datetime, off the 30-minute grid, in the past, inside the lead-time buffer, outside working hours, missing reason, no-op reschedule |

All errors, including FastAPI's own request validation errors, share one shape:

```json
{ "error": { "code": "SLOT_TAKEN", "message": "Dr. Achieng already has an appointment at 2026-11-02T09:00:00+03:00." } }
```

### 2.5 Quick tour

```bash
DAY=$(date -d "next monday" +%F)      # GNU date. On macOS: date -v+mon +%F

# 1. free slots
curl "http://localhost:8000/doctors/1/availability?date=$DAY"

# 2. book 09:00 clinic time (note the +03:00 offset)
curl -X POST http://localhost:8000/appointments -H "Content-Type: application/json" \
  -d "{\"doctor_id\":1,\"patient_id\":1,\"start_time\":\"${DAY}T09:00:00+03:00\"}"

# 3. booking the same slot again -> 409
# 4. reschedule
curl -X PATCH http://localhost:8000/appointments/1/reschedule -H "Content-Type: application/json" \
  -d "{\"new_start_time\":\"${DAY}T11:00:00+03:00\"}"

# 5. cancel (slot becomes bookable again)
curl -X PATCH http://localhost:8000/appointments/1/cancel -H "Content-Type: application/json" \
  -d '{"reason":"Patient unwell"}'

# 6. upcoming appointments for a patient
curl "http://localhost:8000/patients/1/appointments"
```

### 2.6 Project layout

```
app/
├── main.py            # app factory, domain error -> HTTP mapping
├── config.py          # env-driven settings
├── database.py        # engine and session
├── models.py          # SQLAlchemy models + partial unique index
├── schemas.py         # Pydantic request/response models
├── exceptions.py      # DomainError hierarchy (404 / 409 / 422)
├── seed.py            # 5 doctors, working hours, sample patients
├── routers/           # thin HTTP layer
└── services/          # business logic (slots.py, appointments.py)
alembic/               # migrations
tests/                 # pytest suite
.github/workflows/     # CI/CD
```

### 2.7 Tests

```bash
docker compose up -d db
TEST_DATABASE_URL=postgresql+psycopg://... pytest -v
```

Tests run against **real PostgreSQL**, not SQLite, because the concurrency guarantee depends on a Postgres partial unique index. Coverage:

- Booking: happy path; outside working hours; in the past; inside the 1-hour buffer; off-grid time; naive datetime; unknown doctor or patient.
- **Concurrency:** two simultaneous bookings of the same slot; exactly one succeeds and the other gets 409.
- Cancel: requires a reason; second cancel returns 409; the slot is bookable again afterwards.
- Reschedule: success frees the old slot; target validated like a fresh booking; taken target returns 409 and leaves the original intact; cancelled appointment returns 409; same-slot returns 422.
- Availability: excludes booked, past and in-buffer slots; empty list on a non-working day; honours the Nairobi timezone.
- Patient list: upcoming only, sorted, excludes cancelled.

---

## 3. Deployment and CI/CD

- **Public URL:**: `https://clinic-booking-api-0uyy.onrender.com/`
- **Host:** Render web service built from the repo's `Dockerfile`, with a managed PostgreSQL instance (`DATABASE_URL` set as an environment variable).
- **Deploy branch:** `main`. Merging a pull request into `main` triggers a deployment.

### Pipeline (`.github/workflows/ci.yml`)

1. **On every pull request to `main`:** start a Postgres service container, install dependencies, run `pytest -v`.
2. **On push to `main` (that is, a merge):** the same test job runs first. A second `deploy` job that `needs: test` calls the Render deploy hook (`RENDER_DEPLOY_HOOK_URL` repository secret). If tests fail, nothing deploys.
3. Render's own auto-deploy is turned **off**, so the hook is the only deploy path and it can only fire after passing tests.
4. On container start, the Dockerfile command runs `alembic upgrade head` and then Uvicorn, so the schema is always current after a deploy.

---

## 4. AI reflection
### 1. How I Used AI Across the Four Sections

- **Section 1: Design**  
  I used AI as a sounding board to pressure-test my data model choices (`Doctor`, `WorkingHours`, `Patient`, and `Appointment`) and identify potential edge cases, including cancelled-slot reuse, timezone boundaries, and concurrent bookings. I wrote the design document myself.

- **Section 2: API Implementation**  
  I used AI to scaffold boilerplate code, including Pydantic schemas, SQLAlchemy session configuration, Alembic configuration, and an initial draft of pytest fixtures. I reviewed and rewrote the booking and availability logic myself.

- **Section 3: Deployment and CI/CD**  
  I used AI to draft the GitHub Actions workflow, including a test job for pull requests and a deployment job for merges. I also used it to help debug Render environment configuration and `DATABASE_URL` issues.

- **Section 4: Final Review**  
  I used AI only to review the clarity of my written responses. The content and engineering decisions are my own.

### 2. An Example of AI Improving My Work

My initial approach to preventing double-booking was to check whether a time slot was available in the application and then insert the appointment. I asked AI:

> I'm building a FastAPI + PostgreSQL booking endpoint. Two requests for the same doctor and slot arrive at the same time. How can both pass my availability check, and how do I prevent it?

The response highlighted the **check-then-insert race condition**. Two concurrent requests could both pass the availability check before either request inserted its appointment.

The solution was to enforce uniqueness at the database level using a **partial unique index** on `(doctor_id, start_time)` for appointments whose status is `booked`. The API catches the resulting `IntegrityError` and returns `409 Conflict` when another request has already booked the same slot.

The application also enforces 30-minute appointments on the `:00` and `:30` grid. Under these rules, valid appointments for the same doctor can only be adjacent or share the same start time. The partial unique index prevents two booked appointments from sharing that start time, including when concurrent requests attempt the same booking.

This approach combines application-level validation with a database-enforced uniqueness guarantee without introducing additional locking logic. However, it does not prevent arbitrary overlapping time ranges if appointments are inserted directly into the database while bypassing the API's validation rules.

### 3. An Example of Incorrect AI Output and How I Caught It

AI initially generated a standard unique constraint:

```python
UniqueConstraint("doctor_id", "start_time")
```

Although this looked correct, it did not account for cancelled appointments. I discovered the issue while writing a test for the scenario where a patient cancels an appointment and another patient subsequently books the same slot. The test failed with an integrity error because the cancelled appointment still occupied the unique key.

I corrected the implementation by replacing the standard unique constraint with a partial unique index that applies only to booked appointments. I then added tests covering cancellation followed by rebooking and rescheduling into a slot freed by another cancellation.

I also identified an issue with the use of naive `datetime.now()` for validating whether a booking was in the past. Although this could work in my local environment, it could produce incorrect comparisons when the application runs on a server using a different timezone.

I addressed this by using timezone-aware datetimes, storing timestamps in UTC, and interpreting working hours in the `Africa/Nairobi` timezone.

These examples reinforced the importance of validating generated code against actual requirements and edge cases rather than assuming that plausible-looking code is correct.

### 4. Engineering Decisions I Made Independently

#### Decision 1: Compute Availability Instead of Storing Time Slots

I decided to calculate availability on demand from a doctor's working hours, excluding slots occupied by booked appointments, rather than creating and storing individual slot records in advance.

For an initial system supporting five doctors, this avoids maintaining a separate table of generated slots that would require additional storage, synchronization, and cleanup whenever working hours or bookings change.

Computing availability on demand keeps the implementation relatively simple while allowing the system to evolve. If query volume grows significantly, availability calculations could later be optimized using caching or materialized availability data.

I made this decision based on the expected scale of the system and the need to keep the initial implementation maintainable without introducing unnecessary complexity.

#### Decision 2: Define API Error Semantics

I independently chose the HTTP status codes used to communicate different failure scenarios:

| Status Code | Scenario |
| --- | --- |
| `422 Unprocessable Entity` | Business-rule violations, such as booking in the past, booking outside working hours, or cancelling an already-cancelled appointment. |
| `404 Not Found` | The requested doctor or appointment does not exist. |
| `409 Conflict` | The requested time slot has already been booked. |
| `422 Unprocessable Entity` | The request contains invalid input or fails schema validation. |

I made these decisions based on established API conventions and the expected behavior of client applications. The goal was to distinguish malformed requests, missing resources, business-rule violations, and booking conflicts so clients can respond appropriately to each failure.

### 5. Database Integrity and Future Improvements

The current implementation relies on application-level validation to enforce 30-minute appointment durations and restrict start times to the `:00` and `:30` grid. Combined with a partial unique index on `(doctor_id, start_time)` for booked appointments, this prevents overlapping bookings through the API under the defined scheduling rules.

However, the database does not currently have a PostgreSQL exclusion constraint that independently rejects overlapping time ranges. Direct database writes that bypass the API could therefore insert appointments with invalid durations or off-grid start times, potentially creating overlaps.

If stronger database-level protection becomes necessary, the next step would be to introduce a PostgreSQL **GiST exclusion constraint** on the doctor's identifier and appointment time range, restricted to booked appointments. This would allow PostgreSQL to reject overlapping intervals independently of the application entry point.

For the current scope, I chose the simpler implementation because the API enforces a fixed appointment duration and scheduling grid. The exclusion constraint remains a documented improvement for a future version that needs to protect against arbitrary overlapping intervals or writes from multiple independent systems.




