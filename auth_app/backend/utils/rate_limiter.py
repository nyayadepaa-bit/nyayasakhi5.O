"""Rate limiting with slowapi.

Provides a shared Limiter instance and a custom key function
that can use user_id from JWT or fall back to client IP.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request


def _get_key(request: Request) -> str:
    """Use user_id from JWT state if available, otherwise IP."""
    # After get_current_user runs the user is stashed on request.state
    user = getattr(request.state, "user", None)
    if user:
        return str(user.id)
    return get_remote_address(request)


limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
