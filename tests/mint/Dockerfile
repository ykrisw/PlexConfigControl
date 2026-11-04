# Browser-test userspace only. This is NOT a PlexConfigControl installer.
FROM linuxmintd/mint22.3-amd64@sha256:304bbf7ec2a61252962c5210467d231a141661490e8962f52fd4df7688370369
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates curl gnupg firefox mint-info-xfce fonts-liberation \
    && curl --fail --show-error --location https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --location https://deb.opera.com/archive.key -o /tmp/opera.key \
    && gpg --dearmor -o /usr/share/keyrings/opera-browser.gpg /tmp/opera.key \
    && echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/opera-browser.gpg] https://deb.opera.com/opera-stable/ stable non-free' > /etc/apt/sources.list.d/opera-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends opera-stable \
    && rm /tmp/opera.key && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/browser-test \
    && /opt/browser-test/bin/pip install 'selenium>=4.27,<5' 'cryptography>=44' 'playwright>=1.56,<2' \
    && useradd --create-home --uid 10001 pcc-browser
WORKDIR /work
COPY --chown=10001:10001 plexconfigcontrol/static /work/plexconfigcontrol/static
COPY --chown=10001:10001 tests/desktop_e2e.py tests/desktop_fixture.py tests/execution_ui_e2e.py tests/retail_opera.py tests/opera_e2e.py /work/tests/
RUN mkdir -p /work/dist && chown 10001:10001 /work/dist
USER 10001
ENV PATH="/opt/browser-test/bin:${PATH}" CI=true PCC_DESKTOP_TARGET=mint PCC_MINT_CONTAINER_CI_ONLY=1
CMD ["python", "tests/desktop_e2e.py"]
