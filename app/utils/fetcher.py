import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

# Strips trailing punctuation common in pasted URLs: "See https://example.com/job."
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_TRAILING_PUNCT = re.compile(r"[.,;!?]+$")

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),    # loopback
    ipaddress.ip_network("10.0.0.0/8"),      # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),   # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("100.64.0.0/10"),   # shared address space
]


def is_url(text: str) -> bool:
    """Returns True if text contains an http(s) URL."""
    return bool(_URL_RE.search(text))


def _resolve_and_validate(hostname: str) -> None:
    """Raise ValueError if hostname resolves to a private/reserved IP (SSRF protection)."""
    try:
        addr = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(addr)
    except (socket.gaierror, ValueError) as e:
        raise ValueError(f"Не удалось разрешить хост '{hostname}': {e}") from e
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            raise ValueError(f"URL ведёт на приватный адрес {ip} — запрещено")


async def fetch_job_text(source: str) -> str:
    """
    If source contains an http(s) URL, fetches it and returns extracted text.
    Otherwise returns source as-is (treat as raw job posting text).
    Raises ValueError on SSRF attempts or fetch errors.
    """
    match = _URL_RE.search(source)
    if not match:
        return source

    url = _TRAILING_PUNCT.sub("", match.group())
    parsed = urlparse(url)
    _resolve_and_validate(parsed.hostname or "")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        try:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при загрузке страницы: {e}") from e

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)
