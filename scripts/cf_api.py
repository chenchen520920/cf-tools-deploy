# -*- coding: utf-8 -*-
"""Cloudflare API 助手（GitHub Actions runner 用，网络直连）"""
import json, time, hashlib, secrets
import urllib.request, urllib.error

API = "https://api.cloudflare.com/client/v4"
ACCOUNT_ID = "114a0c52f6adbfb03b772ed5e33d1ccb"

def cf(method, path, token, body=None, ctype="application/json", timeout=60):
    url = API + path
    data = None
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        if ctype == "application/json":
            data = json.dumps(body).encode("utf-8")
        else:
            data = body
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"__error__": "HTTP %s: %s" % (e.code, raw[:500])}
    except Exception as e:
        return {"__error__": str(e)}

def build_multipart(fields, files):
    boundary = "----WB" + secrets.token_hex(8)
    parts = []
    for name, value in fields.items():
        parts.append(("--%s\r\n" % boundary).encode())
        parts.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        parts.append(value.encode() + b"\r\n")
    for name, (filename, content, mime) in files.items():
        parts.append(("--%s\r\n" % boundary).encode())
        parts.append(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (name, filename)).encode())
        parts.append(("Content-Type: %s\r\n\r\n" % mime).encode())
        parts.append(content + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=%s" % boundary

def create_kv(token, title):
    r = cf("POST", "/accounts/%s/storage/kv/namespaces" % ACCOUNT_ID, token, body={"title": title})
    if r.get("success"):
        return r["result"]["id"]
    # 已存在则复用
    r2 = cf("GET", "/accounts/%s/storage/kv/namespaces" % ACCOUNT_ID, token)
    for ns in r2.get("result", []):
        if ns.get("title") == title:
            print("  KV %s 已存在, 复用" % title)
            return ns["id"]
    print("  创建 KV 失败:", json.dumps(r.get("errors"), ensure_ascii=False))
    return None

def create_project(token, base_name):
    import random, string
    name = base_name
    for attempt in range(5):
        if attempt:
            name = "%s-%s" % (base_name, "".join(random.choices(string.ascii_lowercase + string.digits, k=4)))
        r = cf("POST", "/accounts/%s/pages/projects" % ACCOUNT_ID, token,
               body={"name": name, "production_branch": "main"})
        if r.get("success"):
            return name
        errs = r.get("errors", [])
        if any("already" in str(e.get("message", "")).lower() or e.get("code") == 8000012 for e in errs):
            print("  项目名 %s 已存在, 直接复用" % name)
            return name
        print("  创建项目失败:", json.dumps(errs, ensure_ascii=False))
        return None
    return None

def patch_project(token, name, production_cfg):
    body = {"deployment_configs": {"production": production_cfg}}
    r = cf("PATCH", "/accounts/%s/pages/projects/%s" % (ACCOUNT_ID, name), token, body=body)
    if not r.get("success"):
        print("  PATCH 失败:", json.dumps(r.get("errors"), ensure_ascii=False))
        return False
    return True

def get_project(token, name):
    return cf("GET", "/accounts/%s/pages/projects/%s" % (ACCOUNT_ID, name), token)

def deploy_worker(token, name, worker_path):
    with open(worker_path, "rb") as f:
        content = f.read()
    h = hashlib.sha256(content).hexdigest()
    body, ctype = build_multipart({"manifest": json.dumps({"_worker.js": h})},
                                  {"_worker.js": ("_worker.js", content, "application/javascript")})
    r = cf("POST", "/accounts/%s/pages/projects/%s/deployments" % (ACCOUNT_ID, name),
           token, body=body, ctype=ctype)
    if not r.get("success"):
        print("  部署请求失败:", json.dumps(r.get("errors"), ensure_ascii=False))
        return None
    return r["result"].get("id")

def poll(token, name, dep_id, rounds=30):
    for i in range(rounds):
        time.sleep(4)
        r = cf("GET", "/accounts/%s/pages/projects/%s/deployments/%s" % (ACCOUNT_ID, name, dep_id), token)
        if "__error__" in r:
            continue
        stages = r.get("result", {}).get("stages", [])
        latest = stages[-1] if stages else {}
        status = latest.get("status")
        if status == "success":
            return True
        if status == "failed":
            print("  部署失败, stage =", latest.get("name"))
            return False
    print("  部署状态确认超时（可能仍在进行）")
    return False

def subdomain(token, name):
    r = get_project(token, name)
    if r.get("success"):
        return r["result"].get("subdomain")
    return None
