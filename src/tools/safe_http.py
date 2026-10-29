"""Research HTTP boundary: validated numeric sockets, verified hostname TLS.

Inherited proxies fail closed: a remote proxy's DNS cannot be constrained here.
No connection pooling, resolver fallback, automatic redirects, or transport retries.
"""
import http.client
import ipaddress
import os
import re
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.request import getproxies


class FetchBlocked(ValueError):
    pass


def _public(value):
    if type(value) is not str or '%' in value:
        raise FetchBlocked('invalid destination address')
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise FetchBlocked('invalid destination address') from None
    if (not ip.is_global or ip.is_multicast or ip.is_reserved or
            ip.is_loopback or ip.is_link_local or ip.is_unspecified or
            getattr(ip, 'ipv4_mapped', None) is not None or
            (ip.version == 4 and any(ip in ipaddress.ip_network(n) for n in
                ('192.0.0.0/24', '192.88.99.0/24'))) or
            (ip.version == 6 and (ip not in ipaddress.ip_network('2000::/3') or
                any(ip in ipaddress.ip_network(n) for n in
                    ('2001::/23', '2002::/16', '3fff::/20'))))):
        raise FetchBlocked('non-public destination refused')
    return ip


def _target(url):
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url:
        raise FetchBlocked('invalid URL characters')
    try:
        p = urlsplit(url)
        host, port = p.hostname, p.port
        if p.scheme not in ('http', 'https') or not host or not p.netloc or '@' in p.netloc or '%' in p.netloc:
            raise ValueError()
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        if p.netloc.endswith(':'):
            raise ValueError()
        if ':' in host:
            if not p.netloc.startswith('['): raise ValueError()
            ipaddress.IPv6Address(host)
            if p.netloc != '['+host+']'+(':'+str(port) if port else ''): raise ValueError()
        else:
            host = host.encode('idna').decode('ascii').lower()
            if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in host.split('.')):
                raise ValueError()
        if host in ('api.openai.com', 'api.tavily.com'):
            raise FetchBlocked('provider API endpoints are not source pages')
        # Reject libc's legacy IPv4 syntaxes rather than resolving them differently.
        try: literal = ipaddress.ip_address(host)
        except ValueError:
            if re.fullmatch(r'[0-9.]+', host) or any(x.startswith('0x') for x in host.split('.')):
                raise ValueError()
            literal = None
    except (ValueError, UnicodeError):
        raise FetchBlocked('invalid or forbidden URL authority') from None
    port = port or (443 if p.scheme == 'https' else 80)
    if literal is not None:
        addresses = [_public(str(literal))]
    else:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
            addresses = []
            for family, kind, proto, canon, addr in answers:
                if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM or proto != socket.IPPROTO_TCP:
                    raise FetchBlocked('unusable DNS answer')
                ip = _public(addr[0])
                if family != (socket.AF_INET if ip.version == 4 else socket.AF_INET6):
                    raise FetchBlocked('inconsistent DNS answer')
                addresses.append(ip)
            if not addresses: raise FetchBlocked('empty DNS answer')
        except OSError:
            raise FetchBlocked('DNS resolution failed') from None
    authority = '['+host+']' if ':' in host else host
    if port != (443 if p.scheme == 'https' else 80): authority += ':'+str(port)
    return p.scheme, host, port, authority, urlunsplit(('', '', p.path or '/', p.query, '')), addresses[0]


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, tls):
        super().__init__(host, port, timeout=30)
        self._address, self._tls = address, tls

    def connect(self):
        # socket.connect receives an ipaddress-produced numeric literal, never DNS.
        family = socket.AF_INET if self._address.version == 4 else socket.AF_INET6
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            endpoint = (str(self._address), self.port) if family == socket.AF_INET else (str(self._address), self.port, 0, 0)
            sock.connect(endpoint)
            if self._tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            self.sock = sock
        except BaseException:
            sock.close()
            raise


def read_public_url(url):
    """Read one public page, validating and pinning every redirect hop.

    No trusted-proxy enforcement contract exists, so proxy-configured runtimes
    are explicitly unavailable rather than silently bypassing required controls.
    """
    if (any(value for key, value in getproxies().items() if key.lower() != 'no') or
            any(value for key, value in os.environ.items() if key.lower() in
                ('http_proxy', 'https_proxy', 'all_proxy'))):
        raise FetchBlocked('research retrieval blocked: proxy destination enforcement unavailable')
    visited = set()
    for hop in range(6):
        target = _target(url)
        scheme, host, port, authority, path, ip = target
        identity = (scheme, authority, path)
        if identity in visited: raise FetchBlocked('redirect loop refused')
        visited.add(identity)
        conn = _PinnedConnection(host, port, ip, scheme == 'https')
        try:
            conn.request('GET', path, headers={'Host': authority, 'User-Agent': 'Mozilla/5.0 (compatible; autonomous-research/1.0)'})
            resp = conn.getresponse()
            try:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.getheader('Location')
                    if not location or hop == 5: raise FetchBlocked('invalid or excessive redirect')
                    if any(ord(c) <= 32 or ord(c) == 127 for c in location) or '\\' in location:
                        raise FetchBlocked('invalid redirect characters')
                    url = urljoin(url, location)
                    continue
                if not 200 <= resp.status < 300:
                    raise FetchBlocked('research HTTP request failed')
                return resp.read()
            finally:
                resp.close()
        finally:
            conn.close()
    raise FetchBlocked('redirect limit exceeded')
