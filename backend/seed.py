"""Fill the development database with realistic DEMO data.

    .venv/bin/python seed.py            # wipes the dev database and seeds it

Everything created here is fictional. All phone numbers are in the 90000xxxxx
range so they can never reach a real person. Never run this against production.
"""

import json
import random
import sys
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import Application, Job, Message, Notification, Rating, User, WorkerProfile
from app.security import hash_password

if get_settings().is_production:
    sys.exit("Refusing to seed a production database.")

random.seed(42)
NOW = datetime.now(timezone.utc)
PASSWORD = "demo1234"

CITIES = {
    "Indore": ((22.7196, 75.8577), ["Vijay Nagar", "Palasia", "Bhawarkuan", "Sudama Nagar", "Nipania", "Rajendra Nagar"]),
    "Pune": ((18.5204, 73.8567), ["Kothrud", "Hadapsar", "Wakad", "Baner", "Viman Nagar", "Katraj"]),
    "Delhi": ((28.6139, 77.2090), ["Laxmi Nagar", "Rohini Sector 9", "Dwarka Sector 12", "Saket", "Karol Bagh", "Mayur Vihar"]),
    "Mumbai": ((19.0760, 72.8777), ["Andheri East", "Borivali West", "Ghatkopar", "Dadar", "Kurla", "Malad"]),
    "Bengaluru": ((12.9716, 77.5946), ["Whitefield", "Koramangala", "HSR Layout", "Jayanagar", "Yelahanka", "Marathahalli"]),
    "Jaipur": ((26.9124, 75.7873), ["Malviya Nagar", "Mansarovar", "Vaishali Nagar", "C-Scheme", "Jagatpura"]),
    "Lucknow": ((26.8467, 80.9462), ["Gomti Nagar", "Aliganj", "Indira Nagar", "Hazratganj", "Alambagh"]),
    "Hyderabad": ((17.3850, 78.4867), ["Kukatpally", "Madhapur", "Dilsukhnagar", "Secunderabad", "Miyapur"]),
}
METRO = {"Delhi", "Mumbai", "Bengaluru"}

WAGES = {  # typical daily wage range in rupees (demo values)
    "painter": (700, 900), "electrician": (800, 1100), "plumber": (750, 1000), "carpenter": (800, 1100),
    "mason": (750, 1000), "helper": (450, 600), "driver": (700, 900), "cook": (800, 1400),
    "house_help": (400, 600), "cleaner": (450, 600), "security_guard": (500, 700), "delivery": (500, 700),
    "welder": (800, 1000), "mechanic": (700, 1000), "tailor": (600, 800), "gardener": (450, 600),
}

