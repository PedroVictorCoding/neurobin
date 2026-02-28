import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone


site_queries_logger = logging.getLogger("site_queries")
bot_queries_logger = logging.getLogger("bot_queries")
internal_queries_logger = logging.getLogger("internal_queries")
robots_queries_logger = logging.getLogger("robots_queries")
security_queries_logger = logging.getLogger("security_queries")


class SiteQueryLoggingMiddleware:
    """
    Routes inbound request logs into site/bot/internal streams.

    /robots.txt requests are mirrored into a dedicated robots log when not internal.
    """

    SENSITIVE_KEYS = {
        "password",
        "password1",
        "password2",
        "token",
        "access",
        "refresh",
        "csrfmiddlewaretoken",
    }
    DEFAULT_BOT_UA_SUBSTRINGS = (
        "bot",
        "crawler",
        "spider",
        "scrapy",
        "curl",
        "go-http-client",
        "python-requests",
        "libwww",
        "wget",
        "headless",
        "phantom",
        "semrush",
        "ahrefs",
        "mj12",
        "oai-searchbot",
        "chatgpt-user",
        "censys",
        "openintel",
        "faviconhash",
        "domhash",
        "cms-checker",
        "palo alto networks",
        "google-read-aloud",
        "discordbot",
        "telegrambot",
        "facebookexternalhit",
        "twitterbot",
        "linkedinbot",
        "whatsapp",
    )
    LOCAL_IPS = {"127.0.0.1"}

    def __init__(self, get_response):
        self.get_response = get_response
        configured = getattr(settings, "BOT_QUERY_UA_SUBSTRINGS", self.DEFAULT_BOT_UA_SUBSTRINGS)
        self.bot_ua_substrings = tuple(
            token.lower().strip()
            for token in configured
            if isinstance(token, str) and token.strip()
        )

    def __call__(self, request):
        response = None
        try:
            response = self.get_response(request)
            return response
        finally:
            self._log_request(request, response)

    def _log_request(self, request, response):
        status_code = response.status_code if response is not None else 500
        client_ip = self._client_ip(request)
        log_payload = {
            "ip": client_ip,
            "method": request.method,
            "path": request.path,
            "full_path": request.get_full_path(),
            "query_params": self._sanitized_query_params(request),
            "status_code": status_code,
            "user": (
                request.user.get_username()
                if getattr(request, "user", None) and request.user.is_authenticated
                else "anonymous"
            ),
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "referer": request.META.get("HTTP_REFERER", ""),
        }

        message = json.dumps(log_payload, sort_keys=True, ensure_ascii=True)
        user_agent = log_payload["user_agent"]
        is_internal = client_ip in self.LOCAL_IPS
        is_bot = self._is_bot_user_agent(user_agent)

        if is_internal:
            internal_queries_logger.info(message)
        elif is_bot:
            bot_queries_logger.info(message)
        else:
            site_queries_logger.info(message)

        if request.path == "/robots.txt" and not is_internal:
            robots_queries_logger.info(message)

        try:
            from logs.ip_analytics import record_site_request

            record_site_request(log_payload, observed_at=timezone.now())
        except Exception as exc:  # pragma: no cover - defensive logging path
            logging.getLogger(__name__).debug("IP analytics tracking skipped: %s", exc)

    def _client_ip(self, request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    def _sanitized_query_params(self, request):
        if not request.GET:
            return {}
        out = {}
        for key in request.GET.keys():
            values = request.GET.getlist(key)
            safe_key = str(key)
            if safe_key.lower() in self.SENSITIVE_KEYS:
                out[safe_key] = ["[REDACTED]"] if values else "[REDACTED]"
            elif len(values) == 1:
                out[safe_key] = values[0]
            else:
                out[safe_key] = values
        return out

    def _is_bot_user_agent(self, user_agent):
        if not user_agent:
            return False
        ua_lower = user_agent.lower()
        return any(token in ua_lower for token in self.bot_ua_substrings)


class BotBlocklistMiddleware:
    """
    Blocks configured low-value crawler user agents while leaving SEO crawlers untouched.
    """

    CRAWLER_METHODS = {"GET", "HEAD"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_blocked_request(request):
            return HttpResponse("Blocked bot.\n", status=403, content_type="text/plain")
        return self.get_response(request)

    def _is_blocked_request(self, request):
        if not getattr(settings, "BOT_BLOCKLIST_ENABLED", True):
            return False

        if request.method not in self.CRAWLER_METHODS:
            return False

        user_agent = (request.META.get("HTTP_USER_AGENT", "") or "").strip()
        if not user_agent:
            return False

        if self._matches_any(user_agent, getattr(settings, "BOT_ALLOWLIST_UA_SUBSTRINGS", ())):
            return False

        return self._matches_any(user_agent, getattr(settings, "BOT_BLOCKLIST_UA_SUBSTRINGS", ()))

    @staticmethod
    def _matches_any(user_agent, substrings):
        ua_lower = user_agent.lower()
        for token in substrings:
            if token and token.lower() in ua_lower:
                return True
        return False


class ExploitAttemptBlocklistMiddleware:
    """
    Auto-blocks IPs that request high-signal exploit/scanner paths such as /.env.
    """

    DEFAULT_TRUSTED_IPS = {"127.0.0.1", "::1"}
    DEFAULT_PATH_INDICATORS = (
        "/.env",
        "/.git/",
        "/.git/config",
        "/.svn/",
        "/.hg/",
        "/wp-admin/",
        "/wp-content/",
        "/wp-includes/",
        "/xmlrpc.php",
        "/phpmyadmin",
        "/pma/",
        "/adminer.php",
        "/vendor/phpunit/",
        "/cgi-bin/",
        "/boaform/admin/formlogin",
        "/.aws/",
        "/.ssh/",
        "/id_rsa",
        "/.ds_store",
        "/.well-known/security.txt",
        "/server-status",
        "/debug/default/view",
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "EXPLOIT_BLOCKLIST_ENABLED", True)
        self.trusted_ips = {
            ip.strip()
            for ip in getattr(settings, "EXPLOIT_TRUSTED_IPS", self.DEFAULT_TRUSTED_IPS)
            if isinstance(ip, str) and ip.strip()
        }
        self.path_indicators = tuple(
            indicator.lower().strip()
            for indicator in getattr(settings, "EXPLOIT_PATH_INDICATORS", self.DEFAULT_PATH_INDICATORS)
            if isinstance(indicator, str) and indicator.strip()
        )
        self.block_timeout_seconds = int(getattr(settings, "EXPLOIT_BLOCK_TIMEOUT_SECONDS", 30 * 24 * 60 * 60))
        self.cache_prefix = str(getattr(settings, "EXPLOIT_BLOCKED_IP_CACHE_PREFIX", "exploit_blocked_ip"))

    def __call__(self, request):
        if not self.enabled:
            return self.get_response(request)

        client_ip = self._client_ip(request)
        if not client_ip or client_ip in self.trusted_ips:
            return self.get_response(request)

        if self._is_blocked(client_ip):
            return HttpResponse("Blocked IP.\n", status=403, content_type="text/plain")

        full_path = request.get_full_path()
        if self._is_exploit_path(full_path):
            self._block_ip(client_ip)
            self._log_block(client_ip=client_ip, request=request, reason="exploit-path")
            return HttpResponse("Blocked IP.\n", status=403, content_type="text/plain")

        return self.get_response(request)

    def _cache_key(self, ip):
        return f"{self.cache_prefix}:{ip}"

    def _is_blocked(self, ip):
        return bool(cache.get(self._cache_key(ip)))

    def _block_ip(self, ip):
        cache.set(self._cache_key(ip), True, timeout=self.block_timeout_seconds)

    def _is_exploit_path(self, full_path):
        path_lower = (full_path or "").lower()
        return any(indicator in path_lower for indicator in self.path_indicators)

    @staticmethod
    def _client_ip(request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    @staticmethod
    def _log_block(client_ip, request, reason):
        payload = {
            "ip": client_ip,
            "method": request.method,
            "path": request.path,
            "full_path": request.get_full_path(),
            "reason": reason,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "referer": request.META.get("HTTP_REFERER", ""),
        }
        security_queries_logger.warning(json.dumps(payload, sort_keys=True, ensure_ascii=True))


class AbuseConfidenceThrottleMiddleware:
    """
    Throttles abusive IPs based on stored AbuseIPDB confidence score.

    Policy (defaults):
    - confidence <= 50: no throttle
    - confidence > 50: 5 requests/hour
    - every +10 confidence points reduces limit by 1 request/hour (minimum 1/hour)
    """

    DEFAULT_TRUSTED_IPS = {"127.0.0.1", "::1"}
    DEFAULT_EXEMPT_PREFIXES = ("/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = bool(getattr(settings, "ABUSE_THROTTLE_ENABLED", True))
        self.cache_prefix = str(getattr(settings, "ABUSE_THROTTLE_CACHE_PREFIX", "abuse_throttle"))
        self.trusted_ips = {
            ip.strip()
            for ip in getattr(settings, "EXPLOIT_TRUSTED_IPS", self.DEFAULT_TRUSTED_IPS)
            if isinstance(ip, str) and ip.strip()
        }
        configured_prefixes = getattr(settings, "ABUSE_THROTTLE_EXEMPT_PATH_PREFIXES", self.DEFAULT_EXEMPT_PREFIXES)
        self.exempt_prefixes = tuple(
            prefix.strip()
            for prefix in configured_prefixes
            if isinstance(prefix, str) and prefix.strip()
        )

    def __call__(self, request):
        if not self.enabled:
            return self.get_response(request)

        if any(request.path.startswith(prefix) for prefix in self.exempt_prefixes):
            return self.get_response(request)

        client_ip = self._client_ip(request)
        if not client_ip or client_ip in self.trusted_ips:
            return self.get_response(request)

        throttle_limit = self._get_throttle_limit(client_ip)
        if throttle_limit is None:
            return self.get_response(request)

        if throttle_limit == 0:
            response = HttpResponse(
                "Rate limit exceeded for this IP.\n",
                status=429,
                content_type="text/plain",
            )
            response["Retry-After"] = str(self._seconds_until_next_hour())
            response["X-RateLimit-Limit"] = "0"
            response["X-RateLimit-Remaining"] = "0"
            return response

        request_count, retry_after_seconds = self._increment_hourly_counter(client_ip)
        if request_count > throttle_limit:
            response = HttpResponse(
                "Rate limit exceeded for this IP.\n",
                status=429,
                content_type="text/plain",
            )
            response["Retry-After"] = str(retry_after_seconds)
            response["X-RateLimit-Limit"] = str(throttle_limit)
            response["X-RateLimit-Remaining"] = "0"
            return response

        response = self.get_response(request)
        remaining = max(0, throttle_limit - request_count)
        response["X-RateLimit-Limit"] = str(throttle_limit)
        response["X-RateLimit-Remaining"] = str(remaining)
        return response

    @staticmethod
    def _client_ip(request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")

    def _get_throttle_limit(self, client_ip: str) -> int | None:
        limit_cache_key = f"{self.cache_prefix}:limit:{client_ip}"
        cached = cache.get(limit_cache_key)
        if cached is not None:
            try:
                cached_int = int(cached)
            except (TypeError, ValueError):
                return None
            return None if cached_int < 0 else cached_int

        from logs.ip_analytics import ensure_ip_profile, refresh_abuseipdb_profile

        profile, _created = ensure_ip_profile(client_ip, observed_at=timezone.now(), refresh_abuse=False)
        if profile is None:
            cache.set(limit_cache_key, -1, timeout=300)
            return None

        if profile.abuse_checked_at is None and getattr(settings, "ABUSEIPDB_AUTO_ENRICH_NEW_IPS", True):
            profile = refresh_abuseipdb_profile(profile, force=True)

        throttle_limit = profile.throttle_limit_per_hour if profile.is_throttle_active else None
        cache.set(limit_cache_key, throttle_limit if throttle_limit is not None else -1, timeout=300)
        return throttle_limit

    def _increment_hourly_counter(self, client_ip: str) -> tuple[int, int]:
        now = timezone.now()
        bucket = now.strftime("%Y%m%d%H")
        key = f"{self.cache_prefix}:count:{client_ip}:{bucket}"

        retry_after_seconds = self._seconds_until_next_hour()

        if cache.add(key, 1, timeout=retry_after_seconds):
            return 1, retry_after_seconds

        try:
            value = int(cache.incr(key))
        except Exception:
            current = int(cache.get(key, 0) or 0) + 1
            cache.set(key, current, timeout=retry_after_seconds)
            value = current
        return value, retry_after_seconds

    @staticmethod
    def _seconds_until_next_hour() -> int:
        now = timezone.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        return max(1, int((next_hour - now).total_seconds()))
