"""Skill catalogue shared by profiles, jobs and the profile parser."""

SKILLS: dict[str, dict] = {
    "electrician": {"en": "Electrician", "hi": "इलेक्ट्रीशियन", "words": ["electrician", "bijli", "wiring", "बिजली", "इलेक्ट्रीशियन", "वायरिंग"]},
    "plumber": {"en": "Plumber", "hi": "प्लंबर", "words": ["plumber", "plumbing", "nal", "pipe", "प्लंबर", "नल", "पाइप"]},
    "carpenter": {"en": "Carpenter", "hi": "बढ़ई", "words": ["carpenter", "furniture", "badhai", "bdhai", "बढ़ई", "फर्नीचर", "लकड़ी"]},
    "painter": {"en": "Painter", "hi": "पेंटर", "words": ["painter", "paint", "putty", "पेंटर", "पेंट", "रंगाई", "पुट्टी"]},
    "mason": {"en": "Mason", "hi": "राजमिस्त्री", "words": ["mason", "mistri", "rajmistri", "tiles", "राजमिस्त्री", "मिस्त्री", "टाइल"]},
    "helper": {"en": "Construction helper", "hi": "मजदूर / हेल्पर", "words": ["helper", "labour", "labor", "majdoor", "mazdoor", "मजदूर", "हेल्पर"]},
    "driver": {"en": "Driver", "hi": "ड्राइवर", "words": ["driver", "driving", "ड्राइवर", "गाड़ी"]},
    "cook": {"en": "Cook", "hi": "रसोइया", "words": ["cook", "khana", "chef", "रसोइया", "खाना", "कुक"]},
    "house_help": {"en": "House help", "hi": "घरेलू काम", "words": ["maid", "house help", "kaamwali", "bai", "घरेलू", "बाई", "सफाई वाली"]},
    "cleaner": {"en": "Cleaner", "hi": "सफाई कर्मी", "words": ["cleaner", "cleaning", "safai", "सफाई"]},
    "security_guard": {"en": "Security guard", "hi": "सिक्योरिटी गार्ड", "words": ["guard", "security", "chowkidar", "गार्ड", "चौकीदार"]},
    "delivery": {"en": "Delivery", "hi": "डिलीवरी", "words": ["delivery", "courier", "डिलीवरी"]},
    "welder": {"en": "Welder", "hi": "वेल्डर", "words": ["welder", "welding", "वेल्डर", "वेल्डिंग"]},
    "mechanic": {"en": "Mechanic", "hi": "मैकेनिक", "words": ["mechanic", "repair", "मैकेनिक", "मरम्मत"]},
    "tailor": {"en": "Tailor", "hi": "दर्जी", "words": ["tailor", "darzi", "silai", "दर्जी", "सिलाई"]},
    "gardener": {"en": "Gardener", "hi": "माली", "words": ["gardener", "mali", "garden", "माली", "बगीचा"]},
}

SKILL_KEYS = set(SKILLS)
