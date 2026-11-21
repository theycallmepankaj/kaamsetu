from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory limits for one process. With several processes, pass
# storage_uri=settings.redis_url so limits are shared.
limiter = Limiter(key_func=get_remote_address, default_limits=["300/minute"])
