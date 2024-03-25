from dataclasses import dataclass, field
from typing import Any, Self
from aiohttp import ClientSession, BaseConnector, TCPConnector

def proxied_http_session_factory(connector: BaseConnector | None = None, ttl_dns_cache: int = 300, keepalive_timeout:int = 60) -> ClientSession:
	connector_owner = False
	if connector is None:
		connector = TCPConnector(ttl_dns_cache=ttl_dns_cache, keepalive_timeout=keepalive_timeout)
		connector_owner = True
	return ClientSession(trust_env=True, connector=connector, connector_owner=connector_owner)

def _http_session_pool_factory(size: int = 4) -> list[ClientSession]:
	return [proxied_http_session_factory() for _ in range(size)]


@dataclass(slots=True, unsafe_hash=True)
class HttpSessionPool:
	connector_pool: list[TCPConnector]

	@classmethod
	def create(cls, session_pool_size: int = 4, connector_pool_size: int | None = None):
		return cls(
			connector_pool = [TCPConnector(ttl_dns_cache=300) for _ in range(connector_pool_size)]
		)
	
	async def __aenter__(self) -> Self:
		[await _.__aenter__() for _ in self.connector_pool]
		return self

	async def __aexit__(self, exc_t, exc_v, exc_tb):
		await [_.__aexit__(exc_t, exc_v, exc_tb) for _ in self.connector_pool]
	
	def session(self) -> ClientSession:
		connector = self.connector_pool.pop(0)
		self.connector_pool.append(connector)
		return ClientSession(trust_env=True, connector=connector, connector_owner=False)

@dataclass(slots=True, unsafe_hash=True)
class ProxiedHttpSessionManager:
	'''Expects proxy configuration to be set in the environment variables.'''
	_http_session_pool: list[ClientSession] = field(init=True, default_factory=_http_session_pool_factory)
	async def __aenter__(self) -> Self:
		[await _.__aenter__() for _ in self._http_session_pool]
		return self

	async def __aexit__(self, exc_t, exc_v, exc_tb):
		[await _.__aexit__(exc_t, exc_v, exc_tb) for _ in self._http_session_pool]

	@classmethod
	def create(cls, pool_size: int = 4):
		return cls(_http_session_pool = _http_session_pool_factory(size=pool_size))
	

	async def session(self):
		"""do not enter, exit, or close the returned session"""
		try:
			_http_session = self._http_session_pool.pop(0)
			if _http_session.closed:
				_http_session = proxied_http_session_factory()
		except IndexError:
			_http_session = proxied_http_session_factory()
			

		self._http_session_pool.append(_http_session)
		return _http_session
