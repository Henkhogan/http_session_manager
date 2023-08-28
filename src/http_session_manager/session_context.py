from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import logging
import traceback
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4, UUID
from datetime import datetime, timedelta

import aiohttp
from aiohttp.client import ClientSession
from aiohttp.client_exceptions import (
	ServerDisconnectedError, 
	ClientOSError, 
	ClientConnectionError, 
	ClientConnectorError,
	ContentTypeError
)
from aiohttp_proxy.errors import (
	NoAcceptableAuthMethods, 
	UnknownAuthMethod, 
	LoginAuthenticationFailed, 
	InvalidServerVersion, 
	InvalidServerReply,
	SocksError,
	SocksConnectionError,
	ProxyError
)

from aiohttp_proxy import ProxyConnector, ProxyType
from .exceptions import NoSessionError
from .connector_context import ConnectorContext

if TYPE_CHECKING:
    from .session_manager import SessionManager

###logger###
logger = logging.getLogger(__name__)


async def check_session(session: ClientSession, url:str = 'https://yahoofinance.com') -> tuple[bool, Exception | None]:
	
		try:
			
			async with session.get(url):
				return True, None


		except (KeyboardInterrupt, asyncio.exceptions.CancelledError) as ex:
			raise
			#logger.warning(f'{type(ex)} for proxy: {proxy_url} with dest: {url}')
			#return False, ex

		except LoginAuthenticationFailed as ex:
			#self.sleep_expiration = datetime.utcnow() + sleep_period
			#logger.warning(f'{type(ex)}: {proxy_url}. set sleep_expiration to {self.sleep_expiration}')
			#self.socks_proxies.append(proxy)
			return False, ex

		except SocksError as ex:
			#logger.error(f'handled error for dest: {dest} (proxy: {proxy}): {ex}. {len(proxies)} proxies remaining -> will continue')
			return False, ex


		except (NoAcceptableAuthMethods, UnknownAuthMethod, InvalidServerVersion, InvalidServerReply, SocksConnectionError, ProxyError) as ex:
			#logger.warning(f'{type(ex)}: {self.proxy}')
			#self.socks_proxies.append(proxy)

			#await asyncio.sleep(self.sleep_interval)
			return False, ex

		except (ServerDisconnectedError, ClientOSError,	ClientConnectionError, ClientConnectorError) as ex:
			#logger.warning(f'{type(ex)}: {self.proxy}')
			#self.socks_proxies.append(proxy)
			return False, ex

		except Exception as ex:
			#logger.exception(f'unhandled exception for proxy: {self.proxy} with dest: {url}')
			return False, ex


@dataclass(slots=True)
class SessionContext:
	id: UUID = field(init = False, default_factory=uuid4)

	created_utc: datetime = field(init = False, default_factory=datetime.utcnow)
	closed_utc: datetime | None = field(init = False, default = None)
	disabled_utc: datetime | None = field(init = False, default = None)
	disabled_reason: Any = field(init = False, default = None)
			
	connector_context: ConnectorContext | None = field(default=None, hash=False)
	proxy_auth: aiohttp.BasicAuth | None = field(default=None)
	proxy_type: ProxyType | None = field(default=None)
	proxy_host: str | None = field(default=None)
	proxy_port: int | None = field(default=None)
	proxy_url: str | None = field(default=None)
	manager: SessionManager | None = field(default=None, hash=False)
	active_clients: int = field(init=False, default=0)
	activations:int = field(init=False, default=0)

	_username: str | None = field(default = None)
	_password: str | None = field(default = None)
	_session: ClientSession | None = field(default = None)
	_connector: ProxyConnector | None = field(default=None)
	
	def __hash__(self):
		return hash(self.id)

	def __repr__(self) -> str:
		return f'<SessionContext(id={self.id}, created_utc={self.created_utc:%Y-%m-%d %H:%M:%S}, closed_utc={self.closed_utc}, disabled_utc={self.disabled_utc}, disabled_reason={self.disabled_reason} ,proxy_host={self.proxy_host}, proxy_port={self.proxy_port}, active_clients={self.active_clients}, activations={self.activations}>'

	@property
	async def session(self) -> ClientSession:
		if self._session is None or self._session.closed:
			self._session = await self.create_session()
		return self._session


	async def create_session(self, check_url: str | None = None) -> ClientSession:
		if self.connector_context:
			session = ClientSession(connector=self.connector_context.connector())
			if check_url:
				await check_session(session, check_url)
			return session

		return ClientSession()

	"""
	@staticmethod
	def create_socks5_session(host: str, port:int, username: str, password: str) -> aiohttp.ClientSession:		
		connector = ProxyConnector(
			proxy_type=ProxyType.SOCKS5,
			host=host,
			port=port,
			username=username,
			password=password,
			ttl_dns_cache = None,
			verify_ssl = False,
			limit_per_host = 10,
			family=socket.AF_INET,
			rdns = True
			#local_addr = ('localhost',None)
		)
		return aiohttp.ClientSession(connector = connector)

	@staticmethod
	def create_ssl_session(host: str, port:int, username: str, password: str) -> aiohttp.ClientSession:
		#return aiohttp.ClientSession()		
		connector = ProxyConnector(
			proxy_type=ProxyType.HTTPS,
			host=host,
			port=port,
			username=username,
			password=password,
			#ttl_dns_cache = None,
			#verify_ssl = False,
			#limit_per_host = 10,
		)
		return aiohttp.ClientSession(connector = connector)
	"""

	async def __aenter__(self) -> ClientSession:
		self.active_clients += 1
		self.activations += 1
		return await self.session

	async def __aexit__(self, exc_t, exc_v, exc_tb):
		self.active_clients -= 1


	def asdict(self) -> dict:
		return {
			'session': self._session,
			'proxy': self.proxy_url,
			'proxy_auth': self.proxy_auth
		}

	async def close(self) -> SessionContext:
		session = await self.session
		await session.close()
		if session.connector:
			await session.connector.close()
		self.closed_utc = datetime.utcnow()
		return self

	def disable(self, reason: Any = None):
		if self.is_disabled():
			return
		self.disabled_utc = datetime.utcnow()
		self.disabled_reason = reason

	def is_disabled(self):
		return (self.disabled_utc is not None)