from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import logging
import traceback
from typing import TYPE_CHECKING
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import socket

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
from async_timeout import timeout

from .exceptions import NoSessionError
from proxy_manager import NordVpnProxyManager, ConnectorContext

from .session_context import SessionContext


###logger###
logger = logging.getLogger(__name__)

def _log_aexit(context, exc_t, exc_v, exc_tb):
	if isinstance(exc_t, asyncio.exceptions.CancelledError):
			logger.warning(f'exiting {context} due to {exc_t}')
	elif any((exc_t, exc_v, exc_tb)):
		logger.error(f'{exc_t=} | {exc_v=} | exc_tb={traceback.format_tb(exc_tb)}')
###default###



###class definitions###


###monkey patching: https://github.com/aio-libs/aiohttp/discussions/6044#discussioncomment-1432443###
setattr(asyncio.sslproto._SSLProtocolTransport, "_start_tls_compatible", True) # type: ignore





@dataclass(slots=True, unsafe_hash=True)
class SessionManager:
	session_contexts: set[SessionContext] = field(init=False, default_factory=set, hash=False)
	exhausted_sessions_context_ids: set[UUID] = field(init=False, default_factory=set, hash=False)
	#socks_proxies: list = field(init=False, default_factory=list)
	active_sessions: int = 4
	activation_timeout: int = 600
	proxy_manager: NordVpnProxyManager = field(default_factory=NordVpnProxyManager)
	session_context_substitution_interval: timedelta | None = None
	session_context_substitution_min_activations: int = 0

	_rotations: int = 0
	_stopwatch: Stopwatch = field(default_factory=Stopwatch)
	_session_context_substitution_task: asyncio.Task | None = field(init=False, default = None)
	_session_context_creation_tasks: set[asyncio.Task] = field(init=False, default_factory=set)

	def __post_init__(self):
		if self.session_context_substitution_interval is None:
			pass
		elif isinstance(self.session_context_substitution_interval, int):
			self.session_context_substitution_interval = timedelta(seconds = self.session_context_substitution_interval)
		else:
			raise TypeError(f'session_context_substitution_interval must be of None, timedelta or int but is {self.session_context_substitution_interval}')

	async def __aenter__(self) -> SessionManager:
		if self.session_context_substitution_interval:
			self._session_context_substitution_task = await self._create_session_context_substitution_task()
			logger.info(f'session_context_substitution_task created')
		try:
			return await self.activate(timeout = self.activation_timeout)
		except TimeoutError:
			logger.exception(f'handled exception will be reraised')
			if self._session_context_substitution_task:
				self._session_context_substitution_task.cancel()
				await self._session_context_substitution_task
			raise
		except Exception:
			logger.exception(f'unhandled exception')

	async def __aexit__(self, exc_t, exc_v, exc_tb):
		_log_aexit(self, exc_t, exc_v, exc_tb)
		if self._session_context_substitution_task:
			self._session_context_substitution_task.cancel()
			await self._session_context_substitution_task
		await asyncio.gather(*self._session_context_creation_tasks)
		await self.close_all()

	async def _create_session_context_substitution_task(self, timeout:int = 600):
		async def func():
			session_context_substitution_expiration_utc = \
				datetime.utcnow() + self.session_context_substitution_interval
			while 1:
				if datetime.utcnow() > session_context_substitution_expiration_utc:				
					try:
						session_context = await self.get_session_context()
						if session_context.activations > self.session_context_substitution_min_activations:
							logger.info(f'selected session_context for substitution: {session_context}')
							session_context.disable(reason = 'session_context_substitution_task')
							await self.pool_session_context()
							await self.rotate(session_context = session_context, timeout = timeout)
						session_context_substitution_expiration_utc = \
							datetime.utcnow() + self.session_context_substitution_interval
					except TimeoutError:
						logger.error(f'timeout')		
					except KeyError:
						_wake_up_utc = datetime.utcnow() + timedelta(seconds = int(timeout/60))
						logger.warning(f'KeyError -> will sleep until {_wake_up_utc:%Y-%m-%d %H:%M%S}')
						while datetime.utcnow() < _wake_up_utc:
							await asyncio.sleep(1)
					except Exception:
						logger.exception(f'unhandled exception -> returning')
						return		
				await asyncio.sleep(1)

		return asyncio.create_task(func())


	async def pool_session_context(self, timeout:int | None = 600):
		with Stopwatch() as stopwatch:
			#await asyncio.sleep(0)
			try:
	
				proxies = self.proxy_manager.socks_proxies
				while 1:
					proxy = proxies.pop(0)
					proxies.append(proxy)

					#session_context = await self.proxy_manager.get_session_context(timeout=timeout)
					session_context = await self.create_session_context(host = proxy['domain'], proxy_type=ProxyType.SOCKS5)
					session_context.manager = self
					try:
						async with (await session_context.session).get('https://api.ipify.org') as response:
							if response.status == 200:
								pass
							else:
								logger.warning(f'proxy {proxy} is not working -> got status {response.status}')
								continue
					except LoginAuthenticationFailed:
						logger.warning(f'proxy {proxy} is not working -> LoginAuthenticationFailed')
						try:
							session_context.session.close()
						except Exception:
							pass
						del session_context
						continue


					self.session_contexts.add(session_context)
					logger.info(f'new session context added to pool: {session_context}')
					break
			except Exception:
				logger.exception(f'')
		logger.debug(f'pooled session in {stopwatch.elapsed().microseconds/1000} ms')

	async def activate(self, timeout) -> SessionManager:
		with self._stopwatch.reset():
			self.session_contexts.clear()
			self._session_context_creation_tasks = {asyncio.create_task(self.pool_session_context(timeout = None)) for _ in range(self.active_sessions)}
			self._rotations = 0
			_timeout_reached = datetime.utcnow() + timedelta(seconds = timeout)
			while not timeout or datetime.utcnow() <= _timeout_reached:
				for task in self._session_context_creation_tasks:
					await asyncio.sleep(0)
					if task.done():
						await task
						logger.info(f'activate completed in {self._stopwatch.elapsed().microseconds/1000} ms')
						self._session_context_creation_tasks.remove(task)
						return self
				await asyncio.sleep(1)
			raise TimeoutError(f'failed to activate within {self.activation_timeout} seconds')
	
			
	async def get_session_context(self, trials: int = 10) -> SessionContext:
		_trials = 0
		_log_prefix = f'get_session_context-{uuid4()}'
		while _trials < trials:
			await asyncio.sleep(0)
			try:
		
				session_context = self.session_contexts.pop()
				if session_context.is_disabled():
					self.exhausted_sessions_context_ids.add(session_context.id)
					try:
						await session_context.close()
					except Exception:
						logger.exception(f'{_log_prefix}: unhandled exceptions -> ignored')				
					continue
				self.session_contexts.add(session_context)

				### experimental: trying to burn the session_context with most activations first
				def _sort_key(session_context: SessionContext):
					if session_context.is_disabled():
						return session_context.activations * (-1)
					return session_context.activations

				session_context = sorted([*self.session_contexts], key = _sort_key).pop()

				return session_context
			except KeyError:
				_sleep_duration = _trials**2
				logger.warning(f'{_log_prefix}: will sleep: {_sleep_duration}')
				await asyncio.sleep(_sleep_duration)
				_trials += 1
			except Exception:
				logger.exception(f'{_log_prefix}: unhandled exception will be reraised')
				raise
		raise NoSessionError(f'{_log_prefix}: failed to get any session')

	async def maintain_session_context_creation_tasks(self):
		for task in self._session_context_creation_tasks.copy():
			if task.done():
				try:
					self._session_context_creation_tasks.remove(task)
					logger.debug(f'removed completed session_context_creation_task')
				except Exception:
					logger.exception(f'unhandled exception will be ignored')
			else:
				logger.info(f'running task: {task.get_name()}')


	async def rotate(self, session_context: SessionContext, timeout: int = 60):
		"""timeout in seconds"""

		session_context.disable()
		await self.maintain_session_context_creation_tasks()
		if not session_context.id in self.exhausted_sessions_context_ids:
			
			if len(self._session_context_creation_tasks) >= self.active_sessions:
				logger.warning(f'active session_context_creation_tasks: {len(self._session_context_creation_tasks)}, active_sessions: {self.active_sessions} ')
				return
			self._session_context_creation_tasks.add(asyncio.create_task(self.pool_session_context(timeout = None), name=f'{datetime.utcnow().isoformat()}'))
			logger.info(f'session_context_creation_task added (total: {len(self._session_context_creation_tasks)}) to replace session_context: {session_context}')
		return

	async def close_all(self):
		await self.maintain_session_context_creation_tasks()
		for session_context in self.session_contexts:
			await session_context.close()

	async def create_session_context(self, host, proxy_type, port:int = 1080) -> SessionContext:
		connector_context = ConnectorContext(

			proxy_type=proxy_type,
			host=host,
			port=port,
			username=self.proxy_manager.user,
			password=self.proxy_manager.password,
			ttl_dns_cache = None,
			verify_ssl = False,
			limit_per_host = 10,
			family=socket.AF_INET,
			rdns = True
			#local_addr = ('localhost',None)
		)
		#connector = await self.create_socks_connector(proxy_type = proxy_type, host = host, port = port)
		return SessionContext(
			#session		= aiohttp.ClientSession(connector = connector),
			connector_context = connector_context,
			#proxy_type		  = proxy_type,
			proxy_host		  = host,
			proxy_port		  = port,
			proxy_url 		  = None,
			proxy_auth		  = None			
			)