JOBS = {
    "painter": [("Paint 2BHK flat before Diwali", "Walls and ceiling of 2 bedrooms, hall and kitchen. Asian Paints Tractor Emulsion, we will buy the material."),
                ("Exterior wall painting, G+1 house", "Weatherproof paint on outside walls. Scaffolding available at site."),
                ("Putty and primer for new office", "Around 1200 sq ft office. Two coats of putty, one primer.")],
    "electrician": [("House wiring check and MCB change", "Old wiring in a 3BHK keeps tripping. Check full wiring and change the MCB box."),
                    ("Install 6 fans and 10 LED lights", "New flat, points already there. Fittings will be provided."),
                    ("Inverter connection and new switchboards", "Connect 1.5 kVA inverter and replace 8 switchboards with modular ones.")],
    "plumber": [("Bathroom leakage repair", "Water leaking from the bathroom into the room below. Need to find and fix the leak."),
                ("Fit new kitchen sink and RO line", "Steel sink with tap, plus water line for RO purifier."),
                ("Overhead tank pipeline replacement", "Replace old GI pipe from the tank with CPVC, about 30 feet.")],
    "carpenter": [("Modular wardrobe fitting", "Fit 2 ready-made wardrobes and adjust the doors."),
                  ("Repair doors and window frames", "5 doors not closing properly, 2 window frames damaged by termite."),
                  ("Make 2 study tables", "Plywood with laminate, size will be explained at site.")],
    "mason": [("Bathroom tiles replacement", "Remove old tiles and fit new floor and wall tiles in one bathroom."),
              ("Boundary wall construction, 40 ft", "Brick wall about 5 ft high with plaster."),
              ("Plaster work for new room", "Inside plaster for one 12x14 room on the first floor.")],
    "helper": [("Helpers for shop shifting", "Shift goods of a kirana shop to a new place 2 km away. Tempo arranged."),
               ("Site helpers for slab casting", "Slab casting for G+1 house. Work starts 7 am."),
               ("Loading and unloading at godown", "Cement and steel unloading from trucks.")],
    "driver": [("Driver for family car, 10 days", "Swift Dzire, city driving. Morning 9 to evening 7."),
               ("Tempo driver for deliveries", "Tata Ace, deliveries within the city. LMV licence needed."),
               ("Driver for outstation family trip", "Innova, 4-day trip. Food and stay will be provided.")],
    "cook": [("Cook for wedding function, 150 guests", "North Indian veg menu for one evening. Helpers will be there."),
             ("Daily cook for family of 4", "Two meals, simple home food, no onion-garlic on Tuesdays.")],
    "house_help": [("Deep cleaning of 3BHK before shifting", "Kitchen, bathrooms, windows and floors."),
                   ("Daily house help, mornings", "Jhadu-pocha and utensils, around 2 hours daily.")],
    "cleaner": [("Office cleaning after renovation", "Dust and paint marks after interior work, 1500 sq ft."),
                ("Water tank cleaning", "Two 1000-litre tanks on the terrace.")],
    "security_guard": [("Night guard for construction site", "8 pm to 8 am. Cabin and torch provided."),
                       ("Guard for society gate, 12-hour shift", "Visitor entry register and parcel handling.")],
    "delivery": [("Delivery partners for grocery store, festive rush", "Own two-wheeler needed. Petrol paid extra.")],
    "welder": [("Grill and gate welding work", "Balcony grill and main gate repair."),
               ("Fabrication of steel shed", "Small shed for parking, about 10x15 ft.")],
    "mechanic": [("AC servicing for 5 units", "Split ACs in an office, wet servicing and gas check."),
                 ("Two-wheeler repair at home", "Activa not starting, also needs general service.")],
    "tailor": [("Stitching 40 school uniforms", "Cloth provided. Shirts and trousers, sizes list will be shared."),
               ("Blouse and kurti alterations for boutique", "Regular work for a small boutique, around 25 pieces.")],
    "gardener": [("Weekly garden maintenance", "Small garden with lawn and 30 pots. Every Sunday morning."),
                 ("Plant 30 saplings in society garden", "Pits to be dug, saplings and manure provided.")],
}

