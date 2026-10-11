# signal-cli daemon for Hermes' Signal gateway (k3s). Same build as node1's host install (see ../../README.md
# "signal-cli on ARM64"): Java 25 JRE + signal-cli JVM release + the ARM64 libsignal_jni matching the bundled
# libsignal-client jar (exquo/signal-libs-build). All downloads sha256-checked against GitHub's asset digests.
# sqlite3 + age: the same image runs the nightly encrypted backup CronJob (online .backup of account.db).
FROM docker.io/library/eclipse-temurin:25-jre-noble@sha256:d9a39a23634650173f1e2bbc176227af9728587ecf0f4b62d53e9355cd7a19ab

ARG SIGNAL_CLI_VERSION=0.14.8
ARG SIGNAL_CLI_SHA256=ccd408e831eff7e41ebaaf309704840bb00d78a7869f35ad700dbae5b5a5bb65
ARG LIBSIGNAL_VERSION=0.102.1
ARG LIBSIGNAL_SHA256=c45f2c54143292ef3941226f53419fd8884e88cba95e2a52a356a9321fc90e60

RUN set -eu; apt-get update; apt-get install -y --no-install-recommends curl ca-certificates sqlite3 age; rm -rf /var/lib/apt/lists/*; cd /tmp; \
    curl -fsSLO https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz; \
    echo "${SIGNAL_CLI_SHA256}  signal-cli-${SIGNAL_CLI_VERSION}.tar.gz" | sha256sum -c -; \
    tar xzf signal-cli-${SIGNAL_CLI_VERSION}.tar.gz -C /opt; ln -s /opt/signal-cli-${SIGNAL_CLI_VERSION} /opt/signal-cli; \
    ls /opt/signal-cli/lib | grep -q "^libsignal-client-${LIBSIGNAL_VERSION}.jar$" || { echo "bundled libsignal-client is not ${LIBSIGNAL_VERSION}"; exit 1; }; \
    f=libsignal_jni.so-v${LIBSIGNAL_VERSION}-aarch64-unknown-linux-gnu.tar.gz; \
    curl -fsSLO https://github.com/exquo/signal-libs-build/releases/download/libsignal_v${LIBSIGNAL_VERSION}/$f; \
    echo "${LIBSIGNAL_SHA256}  $f" | sha256sum -c -; \
    mkdir -p /opt/signal-cli/native && tar xzf $f -C /opt/signal-cli/native; rm -f /tmp/*.tar.gz

COPY --chmod=755 signal-cli-backup.sh /usr/local/bin/signal-cli-backup

# uid 1000 "ubuntu" = owner of the migrated data (node1's ~/.local/share/signal-cli); data dir is the PVC.
RUN (getent passwd 1000 | cut -d: -f1 | xargs -r userdel -r 2>/dev/null || true); \
    groupadd -g 1000 ubuntu 2>/dev/null || true; useradd -u 1000 -g 1000 -m -d /home/ubuntu -s /bin/sh ubuntu
ENV JAVA_OPTS="-Xmx256m -Djava.library.path=/opt/signal-cli/native" \
    PATH=/opt/signal-cli/bin:/opt/java/openjdk/bin:/usr/sbin:/usr/bin:/sbin:/bin
USER 1000
WORKDIR /home/ubuntu
# The account comes from SIGNAL_ACCOUNT (Secret) — not baked in.
CMD ["sh", "-c", "exec signal-cli -a \"$SIGNAL_ACCOUNT\" --config /home/ubuntu/.local/share/signal-cli daemon --http 0.0.0.0:8093 --receive-mode on-start"]
