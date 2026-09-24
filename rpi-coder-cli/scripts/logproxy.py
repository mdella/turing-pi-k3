# Logging pass-through proxy: 127.0.0.1:18080 -> Mac llama-server. One JSON line per request
# (message/tool counts, prompt tokens, tool calls, timing). Usage: PROXY_LOG=~/proxy.jsonl python3 logproxy.py
import http.server, socketserver, urllib.request, json, time, sys, threading, os
UP='http://100.101.193.15:8080'; LOG=os.environ.get('PROXY_LOG','/tmp/proxy.jsonl'); lock=threading.Lock()
class H(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*a): pass
    def _go(self,method):
        body=self.rfile.read(int(self.headers.get('Content-Length',0) or 0)) if method=='POST' else None
        t0=time.time(); rec={'t':round(t0,1),'path':self.path}
        try:
            j=json.loads(body) if body else {}
            if isinstance(j,dict) and 'messages' in j:
                rec.update(msgs=len(j['messages']),tools=len(j.get('tools') or []),stream=j.get('stream'),max_tokens=j.get('max_tokens') or j.get('max_completion_tokens'),
                           tool_names=[t.get('function',{}).get('name') for t in j.get('tools') or []],req=j)
        except Exception: pass
        hdr={k:v for k,v in self.headers.items() if k.lower() not in ('host','content-length','accept-encoding','connection')}
        req=urllib.request.Request(UP+self.path,data=body,headers=hdr,method=method)
        try: r=urllib.request.urlopen(req,timeout=1800); status=r.status
        except urllib.error.HTTPError as e: r=e; status=e.code
        except Exception as e:
            rec['err']=str(e); self.send_response(502); self.send_header('Content-Length','0'); self.end_headers(); self._w(rec); return
        self.send_response(status)
        for k,v in r.headers.items():
            if k.lower() not in ('transfer-encoding','connection','content-length'): self.send_header(k,v)
        self.send_header('Transfer-Encoding','chunked'); self.end_headers()
        buf=b''; first=None
        while True:
            c=r.read1(65536) if hasattr(r,'read1') else r.read(65536)
            if not c: break
            if first is None: first=time.time()
            buf+=c; self.wfile.write(b'%x\r\n'%len(c)+c+b'\r\n'); self.wfile.flush()
        self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
        rec.update(status=status,secs=round(time.time()-t0,2),ttfb=round((first or t0)-t0,2))
        txt=buf.decode('utf-8','replace'); usage=None; calls=[]; content=''; fin=None
        if status>=400: rec['err']=txt[:400]
        for line in txt.splitlines() if 'data:' in txt else []:
            if not line.startswith('data:') or '[DONE]' in line: continue
            try: d=json.loads(line[5:])
            except Exception: continue
            # Anthropic /v1/messages stream (Claude Code): usage arrives in message_start (input side) and
            # message_delta (output side); tool calls are tool_use blocks whose args stream as input_json_delta.
            # Normalised to prompt_tokens so the OpenAI-side summaries work unchanged.
            ty=d.get('type')
            if ty in ('message_start','message_delta'):
                u=(d.get('message') or {}).get('usage') if ty=='message_start' else d.get('usage')
                if u:
                    usage=dict(usage or {}); usage.update(u)
                    usage['prompt_tokens']=sum(usage.get(k) or 0 for k in ('input_tokens','cache_read_input_tokens','cache_creation_input_tokens'))
                if ty=='message_delta': fin=(d.get('delta') or {}).get('stop_reason') or fin
                continue
            if ty=='content_block_start':
                b=d.get('content_block') or {}
                if b.get('type')=='tool_use': calls.append({'name':b.get('name') or '','args':''})
                continue
            if ty=='content_block_delta':
                de=d.get('delta') or {}
                if de.get('type')=='input_json_delta' and calls: calls[-1]['args']+=de.get('partial_json') or ''
                elif de.get('type')=='text_delta': content+=de.get('text') or ''
                continue
            usage=d.get('usage') or usage
            for ch in d.get('choices') or []:
                de=ch.get('delta') or {}; fin=ch.get('finish_reason') or fin
                content+=de.get('content') or ''
                for tc in de.get('tool_calls') or []:
                    i=tc.get('index',0)
                    while len(calls)<=i: calls.append({'name':'','args':''})
                    f=tc.get('function') or {}; calls[i]['name']+=f.get('name') or ''; calls[i]['args']+=f.get('arguments') or ''
        if 'data:' not in txt and status<400:
            try: d=json.loads(txt); usage=d.get('usage'); m=d['choices'][0]['message']; content=m.get('content') or ''; fin=d['choices'][0].get('finish_reason')
            except Exception: pass
        bad=0
        for c in calls:
            try: json.loads(c['args'] or '{}')
            except Exception: bad+=1
        rec.update(usage=usage,finish=fin,calls=[c['name'] for c in calls],bad_args=bad,content=content[:2000])
        self._w(rec)
    def _w(self,rec):
        with lock, open(LOG,'a') as f: f.write(json.dumps(rec)+'\n')
    def do_POST(self): self._go('POST')
    def do_GET(self): self._go('GET')
class S(socketserver.ThreadingMixIn,http.server.HTTPServer): daemon_threads=True
S(('127.0.0.1',18080),H).serve_forever()
