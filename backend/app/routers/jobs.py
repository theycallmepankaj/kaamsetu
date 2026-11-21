"""Jobs, applications, hiring and ratings.

Every endpoint checks that the caller owns the job (employer) or the application
(worker) before reading or changing it, so users cannot act on other people's data
by guessing ids.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..geo import distance_between, is_nearby
from ..limiter import limiter
from ..models import Application, Job, Message, Rating, User, WorkerProfile
from ..realtime import notify_user
from ..schemas import ApplicationOut, JobIn, JobOut, MessageOut, RatingIn, StatusIn
from ..security import get_current_user, require_role
from .profile import rating_for

router = APIRouter(prefix="/api", tags=["jobs"])

ACTIVE_HIRED = ("hired", "on_the_way", "arrived", "completed")
ALERT_RADIUS_KM = 15


def _hired_count(job: Job) -> int:
    return sum(1 for a in job.applications if a.status in ACTIVE_HIRED)


def _job_out(job: Job, distance: float | None = None, mine: Application | None = None) -> JobOut:
    out = JobOut.model_validate(job)
    out.employer_name = job.employer.name if job.employer else ""
    out.hired_count = _hired_count(job)
    out.applicant_count = sum(1 for a in job.applications if a.status not in ("withdrawn", "rejected"))
    out.distance_km = distance
    if mine is not None:
        out.my_application = _app_out(None, mine, reveal_phone=False)
    return out


def _app_out(db: Session | None, a: Application, reveal_phone: bool) -> ApplicationOut:
    out = ApplicationOut.model_validate(a)
    out.worker_name = a.worker.name
    out.worker_phone = a.worker.phone if reveal_phone and a.status in ACTIVE_HIRED else None
    prof = a.worker.profile
    if prof:
        out.worker_skills = prof.skill_list
        out.worker_experience = prof.experience_years
    if db is not None:
        out.worker_rating, _ = rating_for(db, a.worker_id)
    return out


def _owned_job(db: Session, job_id: int, employer: User) -> Job:
    job = db.get(Job, job_id)
    if not job or job.employer_id != employer.id:
        raise HTTPException(404, "Job not found")
    return job


def _app_for_participant(db: Session, app_id: int, user: User) -> Application:
    a = db.query(Application).options(joinedload(Application.job)).filter_by(id=app_id).first()
    if not a or (a.worker_id != user.id and a.job.employer_id != user.id):
        raise HTTPException(404, "Not found")
    return a


# ---------- employer ----------


@router.post("/jobs", response_model=JobOut, status_code=201)
@limiter.limit("20/hour")
async def create_job(
    request: Request, body: JobIn, employer: User = Depends(require_role("employer")), db: Session = Depends(get_db)
):
    job = Job(employer_id=employer.id, **body.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)

    # Live alert to available workers with this skill who are nearby.
    candidates = (
        db.query(WorkerProfile)
        .filter(WorkerProfile.available.is_(True), WorkerProfile.skills.contains(job.skill))
        .all()
    )
    for p in candidates:
        if job.skill in p.skill_list and is_nearby(p.lat, p.lng, p.city, job.lat, job.lng, job.city, ALERT_RADIUS_KM):
            d = distance_between(p.lat, p.lng, job.lat, job.lng)
            await notify_user(p.user_id, "job:new", _job_out(job, d).model_dump(mode="json"), "/work")
    return _job_out(job)


@router.get("/jobs/mine", response_model=list[JobOut])
def my_jobs(employer: User = Depends(require_role("employer")), db: Session = Depends(get_db)):
    jobs = db.query(Job).filter_by(employer_id=employer.id).order_by(Job.created_at.desc()).limit(100).all()
    return [_job_out(j) for j in jobs]


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationOut])
def job_applications(job_id: int, employer: User = Depends(require_role("employer")), db: Session = Depends(get_db)):
    job = _owned_job(db, job_id, employer)
    return [_app_out(db, a, reveal_phone=True) for a in job.applications if a.status != "withdrawn"]


@router.post("/jobs/{job_id}/close", response_model=JobOut)
def close_job(job_id: int, employer: User = Depends(require_role("employer")), db: Session = Depends(get_db)):
    job = _owned_job(db, job_id, employer)
    job.status = "closed"
    db.commit()
    return _job_out(job)


@router.post("/applications/{app_id}/hire", response_model=ApplicationOut)
async def hire(app_id: int, employer: User = Depends(require_role("employer")), db: Session = Depends(get_db)):
    a = _app_for_participant(db, app_id, employer)
    job = a.job
    if job.employer_id != employer.id:
        raise HTTPException(404, "Not found")
    if job.status != "open":
        raise HTTPException(409, "This job is no longer open")
    if a.status != "applied":
        raise HTTPException(409, "Worker cannot be hired in the current state")
    if _hired_count(job) >= job.workers_needed:
        raise HTTPException(409, "All positions are already filled")
    a.status = "hired"
    db.flush()
    if _hired_count(job) >= job.workers_needed:
        job.status = "filled"
    db.commit()
    await notify_user(
        a.worker_id,
        "job:hired",
        {"application_id": a.id, "job_id": job.id, "title": job.title, "employer": employer.name, "employer_phone": employer.phone},
        f"/chat/{a.id}",
    )
    return _app_out(db, a, reveal_phone=True)


# ---------- worker ----------


@router.get("/jobs/nearby", response_model=list[JobOut])
def nearby_jobs(
    radius_km: float = Query(15, ge=1, le=100),
    skill: str | None = Query(None, max_length=40),
    sort: str = Query("distance", pattern="^(distance|wage|new)$"),
    worker: User = Depends(require_role("worker")),
    db: Session = Depends(get_db),
):
    p = db.get(WorkerProfile, worker.id)
    if not p or not p.skill_list:
        return []
    skills = [skill] if skill in p.skill_list else p.skill_list
    jobs = (
        db.query(Job)
        .options(joinedload(Job.employer), joinedload(Job.applications))
        .filter(Job.status == "open", Job.skill.in_(skills))
        .order_by(Job.created_at.desc())
        .limit(300)
        .all()
    )
    result = []
    for j in jobs:
        if not is_nearby(p.lat, p.lng, p.city, j.lat, j.lng, j.city, radius_km):
            continue
        mine = next((a for a in j.applications if a.worker_id == worker.id), None)
        result.append(_job_out(j, distance_between(p.lat, p.lng, j.lat, j.lng), mine))
    if sort == "wage":
        result.sort(key=lambda o: -o.wage_per_day)
    elif sort == "new":
        result.sort(key=lambda o: o.created_at, reverse=True)
    else:
        result.sort(key=lambda o: (o.distance_km is None, o.distance_km or 0))
    result.sort(key=lambda o: not o.urgent)  # stable: urgent jobs first, rest keep their order
    return result[:100]


@router.get("/applications/mine", response_model=list[ApplicationOut])
def my_applications(worker: User = Depends(require_role("worker")), db: Session = Depends(get_db)):
    apps = db.query(Application).filter_by(worker_id=worker.id).order_by(Application.created_at.desc()).limit(100).all()
    return [_app_out(db, a, reveal_phone=False) for a in apps]


@router.get("/applications/mine/jobs", response_model=list[JobOut])
def my_application_jobs(worker: User = Depends(require_role("worker")), db: Session = Depends(get_db)):
    apps = db.query(Application).filter_by(worker_id=worker.id).order_by(Application.created_at.desc()).limit(100).all()
    return [_job_out(a.job, None, a) for a in apps]


@router.post("/jobs/{job_id}/apply", response_model=ApplicationOut, status_code=201)
@limiter.limit("30/hour")
async def apply(request: Request, job_id: int, worker: User = Depends(require_role("worker")), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.status != "open":
        raise HTTPException(404, "Job not found or no longer open")
    existing = db.query(Application).filter_by(job_id=job.id, worker_id=worker.id).first()
    if existing and existing.status != "withdrawn":
        raise HTTPException(409, "You have already applied")
    if existing:
        existing.status = "applied"
        a = existing
    else:
        a = Application(job_id=job.id, worker_id=worker.id)
        db.add(a)
    db.commit()
    db.refresh(a)
    out = _app_out(db, a, reveal_phone=False)
    await notify_user(
        job.employer_id,
        "job:application",
        {"job_id": job.id, "title": job.title, "application": out.model_dump(mode="json")},
        f"/hire/{job.id}",
    )
    return out


# ---------- both sides ----------

# Which side may move an application into which status.
TRANSITIONS = {
    "worker": {"on_the_way": {"hired"}, "arrived": {"hired", "on_the_way"}, "withdrawn": {"applied"}},
    "employer": {"completed": {"hired", "on_the_way", "arrived"}, "rejected": {"applied"}},
}


@router.patch("/applications/{app_id}/status", response_model=ApplicationOut)
async def update_status(app_id: int, body: StatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _app_for_participant(db, app_id, user)
    side = "worker" if a.worker_id == user.id else "employer"
    allowed_from = TRANSITIONS[side].get(body.status)
    if not allowed_from or a.status not in allowed_from:
        raise HTTPException(409, f"Cannot change status from {a.status} to {body.status}")
    a.status = body.status
    db.commit()
    other = a.job.employer_id if side == "worker" else a.worker_id
    payload = {"application_id": a.id, "job_id": a.job_id, "title": a.job.title, "status": a.status, "by": user.name}
    link = f"/hire/{a.job_id}" if side == "worker" else "/work/mine"
    await notify_user(other, "job:status", payload, link)
    return _app_out(db, a, reveal_phone=side == "employer")


@router.get("/applications/{app_id}/messages", response_model=list[MessageOut])
def messages(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _app_for_participant(db, app_id, user)
    return db.query(Message).filter_by(application_id=a.id).order_by(Message.created_at.asc()).limit(500).all()


@router.post("/applications/{app_id}/rate", status_code=201)
def rate(app_id: int, body: RatingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _app_for_participant(db, app_id, user)
    if a.status != "completed":
        raise HTTPException(409, "You can rate only after the work is completed")
    to_user = a.job.employer_id if a.worker_id == user.id else a.worker_id
    if db.query(Rating).filter_by(application_id=a.id, from_user_id=user.id).first():
        raise HTTPException(409, "Already rated")
    db.add(Rating(application_id=a.id, from_user_id=user.id, to_user_id=to_user, stars=body.stars, comment=body.comment))
    db.commit()
    return {"ok": True}
