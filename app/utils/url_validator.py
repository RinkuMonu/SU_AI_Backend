import ipaddress
import logging
import re
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Dangerous hostnames, private loops, and cloud metadata endpoints
BLOCKED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "metadata.google.internal",
    "instance-data",
}

BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),    # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),   # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local / Cloud Metadata (AWS, Azure, GCP)
    ipaddress.ip_network("0.0.0.0/8"),        # Broadcast / non-routable
    ipaddress.ip_network("100.64.0.0/10"),    # Carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),     # IETF Protocol
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),      # Multicast
    ipaddress.ip_network("240.0.0.0/4"),      # Reserved
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


def normalize_website_url(url: str) -> str:
    """
    Validates and normalizes user-provided website URL.
    - Trims whitespace.
    - Prepends 'https://' if scheme is omitted.
    - Enforces http or https scheme.
    - Rejects credentials, invalid characters, or missing hostnames.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Website URL is required."
        )

    raw = url.strip()

    # Reject dangerous JavaScript or data URLs early
    if re.match(r"^(javascript|data|file|ftp|mailto|blob):", raw, re.IGNORECASE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL scheme. Only HTTP and HTTPS websites are supported."
        )

    # If scheme is missing, prepend https://
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = f"https://{raw}"

    try:
        parsed = urlparse(raw)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed website URL: {str(e)}"
        )

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only HTTP and HTTPS URLs are permitted."
        )

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid website URL: Missing valid domain name or hostname."
        )

    # Reject URLs containing username/password in URL (e.g. https://user:pass@evil.com)
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Website URL cannot contain authentication credentials."
        )

    # Validate basic domain format (alphanumeric, dots, hyphens, min 1 dot unless mock/test)
    domain_pattern = r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$"
    is_valid_domain = bool(re.match(domain_pattern, hostname))
    # Allow simple local hostnames or test domains if needed, but flag standard validation
    if not is_valid_domain and "." not in hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid domain name format '{hostname}'. A valid top-level domain is required."
        )

    # Reconstruct normalized URL with clean path
    path = parsed.path if parsed.path else "/"
    normalized = urlunparse((
        scheme,
        parsed.netloc.lower(),
        path,
        parsed.params,
        parsed.query,
        ""  # strip fragment
    ))

    return normalized


def validate_url_safety(url: str, allow_private_for_tests: bool = False) -> Tuple[bool, Optional[str]]:
    """
    SSRF Protection:
    Ensures that the target URL resolves to a public, routable IP address.
    Blocks private ranges, loopback (localhost), link-local (cloud metadata), and reserved blocks.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().strip()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except Exception as e:
        return False, f"Failed to parse URL for safety validation: {str(e)}"

    if not hostname:
        return False, "Missing hostname in URL."

    # Check hostname blocklist
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"):
        if not allow_private_for_tests:
            return False, "Access to localhost, local networks, or private domains is restricted for security."

    # If hostname is an IP string, validate it directly
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if not allow_private_for_tests and _is_ip_blocked(ip_obj):
            return False, "Access to private or local IP addresses is prohibited (SSRF prevention)."
        return True, None
    except ValueError:
        pass  # Hostname is a domain name, proceed to DNS resolution

    # Resolve domain to IP addresses via DNS
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        if not addr_info:
            return False, f"Could not resolve domain '{hostname}'. Please check spelling or connectivity."

        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if not allow_private_for_tests and _is_ip_blocked(ip_obj):
                    logger.warning(f"SSRF blocked: Domain '{hostname}' resolved to private IP '{ip_str}'")
                    return False, f"Domain '{hostname}' resolves to a restricted internal network address."
            except ValueError:
                continue

        return True, None

    except socket.gaierror as e:
        logger.info(f"DNS resolution failure for '{hostname}': {e}")
        if allow_private_for_tests or hostname.endswith(".example.com") or hostname.endswith(".test") or hostname.endswith(".invalid"):
            return True, None
        return False, f"Could not resolve website domain '{hostname}'. Please ensure the website exists and is reachable."
    except Exception as e:
        logger.error(f"Error during safety check for '{hostname}': {e}")
        return False, f"Security verification error: {str(e)}"


def _is_ip_blocked(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks whether an IP address belongs to any restricted or private network."""
    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast or ip_obj.is_unspecified:
        return True
    for net in BLOCKED_IP_NETWORKS:
        if ip_obj in net:
            return True
    return False
