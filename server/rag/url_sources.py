"""Fetch bounded public web pages, checking destinations again on redirects."""
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests


def _public_destination(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public http:// or https:// URL without login credentials.')
    host = parsed.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        raise ValueError('Private website addresses cannot be imported.')
    addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Private website addresses cannot be imported.')


def fetch_page(url):
    started = time.monotonic()
    with requests.Session() as session:
        session.trust_env = False
        current = url
        for _ in range(6):
            if time.monotonic() - started > 45:
                raise ValueError('The page took too long to respond. Try this URL again later.')
            _public_destination(current)
            with session.get(current, timeout=(5, 15), allow_redirects=False, stream=True,
                             headers={'User-Agent': 'BookyAI-Knowledge/1.0'}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    destination = response.headers.get('Location')
                    if not destination:
                        raise ValueError('The page returned a redirect without a destination.')
                    current = urljoin(current, destination)
                    continue
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').lower()
                if content_type and not (content_type.startswith('text/') or 'application/xhtml+xml' in content_type):
                    raise ValueError('This URL does not return a text or HTML page. Upload files separately.')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    if time.monotonic() - started > 45:
                        raise ValueError('The page took too long to download. Try this URL again later.')
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ValueError('This page is too large to import. Use a smaller page or upload a text document.')
                    chunks.append(chunk)
                return b''.join(chunks)
    raise ValueError('The page redirected too many times.')
