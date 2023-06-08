from __future__ import annotations

from typing import Any
from aiohttp_proxy import ProxyConnector, ProxyType
from socket import AddressFamily
from dataclasses import dataclass, field

ProxyManager = Any

@dataclass(slots=True)
class ConnectorContext:        
	proxy_type: ProxyType
	host: str | None
	port: int | None
	username: str | None
	password: str | None
	family: AddressFamily | None
	ttl_dns_cache: None #missing type
	verify_ssl: bool | None #missing type
	limit_per_host: int | None #missing type
	rdns: bool = False
	kwargs: dict = field(default_factory=dict)
	manager: ProxyManager | None = None

	def connector(self) -> ProxyConnector:
		return ProxyConnector(
			proxy_type=self.proxy_type,
			host=self.host,
			port=self.port,
			username=self.username,
			password=self.password,
			ttl_dns_cache = self.ttl_dns_cache,
			verify_ssl = self.verify_ssl,
			limit_per_host = self.limit_per_host,
			#family=socket.AF_INET,
			rdns = self.rdns
			#local_addr = ('localhost',None)
		)


def proxy_connector_factory(proxy_type: ProxyType, host: str, port: int, username: str, password: str) -> ProxyConnector:
	return ProxyConnector(
		proxy_type=proxy_type,
		host=host,
		port=port,
		username=username,
		password=password,
		#ttl_dns_cache = None,
		#verify_ssl = False,
		#limit_per_host = 10,
	)

def https_proxy_connector_factory(host: str, port: int, username: str, password: str) -> ProxyConnector:
	return 	proxy_connector_factory(
		proxy_type=ProxyType.HTTPS,
		host=host,
		port=port,
		username=username,
		password=password,
		#ttl_dns_cache = None,
		#verify_ssl = False,
		#limit_per_host = 10,
	)

def socks_proxy_connector_factory(host: str, port: int, username: str, password: str) -> ProxyConnector:
	return proxy_connector_factory(
		proxy_type=ProxyType.SOCKS5,
		host=host,
		port=port,
		username=username,
		password=password,
		#ttl_dns_cache = None,
		#verify_ssl = False,
		#limit_per_host = 10,
		#family=socket.AF_INET,
		#rdns = True
		#local_addr = ('localhost',None)
	)