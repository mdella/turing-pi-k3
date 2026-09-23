# Samples the coder's /slots every 2 s: busy slots and per-slot decode rate (tokens/s).
# Usage: python3 slot-poll.py out.jsonl   (Ctrl-C to stop)
import json,time,urllib.request,sys
out=open(sys.argv[1],'w'); prev={}
while True:
    try:
        s=json.load(urllib.request.urlopen('http://100.101.193.15:8080/slots',timeout=5)); t=time.time()
        busy=[x['id'] for x in s if x['is_processing']]
        rates={}
        for x in s:
            nd=(x.get('next_token') or [{}])[0].get('n_decoded',0) if isinstance(x.get('next_token'),list) else (x.get('next_token') or {}).get('n_decoded',0)
            if x['id'] in prev and x['is_processing'] and nd>prev[x['id']][1]:
                rates[x['id']]=round((nd-prev[x['id']][1])/(t-prev[x['id']][0]),1)
            prev[x['id']]=(t,nd)
        out.write(json.dumps({'t':round(t,1),'busy':busy,'rates':rates})+'\n'); out.flush()
    except Exception as e:
        out.write(json.dumps({'err':str(e)})+'\n'); out.flush()
    time.sleep(2)
