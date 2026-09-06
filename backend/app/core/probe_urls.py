"""Network policy for existing administrator-only UzEx diagnostic probes."""
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_PROBE_HOSTS = frozenset({"etender.uzex.uz", "apietender.uzex.uz"})


def validate_probe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_PROBE_HOSTS
                or parsed.port not in {None, 443} or parsed.username or parsed.password
                or "\\" in value or any(ord(char) < 32 for char in value)):
            raise ValueError()
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise ValueError("Unsupported probe destination") from None
    return value


def guard_probe_context(context):
    # Applied to every redirected page/subresource request, including popups.
    def route_request(route):
        try:
            validate_probe_url(route.request.url)
        except ValueError:
            route.abort("blockedbyclient")
        else:
            route.continue_()
    context.route("**/*", route_request)