WORKERS = [  # name, city, skills, years
    ("Ramesh Yadav", "Indore", ["painter"], 8), ("Suresh Patel", "Indore", ["electrician"], 12), ("Mohammed Salim", "Indore", ["plumber"], 6),
    ("Anita Devi", "Indore", ["house_help", "cook"], 9), ("Raju Kushwaha", "Indore", ["mason", "helper"], 15), ("Gopal Sahu", "Indore", ["carpenter"], 10),
    ("Deepak Rathore", "Indore", ["painter"], 5), ("Sohan Lal Verma", "Indore", ["painter", "helper"], 11),
    ("Akash Verma", "Indore", ["electrician"], 4), ("Kailash Chouhan", "Indore", ["plumber"], 9),
    ("Ganesh Pawar", "Pune", ["painter"], 7), ("Vijay Shinde", "Pune", ["electrician"], 9), ("Prakash Jadhav", "Pune", ["plumber"], 11),
    ("Mahesh Kumbhar", "Pune", ["mason"], 14), ("Sunita Waghmare", "Pune", ["cook"], 6), ("Firoz Ansari", "Pune", ["welder"], 8),
    ("Manoj Kumar", "Delhi", ["electrician"], 10), ("Imran Khan", "Delhi", ["driver"], 7), ("Pooja Kumari", "Delhi", ["house_help"], 4),
    ("Sanjay Rawat", "Delhi", ["security_guard"], 12), ("Dinesh Saini", "Delhi", ["carpenter"], 16), ("Rakesh Jatav", "Delhi", ["helper", "painter"], 5),
    ("Yusuf Sheikh", "Mumbai", ["plumber"], 13), ("Santosh Nishad", "Mumbai", ["driver"], 9), ("Kavita Yadav", "Mumbai", ["cook"], 11),
    ("Abdul Rehman", "Mumbai", ["tailor"], 18), ("Sachin More", "Mumbai", ["painter"], 6), ("Deepak Kashyap", "Mumbai", ["delivery"], 3),
    ("Arjun Gowda", "Bengaluru", ["electrician"], 8), ("Ravi Naik", "Bengaluru", ["mechanic"], 10), ("Lakshmi Bai", "Bengaluru", ["house_help", "cleaner"], 7),
    ("Venkatesh Rao", "Bengaluru", ["carpenter"], 13), ("Shankar Reddy", "Bengaluru", ["gardener"], 9), ("Raju Mondal", "Bengaluru", ["mason"], 11),
    ("Babulal Meena", "Jaipur", ["mason"], 20), ("Harish Bhatt", "Jaipur", ["painter"], 9), ("Kamla Bai", "Jaipur", ["cook", "house_help"], 12),
    ("Mukesh Prajapati", "Jaipur", ["plumber"], 7), ("Bhagwan Singh", "Jaipur", ["security_guard"], 15),
    ("Naresh Chauhan", "Lucknow", ["electrician"], 9), ("Sita Devi", "Lucknow", ["tailor"], 14), ("Ramu Kewat", "Lucknow", ["helper"], 4),
    ("Ajay Thakur", "Lucknow", ["driver"], 8), ("Kishore Das", "Hyderabad", ["welder"], 10), ("Srinivas Goud", "Hyderabad", ["painter"], 7),
    ("Salma Begum", "Hyderabad", ["house_help"], 6), ("Naveen Kumar", "Hyderabad", ["mechanic", "electrician"], 9),
]

EMPLOYERS = [
    ("Sunita Sharma", "Indore"), ("Rajesh Agrawal", "Indore"), ("Neha Kulkarni", "Pune"), ("Rohit Deshpande", "Pune"),
    ("Vikram Malhotra", "Delhi"), ("Shalini Gupta", "Delhi"), ("Farhan Qureshi", "Mumbai"), ("Meera Iyer", "Mumbai"),
    ("Kavya Reddy", "Bengaluru"), ("Amit Jain", "Jaipur"), ("Arvind Mishra", "Lucknow"), ("Priya Menon", "Hyderabad"),
]

BIOS = [
    "{skill} ka kaam {y} saal se kar raha hoon. {city} mein kahin bhi aa sakta hoon.",
    "{y} years as a {skill_l}. I bring my own tools and clean up after the job.",
    "Ghar, dukaan aur office sab ka kaam kiya hai. Time ka pakka, kaam saaf.",
    "Worked with contractors on big sites for {y} years, now taking direct work in {city}.",
    "{skill} ka poora anubhav. Pehle kaam dekh kar sahi rate bataunga, koi chhupa kharcha nahi.",
    "Reliable {skill_l}, {y} years of experience. Available on weekends too.",
    "Apne gaon se aakar {city} mein {y} saal se kaam kar raha hoon. Bharosemand aur imaandaar.",
    "Small repairs or full jobs, both done neatly. Can start the same day if nearby.",
]
SKILL_EN = {"house_help": "house help", "security_guard": "security guard", "helper": "construction helper"}

