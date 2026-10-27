# Hermes gateway + dashboard image for k3s (geekstyle). Upstream image, pinned by digest, plus our local layer:
#   - patches/ (Signal observer + name trigger, Haiku 5.5 defaults, API-server routes, SSH no-sync-back)
#   - extras Hermes would otherwise lazy-install at runtime into a read-only tree (honcho, ddgs, edge-tts)
#   - local MCP servers (S3, repos, render) and the timer scripts, under /opt/geekstyle
# Runs WITHOUT s6 in k8s: the pod command starts `hermes gateway run` / `hermes dashboard` directly as uid 1000 with
# HERMES_HOME=/home/ubuntu/.hermes (the state volume), so absolute paths in the existing configs keep working.
ARG HERMES_BASE=docker.io/nousresearch/hermes-agent:v0.22.5@sha256:9c5561579f3ffdf333401797094ac3a743738d6c25d40f4331c7bf77b694238d
FROM ${HERMES_BASE}

ARG MERMAID_VERSION=11.17.2
ARG MERMAID_INTEGRITY=sha512-V6K3C8EBdEsPFZXSKMJe6ppQOENxuHARr9GvHX4hh47lAbhMRD9qf4oEK7LoaRQxULMa80/qt5gHO73aCleBBg==

USER root

# 1. Local patches — fail the build if any hunk no longer applies.
COPY patches/ /opt/geekstyle/patches/
RUN cd /opt/hermes && for p in /opt/geekstyle/patches/*.patch; do echo "applying $p"; git apply --verbose "$p"; done

# 2. Extras Hermes would lazy-install at runtime (the tree is read-only here): ddgs + edge-tts at the versions this
#    release pins in pyproject.toml. Honcho memory left core for the plugin catalog; bundling it at the in-tree path
#    plugins/memory/honcho makes Hermes find it there first, so 0.22's startup migration (a runtime `plugins install`
#    from GitHub into a read-only tree) never runs. Commit = the 0.22.5 catalog's reviewed pin (plugin-catalog/honcho.yaml).
ARG HONCHO_PLUGIN_COMMIT=e2d2aba182862deeb846e5cd4a30a41bce0ed82a
ARG HONCHO_AI_VERSION=2.2.0
RUN set -eu; cd /opt/hermes; \
    pins=$(/opt/hermes/.venv/bin/python -c 'import tomllib; x=tomllib.load(open("pyproject.toml","rb"))["project"]["optional-dependencies"]; print(" ".join(p for e in ("ddgs","edge-tts") for p in x[e]))'); \
    echo "installing: $pins honcho-ai==${HONCHO_AI_VERSION}"; \
    uv=$(ls -d /opt/hermes/tools/uv-*/ | head -1)uv; \
    "$uv" pip install --no-cache --python /opt/hermes/.venv/bin/python $pins "honcho-ai==${HONCHO_AI_VERSION}"; \
    git init -q /tmp/honcho && cd /tmp/honcho && git fetch -q --depth 1 https://github.com/plastic-labs/honcho "${HONCHO_PLUGIN_COMMIT}" \
      && git checkout -q FETCH_HEAD && test "$(git rev-parse HEAD)" = "${HONCHO_PLUGIN_COMMIT}"; \
    cp -r /tmp/honcho/hermes-plugin-honcho /opt/hermes/plugins/memory/honcho; rm -rf /tmp/honcho; \
    printf 'plastic-labs/honcho@%s (hermes-plugin-honcho), bundled by the geekstyle image\n' "${HONCHO_PLUGIN_COMMIT}" > /opt/hermes/plugins/memory/honcho/BUNDLED; \
    /opt/hermes/.venv/bin/python -c 'import honcho, ddgs, edge_tts, boto3, markdown, mcp; print("extras ok")'

# 3. Our MCP servers + timer scripts, and the vendored Mermaid for render_docs (sha512 = npm integrity).
COPY local-mcp/ /opt/geekstyle/local-mcp/
COPY bin/ /opt/geekstyle/bin/
RUN set -eu; d=/opt/geekstyle/local-mcp/render/vendor; mkdir -p $d; \
    curl -fsSL -o /tmp/mermaid.tgz https://registry.npmjs.org/mermaid/-/mermaid-${MERMAID_VERSION}.tgz; \
    want=$(echo "${MERMAID_INTEGRITY#sha512-}" | base64 -d | od -An -tx1 | tr -d ' \n'); \
    echo "$want  /tmp/mermaid.tgz" | sha512sum -c -; \
    tar -xzf /tmp/mermaid.tgz -C /tmp package/dist/mermaid.min.js package/LICENSE; \
    mv /tmp/package/dist/mermaid.min.js /tmp/package/LICENSE $d/; rm -rf /tmp/package /tmp/mermaid.tgz; \
    echo "mermaid ${MERMAID_VERSION} from npm (sha512 verified). MIT — see LICENSE." > $d/VERSION; \
    chmod -R a+rX,go-w /opt/geekstyle; chmod 755 /opt/geekstyle/bin/*

# 4. Runtime identity: uid/gid 1000 "ubuntu" (owner of the migrated state), home = state volume mount point.
RUN set -eu; (getent group 1000 >/dev/null || groupadd -g 1000 ubuntu); \
    (getent passwd 1000 >/dev/null || useradd -u 1000 -g 1000 -M -d /home/ubuntu -s /bin/bash ubuntu); \
    mkdir -p /home/ubuntu && chown 1000:1000 /home/ubuntu
# HERMES_WRITE_SAFE_ROOT applies to every terminal backend, incl. the SSH sandboxes (cwd /workspace): allow those too.
ENV HOME=/home/ubuntu \
    HERMES_HOME=/home/ubuntu/.hermes \
    HERMES_WRITE_SAFE_ROOT=/home/ubuntu/.hermes:/workspace:/tmp \
    XDG_RUNTIME_DIR=/tmp/hermes-runtime \
    PATH=/opt/hermes/bin:/opt/hermes/.venv/bin:/opt/geekstyle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
USER 1000
WORKDIR /home/ubuntu/.hermes
# Default = gateway. The pod overrides per container (gateway / dashboard); bypasses the upstream s6 entrypoint.
ENTRYPOINT []
CMD ["/opt/hermes/.venv/bin/python", "-m", "hermes_cli.main", "gateway", "run"]
