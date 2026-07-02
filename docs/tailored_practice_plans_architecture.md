# Tailored Practice Plans — Architecture

An SLP (doctor) builds an individualized **treatment course** for a patient: an
ordered set of exercise assignments, each targeting a specific phoneme (for the
drill games) and difficulty, with dosage and objective advancement criteria. The
patient works the plan; the doctor reviews progress and adjusts.

Grounded in the earlier deep-research (see git history / memory): SLP treatment
follows two intersecting hierarchies, progresses on **objective gates**, is
**individualized** to the child's sounds, and must push toward **carryover** to
spontaneous speech.

---

## 1. Design principles (from the research)

1. **Two hierarchies.** Linguistic: word → phrase → sentence → conversation.
   Situational/difficulty: easy → hard. A plan climbs both.
2. **Objective advancement gates.** Advance a step only when a fluency score
   holds above a threshold over N consecutive attempts (Lidcombe/GILCU model),
   with **doctor override**.
3. **Individualized by phoneme + difficulty** — exactly the axes your content is
   tagged on (`disfluency_phrase.target_phoneme`, `.difficulty`).
4. **Short, distributed dosage**; structured → unstructured fade.
5. **Carryover** — sequence from drills toward open-ended speech.

## 2. How your 5 exercises fit

| Exercise (`exercise_type`) | Phoneme-targetable? | Difficulty | Hierarchy rung |
|---|:---:|---|---|
| `REPEAT_AFTER_ME` | ✅ | E/M/H/TT | word/phrase (structured) |
| `READ_IT_LOUD` | ✅ | E/M/H/TT | sentence/passage (structured) |
| `STORY_TELLER` | ❌ | E/M/H | narrative (semi-structured) |
| `PICTURE_TALK` | ❌ | E/M/H | connected speech (semi-open) |
| `TALK_WITH_OLLIE` | ❌ | — | conversation (fully open) |

**Decision (locked):** a plan step targets a **phoneme only for RAM + Read It
Loud**; the open games are assigned by **difficulty/hierarchy only** (you can't
force a target sound on spontaneous speech).

---

## 3. Core concepts

```
PracticePlan            (doctor authors it for one patient)
   └── PlanItem[]       (one assigned exercise step: type + phoneme? + difficulty + dosage + gate)
          └── PlanItemAttempt[]   (one row per attempt the patient makes on that step)
```

