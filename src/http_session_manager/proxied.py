from dataclasses import dataclass, field
from typing import Self
from aiohttp import ClientSession
from .session_context import SessionContext

def proxied_http_session_factory():
	return ClientSession(trust_env=True)

def _http_session_pool_factory(size: int = 4) -> list[ClientSession]:
	return [proxied_http_session_factory() for _ in range(size)]


@dataclass(slots=True, unsafe_hash=True)
class ProxiedHttpSessionManager:
	'''Expects proxy configuration to be set in the environment variables.'''

	_http_session_pool: list[ClientSession] = field(init=False, default_factory=_http_session_pool_factory)
	async def __aenter__(self) -> Self:
		[await _.__aenter__() for _ in self._http_session_pool]
		return self

	async def __aexit__(self, exc_t, exc_v, exc_tb):
		[await _.__aexit__(exc_t, exc_v, exc_tb) for _ in self._http_session_pool]

	async def get_session_context(self, trials: int = 10) -> SessionContext:
		_http_session = self._http_session_pool.pop(0)
		self._http_session_pool.append(_http_session)
		return SessionContext(_session = _http_session)
	
	async def rotate(self, session_context: SessionContext, timeout: int = 60):
		"""timeout in seconds"""
		try:
			self._http_session_pool.remove(session_context._session)
			await session_context._session.close()
			_session = proxied_http_session_factory()
			await _session.__aenter__()
			self._http_session_pool.append(_session)
		except ValueError:
			pass