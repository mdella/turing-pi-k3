# Cheshire's tool sandbox (Hermes terminal backend "docker", profile cheshire only).
# Commands, file tools and execute_code run in a container from this image, with no network, all caps dropped
# except Hermes' minimum, as the host uid (not root), and only Cheshire's workspace + GnuPG dirs mounted.
# Build:  docker build -t cheshire-sandbox:<YYYYMMDD> .   (then set terminal.docker_image in the profile config)
FROM python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
# python:3.12-slim-bookworm (multi-arch index, pinned 2026-10-09)

RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git gnupg jq less file zip unzip xz-utils \
      pandoc poppler-utils fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# Document skills: pdf (pypdf/reportlab/pdfplumber/pymupdf), docx, pptx-author, xlsx; plus charts and Markdown.
RUN pip install --no-cache-dir \
      pypdf reportlab pdfplumber pymupdf python-docx "python-pptx>=0.6" openpyxl markdown matplotlib

# Unprivileged home for the host uid Hermes runs commands as (docker_run_as_host_user); GNUPGHOME is mounted here.
RUN useradd -u 1000 -m -s /bin/bash cheshire && mkdir -p /workspace && chown 1000:1000 /workspace
ENV HOME=/home/cheshire GNUPGHOME=/home/cheshire/.gnupg PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace
CMD ["sleep", "infinity"]
