from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..limiter import limiter
from ..models import Rating, User, WorkerProfile
from ..rag.profile_parser import parse_profile_text
from ..schemas import ProfileIn, ProfileOut, ProfileParseIn, ProfileSuggestion
from ..security import require_role
from ..skills import SKILLS

router = APIRouter(prefix="/api", tags=["profile"])


def rating_for(db: Session, user_id: int) -> tuple[float | None, int]:
    avg, count = db.query(func.avg(Rating.stars), func.count(Rating.id)).filter(Rating.to_user_id == user_id).one()
    return (round(float(avg), 1) if avg else None), count


def _profile_out(db: Session, p: WorkerProfile) -> ProfileOut:
    avg, count = rating_for(db, p.user_id)
    return ProfileOut(
        skills=p.skill_list,
        experience_years=p.experience_years,
        daily_wage=p.daily_wage,
        city=p.city,
        lat=p.lat,
        lng=p.lng,
        bio=p.bio,
        available=p.available,
        rating=avg,
        rating_count=count,
    )


@router.get("/skills")
def list_skills():
    return [{"key": k, "en": v["en"], "hi": v["hi"]} for k, v in SKILLS.items()]


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(require_role("worker")), db: Session = Depends(get_db)):
    p = db.get(WorkerProfile, user.id)
    if p is None:
        p = WorkerProfile(user_id=user.id, city=user.city)
        db.add(p)
        db.commit()
    return _profile_out(db, p)


@router.put("/profile", response_model=ProfileOut)
def save_profile(body: ProfileIn, user: User = Depends(require_role("worker")), db: Session = Depends(get_db)):
    p = db.get(WorkerProfile, user.id) or WorkerProfile(user_id=user.id)
    p.skills = ",".join(body.skills)
    p.experience_years = body.experience_years
    p.daily_wage = body.daily_wage
    p.city = body.city
    p.lat, p.lng = body.lat, body.lng
    p.bio = body.bio
    p.available = body.available
    db.add(p)
    user.city = body.city
    db.commit()
    return _profile_out(db, p)


@router.post("/profile/parse", response_model=ProfileSuggestion)
@limiter.limit("10/minute")
async def parse_profile(request: Request, body: ProfileParseIn, user: User = Depends(require_role("worker"))):
    """Turn a spoken/typed sentence into profile fields. The worker reviews them before saving."""
    return await parse_profile_text(body.text)


@router.get("/workers/{worker_id}/rating")
def worker_rating(worker_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("employer", "worker", "admin"))):
    worker = db.get(User, worker_id)
    if not worker or worker.role != "worker":
        raise HTTPException(404, "Worker not found")
    avg, count = rating_for(db, worker_id)
    return {"rating": avg, "count": count}
