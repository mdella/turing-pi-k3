#!/bin/sh
# Distrust CA roots in the image's system bundle and FAIL the build if any is still present (2026-10-30).
# Why: CVE-2026-111943 — eMudhra intermediates whose private keys were compromised chain to "emSign ECC Root CA - G3".
# GitLab removed them from its own stores; Debian's fix (ca-certificates 20260816+nmu1) blacklists that root. Our
# images' distros don't all have a fixed package yet (Debian stable none; the alpine-chrome base is Alpine 3.19, EOL),
# so remove it here, the same way, on every build. Chromium uses Chrome's own root store; this covers everything else
# (curl, Python, Java's cacerts is separate and not touched).
# Usage: ca-distrust.sh "Common Name 1" ["Common Name 2" ...]   (default: emSign ECC Root CA - G3)
set -eu
[ $# -gt 0 ] || set -- "emSign ECC Root CA - G3"
B=/etc/ssl/certs/ca-certificates.crt
need_openssl=0; command -v openssl >/dev/null 2>&1 || need_openssl=1
if [ "$need_openssl" = 1 ] && command -v apk >/dev/null 2>&1; then apk add --no-cache --virtual .ca-distrust openssl >/dev/null; fi

subjects() { awk 'BEGIN{c=""} /BEGIN CERT/{c=""} {c=c $0 "\n"} /END CERT/{printf "%s", c | "openssl x509 -noout -subject -nameopt utf8,sep_comma_plus 2>/dev/null"; close("openssl x509 -noout -subject -nameopt utf8,sep_comma_plus 2>/dev/null")}' "$B"; }

if command -v update-ca-certificates >/dev/null 2>&1 && [ -d /usr/share/ca-certificates/mozilla ] && [ -f /etc/ca-certificates.conf ]; then
  # Debian/Ubuntu: exclude by file name in ca-certificates.conf, then regenerate (what Debian's blacklist does).
  for cn in "$@"; do
    f="mozilla/$(printf '%s' "$cn" | tr ' ' '_').crt"
    if grep -qx "$f" /etc/ca-certificates.conf; then sed -i "s|^$f\$|!$f|" /etc/ca-certificates.conf; echo "ca-distrust: excluded $f"; fi
  done
  update-ca-certificates --fresh >/dev/null
else
  # Alpine bundle-only: rewrite the bundle without the matching certificates.
  # Fixed work dir (no rm on a computed path).
  rm -rf /tmp/ca-distrust; mkdir -p /tmp/ca-distrust/certs
  tmp=/tmp/ca-distrust/bundle.pem; d=/tmp/ca-distrust/certs; : > "$tmp"
  # Copy ONLY the lines from BEGIN to END of each certificate: text between certificates must not reopen (and
  # truncate) a finished file.
  awk -v d="$d" '/BEGIN CERT/{n++; f=sprintf("%s/%05d.pem", d, n); in_c=1} in_c{print >> f} /END CERT/{in_c=0; close(f)}' "$B"
  before=$(grep -c "BEGIN CERTIFICATE" "$B"); removed=0; unparsed=0
  for f in "$d"/*.pem; do
    s=$(openssl x509 -noout -subject -nameopt utf8,sep_comma_plus -in "$f" 2>/dev/null || true); drop=0
    [ -n "$s" ] || unparsed=$((unparsed + 1))
    for cn in "$@"; do case "$s" in *"CN=$cn"*) drop=1;; esac; done
    if [ "$drop" = 1 ]; then echo "ca-distrust: removed $s"; removed=$((removed + 1)); else cat "$f" >> "$tmp"; fi
  done
  after=$(grep -c "BEGIN CERTIFICATE" "$tmp" || true)
  # Never write a bundle we can't account for: every certificate must parse, and exactly the removed ones may be gone.
  if [ "$unparsed" -ne 0 ] || [ "$after" -ne $((before - removed)) ] || [ "$after" -lt 50 ]; then
    echo "ca-distrust: REFUSING to rewrite bundle (before=$before removed=$removed after=$after unparsed=$unparsed)"; exit 1
  fi
  cat "$tmp" > "$B"; rm -rf /tmp/ca-distrust
fi

left=$(subjects | while IFS= read -r s; do for cn in "$@"; do case "$s" in *"CN=$cn"*) echo "$s";; esac; done; done)
total=$(grep -c "BEGIN CERTIFICATE" "$B")
[ "$need_openssl" = 1 ] && command -v apk >/dev/null 2>&1 && apk del .ca-distrust >/dev/null || true
if [ -n "$left" ]; then echo "ca-distrust: STILL TRUSTED: $left"; exit 1; fi
echo "ca-distrust: ok, $total certificates, none of: $*"
