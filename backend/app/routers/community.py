"""Dashboards, public stats, worker directory, public worker profiles and notifications."""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Application, Job, Notification, Rating, User, WorkerProfile
from ..security import get_current_user, require_role
from ..skills import SKILLS

router = APIRouter(prefix="/api", tags=["community"])

DONE = ("completed",)
ACTIVE = ("hired", "on_the_way", "arrived")


def _first_name_initial(name: str) -> str:
    """Privacy: reviews show 'Sunita S.' rather than full names."""
    parts = name.split()
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


def _ratings(db: Session, user_ids: list[int]) -> dict[int, tuple[float, int]]:
    if not user_ids:
        return {}
    rows = (
        db.query(Rating.to_user_id, func.avg(Rating.stars), func.count(Rating.id))
        .filter(Rating.to_user_id.in_(user_ids))
        .group_by(Rating.to_user_id)
        .all()
    )
    return {uid: (round(float(avg), 1), n) for uid, avg, n in rows}


def _jobs_done(db: Session, user_ids: list[int]) -> dict[int, int]:
    if not user_ids:
        return {}
    rows = (
        db.query(Application.worker_id, func.count(Application.id))
        .filter(Application.worker_id.in_(user_ids), Application.status.in_(DONE))
        .group_by(Application.worker_id)
        .all()
    )
    return dict(rows)


# ---------- public ----------


@router.get("/stats/public")
def public_stats(db: Session = Depends(get_db)):
    """Numbers and a live job board for the landing page. No personal data."""
    open_jobs = db.query(Job).filter(Job.status == "open")
    recent = open_jobs.order_by(Job.created_at.desc()).limit(6).all()
    skill_counts = dict(db.query(Job.skill, func.count(Job.id)).filter(Job.status == "open").group_by(Job.skill).all())
    worker_skills: dict[str, int] = {}
    for (skills,) in db.query(WorkerProfile.skills).all():
        for s in filter(None, skills.split(",")):
            worker_skills[s] = worker_skills.get(s, 0) + 1
    review_rows = (
        db.query(Rating, User, Job)
        .join(User, User.id == Rating.from_user_id)
        .join(Application, Application.id == Rating.application_id)
        .join(Job, Job.id == Application.job_id)
        .filter(Rating.comment != "", Rating.stars >= 4, User.role == "employer")
        .order_by(Rating.created_at.desc())
        .limit(3)
        .all()
    )
    return {
        "recent_reviews": [
            {"by": _first_name_initial(u.name), "city": j.city, "stars": r.stars, "comment": r.comment, "job_title": j.title}
            for r, u, j in review_rows
        ],
        "open_jobs": open_jobs.count(),
        "workers": db.query(User).filter(User.role == "worker").count(),
        "employers": db.query(User).filter(User.role == "employer").count(),
        "cities": db.query(func.count(func.distinct(func.lower(Job.city)))).scalar() or 0,
        "completed": db.query(Application).filter(Application.status == "completed").count(),
        "avg_rating": round(float(db.query(func.avg(Rating.stars)).scalar() or 0), 1),
        "recent_jobs": [
            {
                "id": j.id,
                "title": j.title,
                "skill": j.skill,
                "city": j.city,
                "area": j.area,
                "wage_per_day": j.wage_per_day,
                "days": j.days,
                "urgent": j.urgent,
                "created_at": j.created_at.isoformat(),
            }
            for j in recent
        ],
        "skills": [
            {"key": k, "en": v["en"], "hi": v["hi"], "open_jobs": skill_counts.get(k, 0), "workers": worker_skills.get(k, 0)}
            for k, v in SKILLS.items()
        ],
    }


# ---------- dashboards ----------


@router.get("/stats/me")
def my_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if user.role == "worker":
        done = (
            db.query(Application, Job)
            .join(Job, Job.id == Application.job_id)
            .filter(Application.worker_id == user.id, Application.status == "completed")
            .all()
        )
        earned = sum(j.wage_per_day * j.days for _, j in done)
        earned_month = sum(j.wage_per_day * j.days for a, j in done if _aware(a.updated_at) >= month_start)
        rating = _ratings(db, [user.id]).get(user.id)
        p = db.get(WorkerProfile, user.id)
        checks = [bool(p and p.skill_list), bool(p and p.experience_years), bool(p and p.daily_wage), bool(p and p.city), bool(p and p.lat), bool(p and p.bio)]
        return {
            "role": "worker",
            "earned_total": earned,
            "earned_month": earned_month,
            "jobs_completed": len(done),
            "active_jobs": db.query(Application).filter(Application.worker_id == user.id, Application.status.in_(ACTIVE)).count(),
            "pending_applications": db.query(Application).filter_by(worker_id=user.id, status="applied").count(),
            "rating": rating[0] if rating else None,
            "rating_count": rating[1] if rating else 0,
            "profile_complete": round(100 * sum(checks) / len(checks)),
        }
    jobs = db.query(Job).filter_by(employer_id=user.id).all()
    job_ids = [j.id for j in jobs]
    apps = db.query(Application).filter(Application.job_id.in_(job_ids)).all() if job_ids else []
    by_job = {j.id: j for j in jobs}
    done = [a for a in apps if a.status == "completed"]
    return {
        "role": "employer",
        "open_jobs": sum(1 for j in jobs if j.status == "open"),
        "active_workers": sum(1 for a in apps if a.status in ACTIVE),
        "new_applications": sum(1 for a in apps if a.status == "applied"),
        "total_hires": sum(1 for a in apps if a.status in ACTIVE + DONE),
        "spent_total": sum(by_job[a.job_id].wage_per_day * by_job[a.job_id].days for a in done),
    }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------- worker directory ----------


