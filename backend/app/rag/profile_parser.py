"""Turn "Main electrician hoon, 5 saal ka experience, Indore mein" into profile fields."""

import logging
import re

import anthropic
from pydantic import BaseModel

from ..config import get_settings
from ..schemas import ProfileSuggestion
from ..skills import SKILLS
from .llm import get_client

log = logging.getLogger("kaamsetu.profile")
settings = get_settings()

CITIES = {
    "Delhi": ["delhi", "dilli", "दिल्ली"], "Mumbai": ["mumbai", "bombay", "मुंबई"], "Bengaluru": ["bengaluru", "bangalore", "बेंगलुरु", "बैंगलोर"],
    "Hyderabad": ["hyderabad", "हैदराबाद"], "Chennai": ["chennai", "चेन्नई"], "Kolkata": ["kolkata", "calcutta", "कोलकाता"],
    "Pune": ["pune", "पुणे"], "Ahmedabad": ["ahmedabad", "अहमदाबाद"], "Surat": ["surat", "सूरत"], "Jaipur": ["jaipur", "जयपुर"],
    "Lucknow": ["lucknow", "लखनऊ"], "Kanpur": ["kanpur", "कानपुर"], "Nagpur": ["nagpur", "नागपुर"], "Indore": ["indore", "इंदौर"],
    "Bhopal": ["bhopal", "भोपाल"], "Patna": ["patna", "पटना"], "Vadodara": ["vadodara", "baroda", "वडोदरा"], "Ludhiana": ["ludhiana", "लुधियाना"],
    "Agra": ["agra", "आगरा"], "Nashik": ["nashik", "नासिक"], "Varanasi": ["varanasi", "banaras", "वाराणसी", "बनारस"], "Ranchi": ["ranchi", "रांची"],
    "Raipur": ["raipur", "रायपुर"], "Chandigarh": ["chandigarh", "चंडीगढ़"], "Guwahati": ["guwahati", "गुवाहाटी"], "Kochi": ["kochi", "cochin", "कोच्चि"],
    "Coimbatore": ["coimbatore", "कोयंबटूर"], "Visakhapatnam": ["visakhapatnam", "vizag", "विशाखापत्तनम"], "Bhubaneswar": ["bhubaneswar", "भुवनेश्वर"],
    "Noida": ["noida", "नोएडा"], "Gurugram": ["gurugram", "gurgaon", "गुरुग्राम"], "Rajkot": ["rajkot", "राजकोट"], "Jodhpur": ["jodhpur", "जोधपुर"],
}


def _keyword_parse(text: str) -> ProfileSuggestion:
    low = text.lower()
    skills = [k for k, v in SKILLS.items() if any(w in low for w in v["words"])]
    exp = re.search(r"(\d{1,2})\s*(?:\+\s*)?(?:saal|sal|years?|yrs?|varsh|वर्ष|साल)", low)
    wage = re.search(r"(?:₹|rs\.?|inr)\s*(\d{3,5})|(\d{3,5})\s*(?:rupaye|rupees?|rupay|rs|₹|रुपये|रुपए)", low)
    city = next((name for name, words in CITIES.items() if any(w in low for w in words)), None)
    return ProfileSuggestion(
        skills=skills[:6],
        experience_years=int(exp.group(1)) if exp else None,
        daily_wage=int(wage.group(1) or wage.group(2)) if wage else None,
        city=city,
        bio=text.strip()[:300],
    )


class _Extracted(BaseModel):
    skills: list[str]
    experience_years: int | None
    daily_wage_rupees: int | None
    city: str | None
    short_bio_in_users_language: str | None


async def parse_profile_text(text: str) -> ProfileSuggestion:
    client = get_client()
    if client is None:
        return _keyword_parse(text)

    skill_list = ", ".join(f"{k} ({v['en']})" for k, v in SKILLS.items())
    try:
        response = await client.messages.parse(
            model=settings.claude_model,
            max_tokens=16000,
            output_config={"effort": "low"},
            system=(
                "You extract a worker's job profile from what they said (Hindi, English or Hinglish). "
                f"Allowed skill keys: {skill_list}. Use only these keys. "
                "Use null for anything the worker did not say. Do not guess numbers. "
                "Write the bio as one or two plain sentences in the worker's language, without personal ID numbers."
            ),
            messages=[{"role": "user", "content": f"<worker_said>{text}</worker_said>"}],
            output_format=_Extracted,
        )
    except anthropic.APIError as e:
        log.warning("Profile parse via Claude failed (%s); using keyword parser", type(e).__name__)
        return _keyword_parse(text)

    data = response.parsed_output
    if response.stop_reason == "refusal" or data is None:
        return _keyword_parse(text)
    return ProfileSuggestion(
        skills=[s for s in data.skills if s in SKILLS][:6],
        experience_years=data.experience_years if data.experience_years is not None and 0 <= data.experience_years <= 60 else None,
        daily_wage=data.daily_wage_rupees if data.daily_wage_rupees is not None and 0 < data.daily_wage_rupees <= 100000 else None,
        city=(data.city or None) and data.city[:60],
        bio=(data.short_bio_in_users_language or "")[:500] or None,
    )
