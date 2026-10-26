# Playwright's image ships Chromium and its system libraries. Keep the tag in
# step with the playwright version pinned in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

# Xvfb gives Chromium a virtual screen (EurekAlert! refuses headless browsers);
# the app starts it only while a run is using the browser. tini reaps the
# processes Chromium and Xvfb leave behind.
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb tini tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY eureka ./eureka
COPY web ./web
COPY agent.py editorial_profile.md ./

ENV DATA_DIR=/data PYTHONUNBUFFERED=1 HEADLESS=false
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

ENTRYPOINT ["/usr/bin/tini", "--"]
# One worker on purpose: the scheduler and the run lock live in this process.
CMD ["python3", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