@router.get("/workers")
def find_workers(
    skill: str | None = Query(None, max_length=40),
    city: str | None = Query(None, max_length=60),
    q: str | None = Query(None, max_length=60),
    _: User = Depends(require_role("employer")),
    db: Session = Depends(get_db),
):
    query = db.query(WorkerProfile, User).join(User, User.id == WorkerProfile.user_id).filter(User.is_active.is_(True), WorkerProfile.skills != "")
    if skill:
        query = query.filter(WorkerProfile.skills.contains(skill))
    if city:
        query = query.filter(func.lower(WorkerProfile.city) == city.strip().lower())
    if q:
        query = query.filter(User.name.ilike(f"%{q.strip()}%"))
    rows = query.limit(300).all()
    rows = [(p, u) for p, u in rows if not skill or skill in p.skill_list]
    ids = [u.id for _, u in rows]
    ratings, done = _ratings(db, ids), _jobs_done(db, ids)
    out = [
        {
            "id": u.id,
            "name": u.name,
            "city": p.city,
            "skills": p.skill_list,
            "experience_years": p.experience_years,
            "daily_wage": p.daily_wage,
            "available": p.available,
            "bio": p.bio,
            "rating": ratings.get(u.id, (None, 0))[0],
            "rating_count": ratings.get(u.id, (None, 0))[1],
            "jobs_completed": done.get(u.id, 0),
        }
        for p, u in rows
    ]
    out.sort(key=lambda w: (not w["available"], -(w["rating"] or 0), -w["jobs_completed"]))
    return out[:60]


@router.get("/workers/{worker_id}")
def worker_public_profile(worker_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, worker_id)
    if not u or u.role != "worker" or not u.is_active:
        raise HTTPException(404, "Worker not found")
    p = db.get(WorkerProfile, u.id)
    rating = _ratings(db, [u.id]).get(u.id)
    reviews = (
        db.query(Rating, User, Job)
        .join(User, User.id == Rating.from_user_id)
        .join(Application, Application.id == Rating.application_id)
        .join(Job, Job.id == Application.job_id)
        .filter(Rating.to_user_id == u.id)
        .order_by(Rating.created_at.desc())
        .limit(20)
        .all()
    )
    breakdown = {s: 0 for s in range(1, 6)}
    for (stars, n) in db.query(Rating.stars, func.count(Rating.id)).filter(Rating.to_user_id == u.id).group_by(Rating.stars):
        breakdown[stars] = n
    return {
        "id": u.id,
        "name": u.name,
        "city": p.city if p else u.city,
        "member_since": u.created_at.isoformat(),
        "skills": p.skill_list if p else [],
        "experience_years": p.experience_years if p else 0,
        "daily_wage": p.daily_wage if p else 0,
        "bio": p.bio if p else "",
        "available": p.available if p else False,
        "rating": rating[0] if rating else None,
        "rating_count": rating[1] if rating else 0,
        "rating_breakdown": breakdown,
        "jobs_completed": _jobs_done(db, [u.id]).get(u.id, 0),
        "reviews": [
            {
                "stars": r.stars,
                "comment": r.comment,
                "by": _first_name_initial(by.name),
                "job_title": job.title,
                "created_at": r.created_at.isoformat(),
            }
            for r, by, job in reviews
        ],
    }


# ---------- notifications ----------


@router.get("/notifications")
def notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=30)
    items = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.created_at >= since)
        .order_by(Notification.created_at.desc())
        .limit(30)
        .all()
    )
    unread = db.query(Notification).filter_by(user_id=user.id, read=False).count()
    return {
        "unread": unread,
        "items": [
            {"id": n.id, "kind": n.kind, "data": json.loads(n.data), "link": n.link, "read": n.read, "created_at": n.created_at.isoformat()}
            for n in items
        ],
    }


@router.post("/notifications/read-all", status_code=204)
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(user_id=user.id, read=False).update({"read": True})
    db.commit()
