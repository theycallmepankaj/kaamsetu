from math import asin, cos, radians, sin, sqrt


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1, lng1, lat2, lng2 = map(radians, (lat1, lng1, lat2, lng2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def distance_between(a_lat, a_lng, b_lat, b_lng) -> float | None:
    if None in (a_lat, a_lng, b_lat, b_lng):
        return None
    return round(haversine_km(a_lat, a_lng, b_lat, b_lng), 1)


def is_nearby(a_lat, a_lng, a_city: str, b_lat, b_lng, b_city: str, radius_km: float) -> bool:
    """Within radius when both have GPS; otherwise fall back to same city name."""
    d = distance_between(a_lat, a_lng, b_lat, b_lng)
    if d is not None:
        return d <= radius_km
    return bool(a_city) and a_city.strip().lower() == (b_city or "").strip().lower()
