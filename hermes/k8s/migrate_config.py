#!/usr/bin/env python3
"""Rewrite a copy of node1's ~/.hermes for the k3s pod (run at cutover against the state volume; idempotent).

    migrate_config.py <HERMES_HOME> [--dry-run]

Text edits only (comments and layout stay), each one asserted so a config drift fails loudly instead of half-applying:
  - honcho.json (all):        baseUrl 127.0.0.1:8800 (node1 socat relay) -> honcho-api.honcho.svc:8000
  - .env (default profile):   SIGNAL_HTTP_URL -> signal-cli Service; API_SERVER_HOST -> 0.0.0.0 (pod; NetworkPolicy gates it)
  - config.yaml (default):    Mac Studio provider base_url (netbird IP) -> mac-studio relay Service
  - profiles/{cheshire,luna}: terminal backend docker -> ssh (their sandbox pod); MCP python + scripts -> image paths;
                              render_docs -> render service (RENDER_URL); luna-publish ClusterIP -> Service DNS
"""
import difflib, json, re, sys
from pathlib import Path

HONCHO = "http://honcho-api.honcho.svc.cluster.local:8000"
SIGNAL = "http://signal-cli.hermes.svc.cluster.local:8093"
MAC = "http://mac-studio.hermes.svc.cluster.local:11434/v1"
RENDER = "http://hermes-render.hermes.svc.cluster.local:8080"
LUNA_PUBLISH = "http://luna-publish.luna.svc.cluster.local:8000/mcp"
VENV_OLD, VENV_NEW = "/home/ubuntu/.hermes/hermes-agent/venv/bin/python", "/opt/hermes/.venv/bin/python"
MCP_OLD, MCP_NEW = "/home/ubuntu/.hermes/local-mcp/", "/opt/geekstyle/local-mcp/"

changes = []


def edit(path: Path, fn, dry):
    old = path.read_text()
    new = fn(old)
    if new != old:
        changes.append(path)
        sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), str(path), str(path), n=0))
        if not dry:
            path.write_text(new)


def sub1(pattern, repl, text, what, flags=0, count_ok=(1,)):
    """re.subn that insists on the expected number of matches (or 0 = already migrated)."""
    new, n = re.subn(pattern, repl, text, flags=flags)
    if n not in count_ok and n != 0:
        sys.exit(f"{what}: expected {count_ok} match(es), got {n}")
    return new


def honcho(text):
    d = json.loads(text)
    if d.get("baseUrl", "").startswith("http://127.0.0.1:8800"):
        d["baseUrl"] = HONCHO
    return json.dumps(d, indent=2) + "\n" if d.get("baseUrl") == HONCHO else text


def default_env(text):
    text = sub1(r"^SIGNAL_HTTP_URL=.*$", f"SIGNAL_HTTP_URL={SIGNAL}", text, "SIGNAL_HTTP_URL", re.M)
    text = sub1(r"^API_SERVER_HOST=.*$", "API_SERVER_HOST=0.0.0.0", text, "API_SERVER_HOST", re.M)
    return text


def default_config(text):
    return sub1(r"base_url: http://100\.101\.193\.15:11434/v1", f"base_url: {MAC}", text, "mac-studio base_url")


def profile_config(profile):
    def fn(text):
        # terminal: docker -> ssh. The docker_* keys stay (ignored by the ssh backend) so rollback is a backend flip.
        text = sub1(r'^  backend: "docker".*$',
                    f'  backend: "ssh"   # k3s: tools run in pod sbx-{profile} (was docker on node1)\n'
                    f'  ssh_host: "sbx-{profile}.hermes.svc.cluster.local"\n'
                    f'  ssh_user: "sandbox"\n'
                    f'  ssh_port: 22\n'
                    f'  ssh_key: "/etc/hermes-ssh/{profile}_key"', text, "terminal backend", re.M)
        text = text.replace(VENV_OLD, VENV_NEW).replace(MCP_OLD, MCP_NEW)
        # render_docs: service instead of docker; vendor dir now in the image
        text = sub1(r'^(\s+)RENDER_IMAGE: .*$', rf'\1RENDER_URL: "{RENDER}"', text, "RENDER_IMAGE", re.M)
        text = text.replace("/opt/geekstyle/local-mcp/render/vendor", "/opt/geekstyle/local-mcp/render/vendor")
        if profile == "luna":
            text = sub1(r"url: http://10\.43\.128\.53:8000/mcp", f"url: {LUNA_PUBLISH}", text, "luna-publish url")
        return text
    return fn


def main():
    home, dry = Path(sys.argv[1]), "--dry-run" in sys.argv
    for p in [home / "honcho.json", *sorted(home.glob("profiles/*/honcho.json"))]:
        edit(p, honcho, dry)
    edit(home / ".env", default_env, dry)
    edit(home / "config.yaml", default_config, dry)
    for prof in ("cheshire", "luna"):
        edit(home / "profiles" / prof / "config.yaml", profile_config(prof), dry)
    print(f"\n{'would change' if dry else 'changed'}: {len(changes)} file(s)")


if __name__ == "__main__":
    main()
