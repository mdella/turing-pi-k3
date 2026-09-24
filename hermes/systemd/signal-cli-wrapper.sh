#!/bin/sh
# signal-cli 0.14.8 with the ARM64 libsignal_jni (exquo/signal-libs-build v0.102.1) — the bundled jar only has x86_64/macOS.
JAVA_OPTS="${JAVA_OPTS:+$JAVA_OPTS }-Djava.library.path=/opt/signal-cli/native" exec /opt/signal-cli/bin/signal-cli "$@"
