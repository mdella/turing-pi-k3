"""
10_host_agent_templates.py

Step 1: extend host 'netbird.cstone.com' (id 10788) with a main agent interface on the droplet's netbird IP,
keep the public-IP interface (the public port checks are bound to it), link 'Linux by Zabbix agent' + 'Docker by Zabbix agent 2',
add group 'Linux servers'. Refuses to run if the host no longer looks as expected.

Idempotent: existing items/triggers/macros are left as they are (macros are updated).
Run from this folder: uv run --no-project --python 3.12 10_host_agent_templates.py
"""
from zbx import api
HID = "10788"
h = api("host.get", {"hostids": [HID], "output": ["host"], "selectInterfaces": "extend", "selectHostGroups": ["groupid"], "selectParentTemplates": ["templateid"]})[0]
if any(i["ip"] == "100.101.19.127" for i in h["interfaces"]):
    raise SystemExit("already configured: netbird agent interface present; nothing to do")
assert h["host"] == "netbird.cstone.com" and len(h["interfaces"]) == 1 and h["interfaces"][0]["interfaceid"] == "82", "host not in the expected original state; stopping"
old = h["interfaces"][0]
api("host.update", {
    "hostid": HID,
    "interfaces": [
        # keep the public-IP interface (the 7 port checks are bound to it) but make it non-main
        {"interfaceid": "82", "type": 1, "main": 0, "useip": 1, "ip": old["ip"], "dns": old["dns"], "port": old["port"]},
        # new main agent interface over netbird; templated agent items bind to the main interface
        {"type": 1, "main": 1, "useip": 1, "ip": "100.101.19.127", "dns": "", "port": "10050"},
    ],
    "groups": [{"groupid": "24"}, {"groupid": "2"}],            # External Services + Linux servers
    "templates": [{"templateid": "10001"}, {"templateid": "10318"}],  # Linux by Zabbix agent, Docker by Zabbix agent 2
})
h = api("host.get", {"hostids": [HID], "output": ["host"], "selectInterfaces": ["interfaceid", "ip", "port", "main"], "selectHostGroups": ["name"], "selectParentTemplates": ["name"]})[0]
print("interfaces:", [(i["interfaceid"], i["ip"], i["port"], "main" if i["main"] == "1" else "secondary") for i in h["interfaces"]])
print("groups:", [g["name"] for g in h["hostgroups"]], "| templates:", [t["name"] for t in h["parentTemplates"]])
print("items now:", api("item.get", {"hostids": [HID], "countOutput": True}), "| LLD rules:", api("discoveryrule.get", {"hostids": [HID], "countOutput": True}))
print("port checks still on public interface 82:", sum(1 for it in api("item.get", {"hostids": [HID], "output": ["interfaceid", "key_"], "search": {"key_": "net.tcp.service"}}) if it["interfaceid"] == "82"), "of 7")
