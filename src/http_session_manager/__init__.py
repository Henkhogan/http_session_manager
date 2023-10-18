try:
    from .session_manager import SessionManager, LoginAuthenticationFailed
except ImportError:
    pass
from .proxied import ProxiedHttpSessionManager
from .exceptions import NoSessionError