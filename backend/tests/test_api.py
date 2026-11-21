import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ["ANTHROPIC_API_KEY"] = ""  # offline assistant for tests

from fastapi.testclient import TestClient  # noqa: E402

from app.main import api  # noqa: E402
from app.rag.profile_parser import _keyword_parse  # noqa: E402
from app.rag.retriever import search  # noqa: E402

ORIGIN = {"Origin": "http://localhost:5173"}


def client() -> TestClient:
    return TestClient(api, base_url="http://localhost", headers=ORIGIN)


def register(c, phone, role, name="Test User", password="pass1234", city="Indore"):
    r = c.post("/api/auth/register", json={"name": name, "phone": phone, "password": password, "role": role, "city": city})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_register_validation():
    c = client()
    assert c.post("/api/auth/register", json={"name": "A B", "phone": "12345", "password": "pass1234", "role": "worker"}).status_code == 422
    assert c.post("/api/auth/register", json={"name": "A B", "phone": "9876500001", "password": "short", "role": "worker"}).status_code == 422
    assert c.post("/api/auth/register", json={"name": "A B", "phone": "9876500001", "password": "pass1234", "role": "admin"}).status_code == 422
    assert c.post("/api/auth/register", json={"name": "A B", "phone": "9876500001", "password": "pass1234", "role": "worker", "x": 1}).status_code == 422


def test_login_refresh_rotation_and_reuse_detection():
    c = client()
    register(c, "9876500002", "worker")
    r = c.post("/api/auth/login", json={"phone": "9876500002", "password": "pass1234"})
    assert r.status_code == 200
    old_cookie = c.cookies.get("ks_refresh")
    assert old_cookie
    # refresh rotates the cookie
    r = c.post("/api/auth/refresh")
    assert r.status_code == 200
    new_cookie = c.cookies.get("ks_refresh")
    assert new_cookie != old_cookie
    # replaying the old token revokes the family; the new one stops working too
    attacker = client()
    attacker.cookies.set("ks_refresh", old_cookie, domain="localhost", path="/api/auth")
    assert attacker.post("/api/auth/refresh").status_code == 401
    victim = client()
    victim.cookies.set("ks_refresh", new_cookie, domain="localhost", path="/api/auth")
    assert victim.post("/api/auth/refresh").status_code == 401


def test_bad_origin_rejected():
    c = TestClient(api, base_url="http://localhost", headers={"Origin": "https://evil.example"})
    assert c.post("/api/auth/login", json={"phone": "9876500002", "password": "x"}).status_code == 403


def test_lockout_after_failed_logins():
    c = client()
    register(c, "9876500003", "worker")
    for _ in range(5):
        assert c.post("/api/auth/login", json={"phone": "9876500003", "password": "wrong1234"}).status_code == 401
    assert c.post("/api/auth/login", json={"phone": "9876500003", "password": "pass1234"}).status_code == 429


def test_tokens_rejected_when_tampered_or_missing():
    c = client()
    t = register(c, "9876500004", "worker")
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/auth/me", headers=auth(t[:-2] + "xx")).status_code == 401
    assert c.get("/api/auth/me", headers=auth(t)).status_code == 200
    # logout-all invalidates existing access tokens
    assert c.post("/api/auth/logout-all", headers=auth(t)).status_code == 204
    assert c.get("/api/auth/me", headers=auth(t)).status_code == 401


