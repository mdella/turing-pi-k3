# Minimal Zabbix API client. Token read from ~/.config/zabbix/api-token (never printed).
import json, os, ssl, sys, urllib.request
URL = "https://127.0.0.1:8500/api_jsonrpc.php"
TOKEN = open(os.path.expanduser("~/.config/zabbix/api-token")).read().strip()
CTX = ssl._create_unverified_context()   # local self-signed cert on 127.0.0.1
def api(method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json-rpc", "Authorization": f"Bearer {TOKEN}"})
    r = json.load(urllib.request.urlopen(req, context=CTX, timeout=30))
    if "error" in r: raise SystemExit(f"API error in {method}: {r['error']}")
    return r["result"]
if __name__ == "__main__":
    u = api("user.get", {"output": ["username"], "selectRole": ["name", "type"], "filter": {}, "limit": 1, "getAccess": True})
    print("hosts visible:", api("host.get", {"countOutput": True}))
    print("existing netbird host:", api("host.get", {"output": ["hostid", "host"], "filter": {"host": ["netbird.cstone.com"]}}))
    print("hostgroups:", [(g["groupid"], g["name"]) for g in api("hostgroup.get", {"output": ["groupid", "name"]})])
    for t in ["Linux by Zabbix agent", "Linux by Zabbix agent active", "Docker by Zabbix agent 2"]:
        print("template:", t, "->", [x["templateid"] for x in api("template.get", {"output": ["templateid"], "filter": {"host": [t]}})])
    print("existing hosts:", [(h["host"], [g["name"] for g in h["hostgroups"]], [i["ip"] or i["dns"] for i in h["interfaces"]]) for h in api("host.get", {"output": ["host"], "selectHostGroups": ["name"], "selectInterfaces": ["ip", "dns"]})])
