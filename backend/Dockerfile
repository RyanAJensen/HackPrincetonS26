FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DB_PATH=/data/unilert.db

WORKDIR /app/backend

COPY backend/requirements.txt /tmp/requirements.txt
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
RUN chmod +x /app/backend/entrypoint.sh /app/backend/start.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,sys,urllib.request; resp=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=4); data=json.load(resp); sys.exit(0 if data.get('status') != 'not_ready' else 1)"

CMD ["/app/backend/entrypoint.sh"]