- **Plan** = the container the SLP builds/reviews.
- **PlanItem** = a single assignment (e.g. "/s/ Read It Loud at MEDIUM, 5 reps/day,
  advance at 80% over 3 attempts"). Ordered by `sequence`.
- **PlanItemAttempt** = the plan's own progress log — records each attempt's score
  so the advancement engine and the doctor can see how the step is going. (RAM
  still writes its own `PracticeAttempt` for mastery; this is the *plan-scoped* log.)

---

## 4. Data model (3 new tables + 2 enums)

All inherit `AbstractEntity`. Reuses the existing `Difficulty` enum and the string
`exercise_type` values already used on `disfluency_phrase`.

```python
# app/models/practice_plan.py

class PlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"; ACTIVE = "ACTIVE"; COMPLETED = "COMPLETED"; ARCHIVED = "ARCHIVED"

class PlanItemStatus(str, enum.Enum):
    LOCKED = "LOCKED"; ACTIVE = "ACTIVE"; COMPLETED = "COMPLETED"


class PracticePlan(AbstractEntity):
    __tablename__ = "practice_plan"
    patient_detail_id: Mapped[int] = mapped_column(
        ForeignKey("patient_detail.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("doctor_details.id", ondelete="SET NULL"), nullable=True)  # author
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PlanStatus] = mapped_column(
        SAEnum(PlanStatus, name="plan_status_enum"), default=PlanStatus.DRAFT, index=True)
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    items: Mapped[list["PlanItem"]] = relationship(
        cascade="all, delete-orphan", order_by="PlanItem.sequence")


class PlanItem(AbstractEntity):
    __tablename__ = "plan_item"
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("practice_plan.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)   # order within the plan
    exercise_type: Mapped[str] = mapped_column(String(20))     # one of the 5 games

    # Targeting — phoneme only for RAM / READ_IT_LOUD; NULL for the open games.
    target_phoneme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    difficulty: Mapped[Difficulty | None] = mapped_column(
        SAEnum(Difficulty, name="difficulty_enum"), nullable=True)  # NULL for Talk with Ollie

    # Dosage: {"reps_per_session": 5, "frequency": "DAILY"|"WEEKLY", "times_per_week": 5}
    dosage: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Advancement gate: {"mode": "AUTO"|"MANUAL", "metric": "fluency_score",
    #                    "threshold": 80, "window": 3}
    advancement: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[PlanItemStatus] = mapped_column(
        SAEnum(PlanItemStatus, name="plan_item_status_enum"), default=PlanItemStatus.ACTIVE)


class PlanItemAttempt(AbstractEntity):
    __tablename__ = "plan_item_attempt"
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_item.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    fluency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)   # analysis snapshot
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

**Why JSONB for `dosage`/`advancement`:** they're small, evolving config blobs —
same pattern as elsewhere in the app. Keeps the schema stable as rules change.

---

## 5. Content selection inside a plan item

A plan item says *what* to practise; the existing game engine serves the actual
content from `disfluency_phrase`. Two small additions needed:

- `exercise_content.select_content(db, exercise_type, difficulty)` → add an optional
  **`target_phoneme`** filter, so a "/s/ Read It Loud MEDIUM" item pulls only /s/
  MEDIUM passages.
- For `REPEAT_AFTER_ME`, either filter phrases by the pinned phoneme, or (if the
  item leaves phoneme NULL) fall back to the existing `practice_planner`
  personalisation.

No new content tables — plans **reference** the content already in
`disfluency_phrase` via (exercise_type, difficulty, target_phoneme).

---

## 6. Advancement engine

`services/plan_progress.py`, run after each plan-linked attempt:

```
on attempt (plan_item_id present):
  1. write PlanItemAttempt (score snapshot)
  2. if advancement.mode == AUTO:
       recent = last `window` attempts for this item
       if len(recent) >= window and all(a.fluency_score >= threshold):
           - bump difficulty one rung (EASY→MEDIUM→HARD[→TT]), OR
           - if already top rung: mark item COMPLETED and unlock the next (by sequence)
  3. doctor can always override (advance / hold / reset) via PATCH
```

Mirrors Lidcombe's "criterion sustained over consecutive sessions" gate. Ordering
items drills → open games gives the structured→unstructured fade.

---

## 7. Endpoints

### Doctor-facing — `get_current_doctor` (from the care-team feature)
```
POST   /v1/plans                          create a plan (+ items) for a patient
GET    /v1/plans?patient_id=&status=      list a patient's plans
GET    /v1/plans/{id}                      plan detail: items + progress summary
PATCH  /v1/plans/{id}                      update (status DRAFT→ACTIVE→…, dates)
POST   /v1/plans/{id}/items                add an item
PATCH  /v1/plans/{id}/items/{item_id}      edit / manually advance / hold
DELETE /v1/plans/{id}/items/{item_id}      remove an item
GET    /v1/plans/{id}/progress             review results per item (trend, attempts)
```
Guard: a doctor may only touch plans for **their approved patients** — join
`PatientDetail.doctor_id == current_doctor.id` (reuses the care-team link).

### Patient-facing — `get_current_patient`
```
GET    /v1/my-plan                         active plan + today's due items (from dosage)
```
"Today's due" = active plan's `ACTIVE` items whose dosage isn't yet met by today's
`PlanItemAttempt` rows.

### Integration with the existing game API
`POST /v1/exercises/{game}/attempt` gains an **optional `plan_item_id`** form field.
When present, after normal scoring it: (a) writes a `PlanItemAttempt`, (b) runs the
advancement engine. No `plan_item_id` → behaves exactly as today (free practice).

---

## 8. Module layout

```
app/
├── models/practice_plan.py      # NEW: PracticePlan, PlanItem, PlanItemAttempt + 2 enums
├── schemas/practice_plan.py     # NEW: plan/item create/read/update, progress, my-plan
├── services/
│   ├── practice_plan.py         # NEW: plan CRUD, "today's due", ownership checks
│   └── plan_progress.py         # NEW: record attempt + advancement engine
└── api/
    ├── plans.py                 # NEW: /v1/plans/* (doctor)
    └── my_plan.py               # NEW: /v1/my-plan (patient)
```
Plus: extend `exercise_content.select_content` with `target_phoneme`; add the
optional `plan_item_id` to `api/exercises.py::submit_attempt`; register routers +
Swagger tags in `main.py`.

---

## 9. Migration

One Alembic migration: `plan_status_enum`, `plan_item_status_enum`, and the three
tables (`practice_plan`, `plan_item`, `plan_item_attempt`) with FKs/indexes. Reuse
the existing `difficulty_enum` (do not recreate). Auto-runs on startup.

---

## 10. Suggested build order (each shippable)

1. **Models + migration** (3 tables + 2 enums).
2. **Plan CRUD** (`/v1/plans` + items) — doctor builds a plan; ownership guarded by
   the care-team link. Validate: phoneme only allowed for RAM / Read It Loud;
   difficulty required except for Talk with Ollie.
3. **`GET /v1/my-plan`** + add `plan_item_id` to the exercise `/attempt` so attempts
   are logged to the plan (writes `PlanItemAttempt`). Plan is now usable end-to-end.
4. **Advancement engine** (`plan_progress`) — AUTO gates + doctor override.
5. **`GET /v1/plans/{id}/progress`** review view.
6. **`target_phoneme` filter** in content selection so pinned-phoneme items serve
   the right content.

Steps 1–3 deliver "doctor assigns a plan, patient does it, attempts are tracked"
before any automation.

---

## 11. Open decisions

- **Dosage defaults** (reps/day, sessions/week) per age — pick sensible defaults,
  let the SLP override per item.
- **Auto vs manual advancement default** + threshold/window values — recommend AUTO
  (threshold 80, window 3) with override, but confirm the numbers clinically.
- **Multiple active plans per patient?** Recommend one ACTIVE plan at a time
  (others DRAFT/ARCHIVED) to keep "today's due" unambiguous.
- **Talk with Ollie in plans** — it has no difficulty/phoneme; a plan item for it is
  just "have a conversation" (dosage only). Confirm whether SLPs assign it at all.
```
