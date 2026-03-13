FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY webui ./webui

EXPOSE 5000

CMD ["python", "webui/app.py"]
