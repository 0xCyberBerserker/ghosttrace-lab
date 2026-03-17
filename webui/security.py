import base64
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from flask import jsonify, request


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] | None = None):
        self._clock = clock or time.monotonic
        self._buckets = defaultdict(deque)

    def check(self, key: tuple[str, str], rule: RateLimitRule) -> int | None:
        now = self._clock()
        bucket = self._buckets[key]
        boundary = now - rule.window_seconds

        while bucket and bucket[0] <= boundary:
            bucket.popleft()

        if len(bucket) >= rule.limit:
            retry_after = max(1, int(bucket[0] + rule.window_seconds - now))
            return retry_after

        bucket.append(now)
        return None


def _parse_basic_auth(header_value: str) -> tuple[str, str] | None:
    if not header_value or not header_value.startswith("Basic "):
        return None

    token = header_value[6:].strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        return None

    if ":" not in decoded:
        return None

    username, password = decoded.split(":", 1)
    return username, password


def _security_config(app):
    return {
        "operator_username": app.config.get("OPERATOR_USERNAME", ""),
        "operator_password": app.config.get("OPERATOR_PASSWORD", ""),
        "rate_limit_upload": app.config.get("RATE_LIMIT_UPLOAD", RateLimitRule(limit=10, window_seconds=60)),
        "rate_limit_chat": app.config.get("RATE_LIMIT_CHAT", RateLimitRule(limit=30, window_seconds=60)),
        "rate_limit_reveal": app.config.get("RATE_LIMIT_REVEAL", RateLimitRule(limit=6, window_seconds=60)),
        "rate_limit_x64dbg": app.config.get("RATE_LIMIT_X64DBG", RateLimitRule(limit=30, window_seconds=60)),
    }


def _operator_auth_enabled(app) -> bool:
    config = _security_config(app)
    return bool(config["operator_username"] and config["operator_password"])


def _operator_auth_exempt() -> bool:
    if request.endpoint == "static":
        return True
    if request.path.startswith("/evidence/") and request.method == "POST":
        return True
    return False


def _build_unauthorized_response():
    response = jsonify({"error": "operator authentication required"})
    response.status_code = 401
    response.headers["WWW-Authenticate"] = 'Basic realm="GhostTrace Operator"'
    return response


def _client_identifier() -> str:
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded_for or request.remote_addr or "unknown"


def _limit_rule_for_request(app) -> tuple[str, RateLimitRule] | None:
    config = _security_config(app)
    if request.path == "/upload" and request.method == "POST":
        return ("upload", config["rate_limit_upload"])
    if request.path == "/chat" and request.method == "POST":
        return ("chat", config["rate_limit_chat"])
    if request.path == "/sandbox/windows_lab_credentials/reveal" and request.method == "POST":
        return ("windows_lab_reveal", config["rate_limit_reveal"])
    if request.path.startswith("/debug/x64dbg/"):
        return ("x64dbg", config["rate_limit_x64dbg"])
    return None


def init_security(app):
    limiter = InMemoryRateLimiter()

    @app.before_request
    def enforce_operator_auth():
        if not _operator_auth_enabled(app) or _operator_auth_exempt():
            return None

        provided = _parse_basic_auth(request.headers.get("Authorization", ""))
        if not provided:
            return _build_unauthorized_response()

        username, password = provided
        config = _security_config(app)
        if not (
            hmac.compare_digest(username, config["operator_username"])
            and hmac.compare_digest(password, config["operator_password"])
        ):
            return _build_unauthorized_response()
        return None

    @app.before_request
    def apply_rate_limits():
        rule_entry = _limit_rule_for_request(app)
        if not rule_entry:
            return None

        bucket_name, rule = rule_entry
        retry_after = limiter.check((bucket_name, _client_identifier()), rule)
        if retry_after is None:
            return None

        response = jsonify(
            {
                "error": "rate limit exceeded",
                "bucket": bucket_name,
                "retry_after_seconds": retry_after,
            }
        )
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

