import json
import logging


site_queries_logger = logging.getLogger("site_queries")
robots_queries_logger = logging.getLogger("robots_queries")


class SiteQueryLoggingMiddleware:
    """
    Logs all inbound HTTP requests with source IP and query context.

    /robots.txt requests are additionally mirrored into a dedicated robots log.
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

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = None
        try:
            response = self.get_response(request)
            return response
        finally:
            self._log_request(request, response)

    def _log_request(self, request, response):
        status_code = response.status_code if response is not None else 500
        log_payload = {
            "ip": self._client_ip(request),
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
        site_queries_logger.info(message)

        if request.path == "/robots.txt":
            robots_queries_logger.info(message)

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
