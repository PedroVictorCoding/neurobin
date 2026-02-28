from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import RequestIPPathStat, RequestIPProfile


logger = logging.getLogger(__name__)


def _clean_text(value, *, limit: int = 0) -> str:
    text = "" if value is None else str(value).strip()
    if limit > 0:
        return text[:limit]
    return text


def _to_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_public_ip(ip_address: str) -> bool:
    try:
        return ipaddress.ip_address(ip_address).is_global
    except ValueError:
        return False


def _parse_abuse_datetime(value) -> timezone.datetime | None:
    raw = _clean_text(value)
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def compute_throttle_limit(confidence_score: int | None) -> int | None:
    score = _to_int(confidence_score)
    if score is None:
        return None

    score = max(0, min(100, score))
    threshold = int(getattr(settings, "ABUSE_THROTTLE_CONFIDENCE_THRESHOLD", 50))
    if score <= threshold:
        return None

    base_limit = int(getattr(settings, "ABUSE_THROTTLE_BASE_LIMIT_PER_HOUR", 5))
    step_percent = max(1, int(getattr(settings, "ABUSE_THROTTLE_STEP_PERCENT", 10)))
    step_reduction = max(1, int(getattr(settings, "ABUSE_THROTTLE_STEP_REDUCTION", 1)))
    min_limit = max(0, int(getattr(settings, "ABUSE_THROTTLE_MIN_LIMIT_PER_HOUR", 0)))

    reduction_steps = max(0, (score - threshold) // step_percent)
    limit = base_limit - (reduction_steps * step_reduction)
    return max(min_limit, limit)


def get_or_create_ip_profile(ip_address: str, *, observed_at=None):
    ip_clean = _clean_text(ip_address, limit=64)
    if not ip_clean:
        return None, False

    try:
        ipaddress.ip_address(ip_clean)
    except ValueError:
        return None, False

    seen_at = observed_at or timezone.now()
    profile, created = RequestIPProfile.objects.get_or_create(
        ip_address=ip_clean,
        defaults={
            "first_seen_at": seen_at,
            "last_seen_at": seen_at,
        },
    )
    return profile, created


def refresh_abuseipdb_profile(profile: RequestIPProfile, *, force: bool = False) -> RequestIPProfile:
    refresh_hours = max(1, int(getattr(settings, "ABUSEIPDB_REFRESH_HOURS", 24)))
    now = timezone.now()

    if (
        not force
        and profile.abuse_checked_at
        and (now - profile.abuse_checked_at) < timedelta(hours=refresh_hours)
    ):
        return profile

    if not _is_public_ip(profile.ip_address):
        profile.abuse_checked_at = now
        profile.abuse_is_public = False
        profile.abuse_confidence_score = 0
        profile.is_throttle_active = False
        profile.throttle_limit_per_hour = None
        profile.abuse_check_error = "IP is not public."
        profile.save(
            update_fields=[
                "abuse_checked_at",
                "abuse_is_public",
                "abuse_confidence_score",
                "is_throttle_active",
                "throttle_limit_per_hour",
                "abuse_check_error",
                "updated_at",
            ]
        )
        return profile

    api_key = _clean_text(getattr(settings, "ABUSEIPDB_API_KEY", ""))
    if not api_key:
        return profile

    endpoint = _clean_text(getattr(settings, "ABUSEIPDB_CHECK_ENDPOINT", "https://api.abuseipdb.com/api/v2/check"))
    max_age_days = max(1, int(getattr(settings, "ABUSEIPDB_MAX_AGE_DAYS", 90)))
    timeout_seconds = max(1, int(getattr(settings, "ABUSEIPDB_TIMEOUT_SECONDS", 6)))
    user_agent = _clean_text(getattr(settings, "ABUSEIPDB_USER_AGENT", "neurobin-ip-analytics/1.0"))

    try:
        response = requests.get(
            endpoint,
            params={
                "ipAddress": profile.ip_address,
                "maxAgeInDays": max_age_days,
                "verbose": "",
            },
            headers={
                "Accept": "application/json",
                "Key": api_key,
                "User-Agent": user_agent,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        data = payload.get("data") if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
    except (requests.RequestException, ValueError) as exc:
        profile.abuse_checked_at = now
        profile.abuse_check_error = _clean_text(exc, limit=500)
        profile.save(update_fields=["abuse_checked_at", "abuse_check_error", "updated_at"])
        logger.debug("AbuseIPDB lookup failed for %s: %s", profile.ip_address, exc)
        return profile

    confidence_score = _to_int(data.get("abuseConfidenceScore"))
    throttle_limit = compute_throttle_limit(confidence_score)

    hostnames = data.get("hostnames")
    if not isinstance(hostnames, list):
        hostnames = []
    hostnames = [_clean_text(value, limit=255) for value in hostnames if _clean_text(value)]

    profile.abuse_checked_at = now
    profile.abuse_confidence_score = confidence_score
    profile.abuse_total_reports = _to_int(data.get("totalReports"))
    profile.abuse_num_distinct_users = _to_int(data.get("numDistinctUsers"))
    profile.abuse_last_reported_at = _parse_abuse_datetime(data.get("lastReportedAt"))
    profile.abuse_usage_type = _clean_text(data.get("usageType"), limit=255)
    profile.abuse_isp = _clean_text(data.get("isp"), limit=255)
    profile.abuse_domain = _clean_text(data.get("domain"), limit=255)
    profile.abuse_country_code = _clean_text(data.get("countryCode"), limit=8)
    profile.abuse_country_name = _clean_text(data.get("countryName"), limit=128)
    profile.abuse_hostnames = hostnames
    profile.abuse_is_public = data.get("isPublic")
    profile.abuse_is_whitelisted = data.get("isWhitelisted")
    profile.abuse_check_error = ""
    profile.is_throttle_active = throttle_limit is not None
    profile.throttle_limit_per_hour = throttle_limit
    profile.save(
        update_fields=[
            "abuse_checked_at",
            "abuse_confidence_score",
            "abuse_total_reports",
            "abuse_num_distinct_users",
            "abuse_last_reported_at",
            "abuse_usage_type",
            "abuse_isp",
            "abuse_domain",
            "abuse_country_code",
            "abuse_country_name",
            "abuse_hostnames",
            "abuse_is_public",
            "abuse_is_whitelisted",
            "abuse_check_error",
            "is_throttle_active",
            "throttle_limit_per_hour",
            "updated_at",
        ]
    )
    return profile


def ensure_ip_profile(ip_address: str, *, observed_at=None, refresh_abuse: bool = False):
    profile, created = get_or_create_ip_profile(ip_address, observed_at=observed_at)
    if profile is None:
        return None, False
    if refresh_abuse:
        refresh_abuseipdb_profile(profile, force=created)
    return profile, created


def record_site_request(log_payload: dict, *, observed_at=None):
    profile, created = ensure_ip_profile(
        log_payload.get("ip", ""),
        observed_at=observed_at,
        refresh_abuse=False,
    )
    if profile is None:
        return None

    seen_at = observed_at or timezone.now()
    method = _clean_text(log_payload.get("method", "GET"), limit=10).upper() or "GET"
    path = _clean_text(log_payload.get("path", ""), limit=512)
    status_code = _to_int(log_payload.get("status_code"))
    last_user_agent = _clean_text(log_payload.get("user_agent"))
    last_user = _clean_text(log_payload.get("user"), limit=150)

    method_field = "other_requests"
    if method == "GET":
        method_field = "get_requests"
    elif method == "POST":
        method_field = "post_requests"

    update_kwargs = {
        "last_seen_at": seen_at,
        "last_path": path,
        "last_user_agent": last_user_agent,
        "last_user": last_user,
        "total_requests": F("total_requests") + 1,
        method_field: F(method_field) + 1,
    }
    if status_code is not None and status_code >= 400:
        update_kwargs["error_requests"] = F("error_requests") + 1

    RequestIPProfile.objects.filter(pk=profile.pk).update(**update_kwargs)

    if path:
        with transaction.atomic():
            path_already_tracked = RequestIPPathStat.objects.select_for_update().filter(
                ip_profile_id=profile.pk,
                path=path,
            ).exists()
            path_stat, path_created = RequestIPPathStat.objects.select_for_update().get_or_create(
                ip_profile_id=profile.pk,
                path=path,
                method=method,
                defaults={"request_count": 0, "last_seen_at": seen_at},
            )
            RequestIPPathStat.objects.filter(pk=path_stat.pk).update(
                request_count=F("request_count") + 1,
                last_seen_at=seen_at,
            )
            if path_created and not path_already_tracked:
                RequestIPProfile.objects.filter(pk=profile.pk).update(distinct_paths=F("distinct_paths") + 1)

    if created and getattr(settings, "ABUSEIPDB_AUTO_ENRICH_NEW_IPS", True):
        refresh_abuseipdb_profile(profile, force=True)

    return profile
