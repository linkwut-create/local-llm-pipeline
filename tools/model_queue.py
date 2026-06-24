import json, os, time, uuid
from pathlib import Path

QD = Path('.local_llm_out/queue')
LF = QD / '.lock'
QF = QD / 'pending.jsonl'
RD = QD / 'results'

def _init():
    QD.mkdir(parents=True, exist_ok=True)
    RD.mkdir(parents=True, exist_ok=True)

def _lock():
    _init()
    try: LF.touch(exist_ok=False); return True
    except FileExistsError: return False

def _unlock():
    try: LF.unlink()
    except FileNotFoundError: pass

def enqueue(model, prompt, max_tokens=16384):
    _init()
    rid = uuid.uuid4().hex[:12]
    req = {'id': rid, 'model': model, 'prompt': prompt, 'max_tokens': max_tokens, 'created_at': time.time()}
    with open(QF, 'a', encoding='utf-8') as f:
        f.write(json.dumps(req, ensure_ascii=False) + chr(10))
    rp = RD / f'{rid}.json'
    while not rp.exists():
        time.sleep(1)
    with open(rp, 'r', encoding='utf-8') as f:
        r = json.load(f)
    rp.unlink()
    return r

def _call(req):
    import urllib.request as u
    model, prompt, mt = req['model'], req['prompt'], req.get('max_tokens', 16384)
    base = os.environ.get('LOCAL_LLM_BASE_URL', 'http://127.0.0.1:4000/v1')
    key = os.environ.get('LOCAL_LLM_API_KEY', 'sk-zero12-cluster')
    url = base.rstrip('/') + '/chat/completions'
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': mt, 'temperature': 0, 'stream': False}).encode('utf-8')
    h = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    t0 = time.time()
    try:
        rq = u.Request(url, data=body, headers=h)
        with u.urlopen(rq, timeout=3600) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = ''
        choices = data.get('choices', [])
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get('message', {})
            content = msg.get('content', '') or msg.get('reasoning_content', '') or ''
        return {'ok': True, 'content': content, 'model': model, 'elapsed': time.time() - t0, 'usage': data.get('usage', {})}
    except Exception as e:
        return {'ok': False, 'content': '', 'model': model, 'elapsed': time.time() - t0, 'error': str(e)[:500]}

def process():
    if not _lock(): return
    try:
        _init()
        if not QF.exists(): return
        reqs = []
        with open(QF, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try: reqs.append(json.loads(line))
                    except: pass
        if not reqs: return
        for req in reqs:
            r = _call(req)
            with open(RD / f"{req['id']}.json", 'w', encoding='utf-8') as f:
                json.dump(r, f, ensure_ascii=False)
        QF.unlink()
    finally: _unlock()

def worker():
    print('[queue_worker] started')
    while True:
        try:
            if QF.exists() and QF.stat().st_size > 0:
                process()
        except Exception as e:
            print(f'[queue_worker] {e}')
        time.sleep(0.5)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'worker': worker()
    elif len(sys.argv) > 1 and sys.argv[1] == 'process': process(); print('done')
    else: print('model_queue: py tools/model_queue.py [worker|process]')
