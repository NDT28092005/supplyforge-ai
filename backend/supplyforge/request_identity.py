"""Request identity helpers shared by security middleware and views."""

import ipaddress

from django.conf import settings


def get_client_ip(request) -> str:
    """Return the peer IP unless a configured proxy supplied the client IP."""
    remote_addr = (request.META.get('REMOTE_ADDR') or '').strip()
    trusted_proxies = getattr(settings, 'TRUSTED_PROXY_IPS', ())

    def is_trusted_proxy(address: str) -> bool:
        try:
            remote_ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        for configured_proxy in trusted_proxies:
            try:
                if '/' in configured_proxy:
                    if remote_ip in ipaddress.ip_network(configured_proxy, strict=False):
                        return True
                elif remote_ip == ipaddress.ip_address(configured_proxy):
                    return True
            except ValueError:
                continue
        return False

    if is_trusted_proxy(remote_addr):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        candidates = [value.strip() for value in forwarded_for.split(',') if value.strip()]
        if candidates:
            candidate = candidates[0]
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass

        real_ip = (request.META.get('HTTP_X_REAL_IP') or '').strip()
        try:
            ipaddress.ip_address(real_ip)
            return real_ip
        except ValueError:
            pass

    try:
        ipaddress.ip_address(remote_addr)
        return remote_addr
    except ValueError:
        return 'unknown'