REVIEWS = {
    5: ["Kaam bahut saaf kiya, time pe aaye.", "Very neat work, finished a day early.", "Polite and skilled. Will hire again.",
        "Ekdum badhiya kaam, rate bhi sahi tha.", "Explained everything before starting. Excellent.", "Site ko saaf karke gaye. Highly recommended."],
    4: ["Achha kaam kiya, bas ek din late shuru hua.", "Good work, needed a small fix later which he did free.", "Kaam theek tha, baat-cheet achhi."],
    3: ["Work was okay, took longer than expected.", "Theek-thaak kaam, thoda aur dhyan dena chahiye tha."],
}

CHATS = [
    ("worker", "Namaste ji, main kal subah 9 baje pahunch jaunga."),
    ("employer", "Theek hai. Gate pe guard ko mera naam bata dena."),
    ("worker", "Saaman aap layenge ya main le aaun?"),
    ("employer", "Material maine le liya hai, aap bas apne tools le aana."),
    ("worker", "Ji, ho jayega. Location bhej dijiye."),
]


def jitter(lat, lng, km=6):
    d = km / 111
    return round(lat + random.uniform(-d, d), 5), round(lng + random.uniform(-d, d), 5)


def days_for(title):
    """Realistic job length from the kind of work."""
    t = title.lower()
    if any(k in t for k in ("function", "install", "two-wheeler", "tank", "texture", "repair", "shifting", "unloading", "ac servicing", "leakage", "sink")):
        return random.choice([1, 1, 2])
    if any(k in t for k in ("daily", "weekly", "guard", "night", "rush", "family car", "family of", "boutique")):
        return random.choice([15, 30, 30])
    if any(k in t for k in ("trip",)):
        return 4
    return random.choice([2, 3, 3, 4, 5, 7])


def wage(skill, city):
    lo, hi = WAGES[skill]
    w = random.randint(lo, hi) * (1.15 if city in METRO else 1)
    return int(round(w / 50) * 50)


def ago(days_max, days_min=0):
    return NOW - timedelta(days=random.uniform(days_min, days_max), minutes=random.randint(0, 600))


