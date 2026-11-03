FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PCC_STATE_DIRECTORY=/var/lib/plexconfigcontrol PCC_PORT=8443
WORKDIR /opt/plexconfigcontrol
COPY pyproject.toml ./
COPY plexconfigcontrol ./plexconfigcontrol
RUN pip install --no-cache-dir '.[server]' \
    && groupadd --gid 568 pcc \
    && useradd --uid 568 --gid 568 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin pcc \
    && mkdir -p /var/lib/plexconfigcontrol \
    && chown 568:568 /var/lib/plexconfigcontrol
USER 568:568
EXPOSE 8443
VOLUME ["/var/lib/plexconfigcontrol"]
HEALTHCHECK --interval=30s --timeout=8s --start-period=30s --retries=3 \
    CMD ["python", "-m", "plexconfigcontrol.healthcheck"]
ENTRYPOINT ["python", "-m", "plexconfigcontrol.runtime"]
