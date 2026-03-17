import json
import logging
import os
import time
import uuid
from typing import Callable

from flask import g, jsonify, request


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        path = getattr(record, "path", None)
        if path:
            payload["path"] = path
        method = getattr(record, "method", None)
        if method:
            payload["method"] = method
        status_code = getattr(record, "status_code", None)
        if status_code is not None:
            payload["status_code"] = status_code
        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return json.dumps(payload, ensure_ascii=True)


def configure_json_logging(logger: logging.Logger) -> None:
    if getattr(logger, "_ghosttrace_json_logging", False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    logger._ghosttrace_json_logging = True


def init_observability(app, service_name: str, readiness_probe: Callable[[], dict]):
    configure_json_logging(app.logger)

    @app.before_request
    def assign_request_id():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.request_started_at = time.perf_counter()

    @app.after_request
    def attach_request_id(response):
        request_id = getattr(g, "request_id", None) or request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started_at = getattr(g, "request_started_at", None)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at is not None else None
        response.headers.setdefault("X-Request-ID", request_id)
        app.logger.info(
            f"{request.method} {request.path}",
            extra={
                "request_id": request_id,
                "path": request.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.get("/health")
    def health():
        readiness = readiness_probe()
        overall_status = "ok" if readiness.get("ready", False) else "degraded"
        return jsonify(
            {
                "status": overall_status,
                "service": service_name,
                "request_id": g.request_id,
                **readiness,
            }
        ), 200 if readiness.get("ready", False) else 503
