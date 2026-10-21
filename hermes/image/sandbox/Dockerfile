# Hermes tool sandbox for the "ssh" terminal backend, one pod per profile in k3s (see turing-pi-k3/hermes/sandbox/ssh/README.md).
# Same toolset as ../cheshire and ../luna, plus an unprivileged sshd: runs as uid 1000 on :2222, public-key only,
# host key and authorized_keys come from mounted Secrets/ConfigMaps (copied into /run/sshd by the entrypoint).
FROM python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
# python:3.12-slim-bookworm (multi-arch index, pinned 2026-10-09)
# OCR (2026-10-21): tesseract-ocr (English only; add tesseract-ocr-<lang> for more) + ocrmypdf, which adds a text
# layer to scanned PDFs so pymupdf/read_file can read them. Hard layouts/handwriting: render + vision instead.

RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git git-lfs gnupg jq less file zip unzip xz-utils \
      pandoc poppler-utils fonts-dejavu-core openssh-server \
      tesseract-ocr ocrmypdf \
 && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_*

RUN pip install --no-cache-dir \
      pypdf reportlab pdfplumber pymupdf python-docx "python-pptx>=0.6" openpyxl markdown matplotlib

RUN useradd -u 1000 -m -s /bin/bash sandbox && mkdir -p /workspace && chown 1000:1000 /workspace
COPY sshd_config /etc/ssh/sshd_config.d/sandbox.conf
COPY --chmod=755 entrypoint.sh /usr/local/bin/sandbox-sshd
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
USER 1000
WORKDIR /workspace
EXPOSE 2222
CMD ["/usr/local/bin/sandbox-sshd"]