def test_job_flow_and_authorization():
    c = client()
    emp = register(c, "9876500010", "employer", name="Shop Owner")
    other_emp = register(c, "9876500011", "employer", name="Other Owner")
    wrk = register(c, "9876500012", "worker", name="Ramesh")

    # worker cannot post jobs
    job = {"title": "Paint 2 rooms", "skill": "painter", "city": "Indore", "wage_per_day": 800, "days": 2, "workers_needed": 1}
    assert c.post("/api/jobs", json=job, headers=auth(wrk)).status_code == 403

    r = c.put("/api/profile", headers=auth(wrk), json={"skills": ["painter"], "experience_years": 5, "daily_wage": 800, "city": "Indore"})
    assert r.status_code == 200, r.text

    r = c.post("/api/jobs", json=job, headers=auth(emp))
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]

    nearby = c.get("/api/jobs/nearby", headers=auth(wrk)).json()
    assert [j["id"] for j in nearby] == [job_id]

    r = c.post(f"/api/jobs/{job_id}/apply", headers=auth(wrk))
    assert r.status_code == 201
    app_id = r.json()["id"]
    assert c.post(f"/api/jobs/{job_id}/apply", headers=auth(wrk)).status_code == 409

    # another employer can't see or act on this job (IDOR protection)
    assert c.get(f"/api/jobs/{job_id}/applications", headers=auth(other_emp)).status_code == 404
    assert c.post(f"/api/applications/{app_id}/hire", headers=auth(other_emp)).status_code == 404
    assert c.get(f"/api/applications/{app_id}/messages", headers=auth(other_emp)).status_code == 404

    apps = c.get(f"/api/jobs/{job_id}/applications", headers=auth(emp)).json()
    assert apps[0]["worker_phone"] is None  # phone hidden until hired

    r = c.post(f"/api/applications/{app_id}/hire", headers=auth(emp))
    assert r.status_code == 200 and r.json()["worker_phone"] == "9876500012"

    # worker can't mark completed; employer can't mark on_the_way
    assert c.patch(f"/api/applications/{app_id}/status", json={"status": "completed"}, headers=auth(wrk)).status_code == 409
    assert c.patch(f"/api/applications/{app_id}/status", json={"status": "on_the_way"}, headers=auth(emp)).status_code == 409
    assert c.patch(f"/api/applications/{app_id}/status", json={"status": "on_the_way"}, headers=auth(wrk)).status_code == 200
    assert c.post(f"/api/applications/{app_id}/rate", json={"stars": 5}, headers=auth(emp)).status_code == 409
    assert c.patch(f"/api/applications/{app_id}/status", json={"status": "completed"}, headers=auth(emp)).status_code == 200
    assert c.post(f"/api/applications/{app_id}/rate", json={"stars": 5}, headers=auth(emp)).status_code == 201
    assert c.post(f"/api/applications/{app_id}/rate", json={"stars": 4}, headers=auth(emp)).status_code == 409
    assert c.get("/api/profile", headers=auth(wrk)).json()["rating"] == 5.0


def test_security_headers():
    r = client().get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_retriever_finds_hindi_and_english():
    assert search("पैसा नहीं मिला thekedar", k=1)[0][0].section == "If your wages are not paid"
    assert search("pension scheme for workers", k=1)[0][0].doc_title.startswith("PM Shram")
    assert search("eshram card kaise banaye", k=1)[0][0].doc_title.startswith("e-Shram")


def test_keyword_profile_parser():
    s = _keyword_parse("Main electrician hoon, 5 saal ka experience, Indore mein kaam chahiye, 800 rupaye roz")
    assert s.skills == ["electrician"] and s.experience_years == 5 and s.city == "Indore" and s.daily_wage == 800


def test_community_endpoints_and_notifications():
    c = client()
    emp = register(c, "9876500020", "employer", name="Meena Joshi")
    wrk = register(c, "9876500021", "worker", name="Kallu Ram")
    c.put("/api/profile", headers=auth(wrk), json={"skills": ["plumber"], "experience_years": 3, "daily_wage": 700, "city": "Bhopal"})
    job = c.post("/api/jobs", headers=auth(emp), json={"title": "Fix tap", "skill": "plumber", "city": "Bhopal", "wage_per_day": 700, "days": 1, "workers_needed": 1, "urgent": True}).json()
    assert job["urgent"] is True

    stats = c.get("/api/stats/public").json()  # public, no token needed
    assert stats["open_jobs"] >= 1 and any(j["id"] == job["id"] for j in stats["recent_jobs"])
    assert "phone" not in str(stats)

    # job:new alert was saved for the worker even though no socket was connected
    n = c.get("/api/notifications", headers=auth(wrk)).json()
    assert n["unread"] >= 1 and n["items"][0]["kind"] == "job:new"
    assert c.post("/api/notifications/read-all", headers=auth(wrk)).status_code == 204
    assert c.get("/api/notifications", headers=auth(wrk)).json()["unread"] == 0

    # directory is employer-only and never exposes phone numbers
    assert c.get("/api/workers", headers=auth(wrk)).status_code == 403
    found = c.get("/api/workers?skill=plumber&city=bhopal", headers=auth(emp)).json()
    assert [w["name"] for w in found] == ["Kallu Ram"] and "phone" not in found[0]
    prof = c.get(f"/api/workers/{found[0]['id']}", headers=auth(emp)).json()
    assert prof["skills"] == ["plumber"] and "phone" not in prof

    me = c.get("/api/stats/me", headers=auth(wrk)).json()
    assert me["role"] == "worker" and me["earned_total"] == 0
    assert c.get("/api/stats/me", headers=auth(emp)).json()["open_jobs"] == 1