def showcase(db, workers, employers):
    """A fixed, guaranteed story for the two demo accounts so every screen has content."""
    w = {u.name: u for u, _, _ in workers}
    ramesh, sunita, rajesh = w["Ramesh Yadav"], employers[0][0], employers[1][0]
    (clat, clng), _ = CITIES["Indore"]

    def job(emp, title, desc, skill, area, wage_, days, status="open", urgent=False, created=None, n=1):
        lat, lng = jitter(clat, clng, km=3)
        j = Job(employer_id=emp.id, title=title, description=desc, skill=skill, city="Indore", area=area, lat=lat, lng=lng,
                wage_per_day=wage_, days=days, workers_needed=n, status=status, urgent=urgent, created_at=created or ago(1))
        db.add(j)
        db.flush()
        return j

    def apply(j, worker, status="applied", when=None, updated=None):
        a = Application(job_id=j.id, worker_id=worker.id, status=status, created_at=when or j.created_at + timedelta(minutes=random.randint(5, 90)))
        a.updated_at = updated or a.created_at
        db.add(a)
        db.flush()
        return a

    # Open jobs near Ramesh (one urgent)
    j1 = job(rajesh, "Paint shop front and shutter", "Agrawal Hardware, Palasia. Shutter enamel paint and front wall. Shop stays open, work after 2 pm.",
             "painter", "Palasia", 850, 2, urgent=True, created=NOW - timedelta(minutes=38))
    job(rajesh, "Texture paint on one living room wall", "Feature wall 12x10 ft. Design will be shown on phone.", "painter", "Vijay Nagar", 900, 1,
        created=NOW - timedelta(hours=5))
    apply(j1, w["Deepak Rathore"])

    # Sunita's open job with three applicants (Ramesh among them)
    j2 = job(sunita, "Paint 2BHK flat before Diwali", JOBS["painter"][0][1], "painter", "Sudama Nagar", 800, 4, created=NOW - timedelta(hours=20))
    for name in ("Sohan Lal Verma", "Deepak Rathore", "Ramesh Yadav"):
        apply(j2, w[name])
    j3 = job(sunita, "Install 6 fans and 10 LED lights", JOBS["electrician"][1][1], "electrician", "Sudama Nagar", 950, 1,
             created=NOW - timedelta(hours=3), urgent=True)
    apply(j3, w["Akash Verma"])

    # Ramesh is currently hired by Sunita for another job, chat in progress
    j4 = job(sunita, "Putty and paint for kids' room", "One room 11x12 ft, light blue colour. Furniture will be covered.", "painter", "Sudama Nagar",
             800, 2, status="filled", created=NOW - timedelta(days=1, hours=4))
    a4 = apply(j4, ramesh, "on_the_way", updated=NOW - timedelta(minutes=12))
    for k, (side, text) in enumerate(CHATS):
        db.add(Message(application_id=a4.id, sender_id=ramesh.id if side == "worker" else sunita.id, text=text,
                       created_at=a4.created_at + timedelta(minutes=15 + k * 9)))

    # Completed work this month with reviews, so earnings and ratings show
    for title, emp, stars, comment, days_ago in [
        ("Exterior wall painting, G+1 house", rajesh, 5, "Kaam bahut saaf kiya, time pe aaye.", 6),
        ("Putty and primer for new office", sunita, 5, "Very neat work, finished a day early.", 13),
        ("Repaint society gate and grills", rajesh, 4, "Achha kaam kiya, bas ek din late shuru hua.", 24),
    ]:
        created = NOW - timedelta(days=days_ago + 3)
        j = job(emp, title, "", "painter", random.choice(CITIES["Indore"][1]), 800, 3, status="closed", created=created)
        a = apply(j, ramesh, "completed", updated=NOW - timedelta(days=days_ago))
        db.add(Rating(application_id=a.id, from_user_id=emp.id, to_user_id=ramesh.id, stars=stars, comment=comment, created_at=a.updated_at + timedelta(hours=2)))

    # Unread notifications for the bell
    for user, kind, data, link, mins in [
        (ramesh, "job:new", {"id": j1.id, "title": j1.title, "wage_per_day": j1.wage_per_day}, "/work", 38),
        (ramesh, "chat:notify", {"application_id": a4.id, "from": sunita.name, "text": CHATS[-2][1]}, f"/chat/{a4.id}", 70),
        (sunita, "job:application", {"job_id": j3.id, "title": j3.title, "application": {"worker_name": "Akash Verma"}}, f"/hire/{j3.id}", 150),
        (sunita, "job:status", {"application_id": a4.id, "job_id": j4.id, "title": j4.title, "status": "on_the_way", "by": ramesh.name}, f"/hire/{j4.id}", 12),
    ]:
        db.add(Notification(user_id=user.id, kind=kind, data=json.dumps(data, ensure_ascii=False), link=link, created_at=NOW - timedelta(minutes=mins)))


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    pw = hash_password(PASSWORD)  # same demo password for every account
    db = SessionLocal()

    workers, employers = [], []
    for i, (name, city, skills, years) in enumerate(WORKERS, 1):
        u = User(name=name, phone=f"90000{i:05d}", password_hash=pw, role="worker", city=city, created_at=ago(400, 60))
        db.add(u)
        db.flush()
        (lat, lng), _ = CITIES[city]
        lat, lng = jitter(lat, lng)
        sk = SKILL_EN.get(skills[0], skills[0])
        bio = random.choice(BIOS).format(y=years, city=city, skill=sk.capitalize(), skill_l=sk)
        db.add(WorkerProfile(user_id=u.id, skills=",".join(skills), experience_years=years, daily_wage=wage(skills[0], city),
                             city=city, lat=lat, lng=lng, bio=bio, available=random.random() > 0.15))
        workers.append((u, city, skills))
    for i, (name, city) in enumerate(EMPLOYERS, 1):
        u = User(name=name, phone=f"90001{i:05d}", password_hash=pw, role="employer", city=city, created_at=ago(300, 30))
        db.add(u)
        db.flush()
        employers.append((u, city))

    by_city_skill = {}
    for u, city, skills in workers:
        for s in skills:
            by_city_skill.setdefault((city, s), []).append(u)

    jobs_made = 0
    for emp, city in employers:
        (clat, clng), areas = CITIES[city]
        city_skills = sorted({s for (c, s) in by_city_skill if c == city})
        for n in range(random.randint(4, 6)):
            skill = random.choice(city_skills + ["helper", "cleaner", "painter"])
            title, desc = random.choice(JOBS[skill])
            lat, lng = jitter(clat, clng)
            state = random.choices(["open", "active", "done"], weights=[5, 2, 4])[0]
            created = ago(2, 0) if state == "open" else ago(6, 1) if state == "active" else ago(45, 7)
            job = Job(employer_id=emp.id, title=title, skill=skill, description=desc, city=city, area=random.choice(areas),
                      lat=lat, lng=lng, wage_per_day=wage(skill, city), days=days_for(title),
                      workers_needed=random.choice([1, 1, 1, 2, 3]) if skill in ("helper", "delivery", "security_guard") else 1,
                      urgent=state == "open" and random.random() < 0.25, status="open", created_at=created)
            db.add(job)
            db.flush()
            jobs_made += 1
            pool = by_city_skill.get((city, skill), [])
            applicants = random.sample(pool, k=min(len(pool), random.randint(0, 3)))
            for j, w in enumerate(applicants):
                a = Application(job_id=job.id, worker_id=w.id, status="applied", created_at=created + timedelta(minutes=random.randint(4, 300)))
                db.add(a)
                db.flush()
                if state == "open":
                    continue
                if j == 0:
                    a.status = random.choice(["hired", "on_the_way", "arrived"]) if state == "active" else "completed"
                    a.updated_at = created + timedelta(days=job.days, hours=random.randint(1, 20))
                    for k, (side, text) in enumerate(CHATS[: random.randint(2, len(CHATS))]):
                        db.add(Message(application_id=a.id, sender_id=w.id if side == "worker" else emp.id, text=text,
                                       created_at=a.created_at + timedelta(minutes=20 + k * 7)))
                    if a.status == "completed":
                        stars = random.choices([5, 4, 3], weights=[6, 3, 1])[0]
                        db.add(Rating(application_id=a.id, from_user_id=emp.id, to_user_id=w.id, stars=stars,
                                      comment=random.choice(REVIEWS[stars]), created_at=a.updated_at + timedelta(hours=2)))
                        db.add(Rating(application_id=a.id, from_user_id=w.id, to_user_id=emp.id, stars=random.choice([4, 5, 5]),
                                      comment="", created_at=a.updated_at + timedelta(hours=3)))
                else:
                    a.status = "rejected"
            if state == "active":
                job.status = "filled" if applicants else "open"
            elif state == "done":
                job.status = "closed"

    showcase(db, workers, employers)
    db.commit()

    print(f"Seeded {len(workers)} workers, {len(employers)} employers, {jobs_made} jobs across {len(CITIES)} cities.\n")
    print("Demo logins (password for every account: demo1234)")
    print(f"  Worker   {workers[0][0].phone}  {workers[0][0].name}, painter, Indore")
    print(f"  Employer {employers[0][0].phone}  {employers[0][0].name}, Indore")
    db.close()


if __name__ == "__main__":
    main()
