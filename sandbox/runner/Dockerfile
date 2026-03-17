FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY sandbox/runner /app/sandbox_runner

EXPOSE 9001

CMD ["gunicorn", "--chdir", "/app/sandbox_runner", "--bind", "0.0.0.0:9001", "--worker-class", "gthread", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
