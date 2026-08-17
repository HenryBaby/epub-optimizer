FROM python:3.12-slim AS production

ARG EPUBCHECK_VERSION=5.3.0
ARG EPUBCHECK_SHA256=6C07E68584B2E2CE2F89FE06E1246DFEAD3EB36B46B340E7D93524F29DCFF6C5

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV EPUBCHECK_JAR=/opt/epubcheck/epubcheck.jar
ENV JAVA=java

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY THIRD_PARTY_NOTICES.md ./
COPY src ./src

RUN pip install --no-cache-dir .

# Official EPUBCheck distribution and a headless Java runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/epubcheck \
    && curl -fsSL "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip" -o /tmp/epubcheck.zip \
    && echo "$EPUBCHECK_SHA256  /tmp/epubcheck.zip" | sha256sum -c - \
    && unzip -q /tmp/epubcheck.zip -d /opt/epubcheck \
    && ln -s /opt/epubcheck/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar /opt/epubcheck/epubcheck.jar \
    && mkdir -p /usr/share/doc/epub-optimizer \
    && cp /app/LICENSE /app/THIRD_PARTY_NOTICES.md /usr/share/doc/epub-optimizer/ \
    && rm /tmp/epubcheck.zip

RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /data /watch /output /failed /unprocessed \
    && chown -R appuser:appuser /data /watch /output /failed /unprocessed

USER appuser

EXPOSE 4200

HEALTHCHECK --interval=30s --timeout=5s CMD java -version >/dev/null 2>&1 && test -f /opt/epubcheck/epubcheck.jar

CMD ["uvicorn", "epub_optimizer.web:app", "--host", "0.0.0.0", "--port", "4200"]

# Development keeps the production image's Python, Java, and EPUBCheck setup,
# then adds only the repository's optional development dependencies.
FROM production AS development

USER root
RUN pip install --no-cache-dir -e ".[dev]"
USER appuser

# Keep the Dockerfile's default target production-compatible for existing
# Compose files and CI jobs that do not specify a build target.
FROM production AS runtime
