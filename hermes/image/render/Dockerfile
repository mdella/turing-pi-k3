# Render service for Hermes' render_docs MCP in k3s: the same pinned headless Chromium image node1 used via
# `docker run`, plus python3 and server.py, plus Mermaid at /vendor (npm sha512 integrity-checked).
FROM docker.io/zenika/alpine-chrome@sha256:eb3378c1ed0079f94db054a5fe1aaa790a254ec0d6bbc67eda052420d86a179d

ARG MERMAID_VERSION=11.17.2
ARG MERMAID_INTEGRITY=sha512-V6K3C8EBdEsPFZXSKMJe6ppQOENxuHARr9GvHX4hh47lAbhMRD9qf4oEK7LoaRQxULMa80/qt5gHO73aCleBBg==

USER root
RUN set -eu; apk add --no-cache python3 curl; \
    curl -fsSL -o /tmp/mermaid.tgz https://registry.npmjs.org/mermaid/-/mermaid-${MERMAID_VERSION}.tgz; \
    want=$(echo "${MERMAID_INTEGRITY#sha512-}" | base64 -d | od -An -tx1 | tr -d ' \n'); \
    echo "$want  /tmp/mermaid.tgz" | sha512sum -c -; \
    mkdir -p /vendor && tar -xzf /tmp/mermaid.tgz -C /tmp package/dist/mermaid.min.js package/LICENSE; \
    mv /tmp/package/dist/mermaid.min.js /tmp/package/LICENSE /vendor/; rm -rf /tmp/package /tmp/mermaid.tgz; \
    apk del curl; chmod -R a+rX /vendor; mkdir -p /job && chown chrome:chrome /job
COPY --chmod=755 server.py /usr/local/bin/render-server
USER chrome
ENTRYPOINT []
CMD ["python3", "/usr/local/bin/render-server"]
