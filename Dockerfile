# The server only runs the website and the Claude scoring. Fetching from
# EurekAlert! happens on team members' computers (see collect.py), so there's
# no browser in this image and it stays small.
FROM python:3.12-slim

# tini reaps the scoring processes the web app starts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY eureka ./eureka
COPY web ./web
# collect.py and collector/ are served as the fetcher download on the Fetch page.
COPY collector ./collector
COPY agent.py collect.py editorial_profile.md ./

ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

ENTRYPOINT ["/usr/bin/tini", "--"]
# One worker on purpose: the scoring queue lives in this process.
CMD ["python3", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
