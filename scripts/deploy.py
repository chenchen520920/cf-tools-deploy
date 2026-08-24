# -*- coding: utf-8 -*-
"""
部署入口（GitHub Actions 运行）
用法: python scripts/deploy.py [all|gateway|burn|node2]
凭证: 环境变量 CF_API
口令派生: API_KEY / BURN_KEY / ADMIN 均由 sha256(purpose:CF_API) 派生，
          不生成随机口令, 日志中不出现任何凭证。
"""
import sys, os, json, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_api import (ACCOUNT_ID, cf, create_kv, create_project, patch_project,
                    get_project, deploy_worker, poll, subdomain)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def derive(purpose, token, n):
    return hashlib.sha256((purpose + ":" + token).encode()).hexdigest()[:n]

def wrangler_pages_deploy(token, comp_dir, project_name):
    """用 wrangler CLI 部署 Pages（wrangler.toml 里的 [ai] 绑定才会生效）"""
    env = dict(os.environ)
    env["CLOUDFLARE_API_TOKEN"] = token
    env["CLOUDFLARE_ACCOUNT_ID"] = ACCOUNT_ID
    r = subprocess.run(
        ["npx", "--yes", "wrangler@latest", "pages", "deploy", ".",
         "--project-name", project_name, "--branch", "main"],
        env=env, capture_output=True, text=True, timeout=600, cwd=comp_dir)
    out = (r.stdout or "") + (r.stderr or "")
    for ln in out.splitlines():
        if any(s in ln for s in ("✨", "Success", "pages.dev", "Error", "error", "✘", "ERROR")):
            print("  wrangler:", ln.strip()[:160])
    return r.returncode == 0

def verify_gateway(sub, key):
    """部署后从 runner 侧做端到端验证（runner 在美国，直连 pages.dev 无阻碍）"""
    import urllib.request, urllib.error, time
    base = "https://" + sub
    def post(path, body=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(body).encode()
        r = urllib.request.Request(base + path, data=data, method="POST",
            headers={"Content-Type": ctype, "x-api-key": key,
                     "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) curl/8.0"})
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, resp.read()
    for attempt in range(5):
        try:
            time.sleep(8)
            # 1. 翻译
            st, b = post("/translate", {"text": "不锈钢扳手，适用于摩托车维修", "to": "English"})
            print("  [verify] /translate:", st, b.decode()[:160].replace("\n", " "))
            # 2. TTS（melotts 当前可能 3043 故障，带/不带 lang 各试一次）
            audio = None
            for payload in ({"text": "This is a gateway self test.", "lang": "en"},
                            {"text": "This is a gateway self test."}):
                try:
                    st, audio = post("/tts", payload)
                    print("  [verify] /tts:", st, len(audio), "bytes (payload=%s)" % list(payload.keys()))
                    break
                except urllib.error.HTTPError as he:
                    print("  [verify] /tts HTTP", he.code, "body:", he.read().decode()[:150].replace("\n", " "))
            # 3. Whisper 独立测（合成 1 秒正弦波 WAV，验证管线通畅即可）
            import math, struct
            sr = 16000
            samples = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / sr))) for i in range(sr))
            wav = (b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt " +
                   struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) + b"data" +
                   struct.pack("<I", len(samples)) + samples)
            try:
                st, b = post("/whisper", raw=wav, ctype="audio/wav")
                print("  [verify] /whisper:", st, b.decode()[:200].replace("\n", " "))
            except urllib.error.HTTPError as he:
                print("  [verify] /whisper HTTP", he.code, "body:", he.read().decode()[:200].replace("\n", " "))
            # 4. 生图
            try:
                st, img = post("/image", {"prompt": "a blue ceramic mug, product photo"})
                print("  [verify] /image:", st, len(img), "bytes")
            except urllib.error.HTTPError as he:
                print("  [verify] /image HTTP", he.code, "body:", he.read().decode()[:200].replace("\n", " "))
            return
        except Exception as e:
            print("  [verify] 第%d轮失败: %s" % (attempt + 1, str(e)[:120]))

def run_component(token, comp):
    print("=" * 50)
    print("组件:", comp)
    if comp == "gateway":
        name = create_project(token, "ai-gw")
        if not name: return False
        # env 变量用 REST 设（secret_text 不明文回显）；AI 绑定由 wrangler.toml 负责
        cfg = {
            "env_vars": {"API_KEY": {"type": "secret_text",
                                     "value": derive("ai-gw-k2", token, 24)}},
            "compatibility_date": "2025-08-01",
        }
        if not patch_project(token, name, cfg): return False
        if not wrangler_pages_deploy(token, os.path.join(ROOT, "gateway"), name):
            print("  wrangler 部署失败")
            return False
        sub = subdomain(token, name) or (name + ".pages.dev")
        print("组件 gateway 部署成功 -> https://%s" % sub)
        verify_gateway(sub, derive("ai-gw-k2", token, 24))
        return True
    elif comp == "burn":
        ns_kv = create_kv(token, "burn-kv")
        if not ns_kv: return False
        name = create_project(token, "burn")
        if not name: return False
        cfg = {
            "env_vars": {"BURN_KEY": {"value": derive("burn", token, 24)}},
            "kv_namespaces": {"KV": {"namespace_id": ns_kv}},
            "compatibility_date": "2025-08-01",
        }
        if not patch_project(token, name, cfg): return False
    elif comp == "node2":
        ns_kv = create_kv(token, "edgetunnel2-kv")
        if not ns_kv: return False
        name = create_project(token, "edgetunnel2")
        if not name: return False
        cfg = {
            "env_vars": {"ADMIN": {"value": derive("edgetunnel2", token, 16)}},
            "kv_namespaces": {"KV": {"namespace_id": ns_kv}},
            "compatibility_date": "2025-08-01",
        }
        if not patch_project(token, name, cfg): return False
    else:
        print("未知组件:", comp)
        return False

    dep = deploy_worker(token, name, os.path.join(ROOT, comp, "_worker.js"))
    if not dep: return False
    ok = poll(token, name, dep)
    sub = subdomain(token, name) or (name + ".pages.dev")
    print("组件 %s 部署%s -> https://%s" % (comp, "成功" if ok else "待确认", sub))
    return True

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    token = os.environ.get("CF_API", "")
    assert token, "缺少环境变量 CF_API"
    r = cf("GET", "/user/tokens/verify", token)
    assert r.get("success"), "CF_API 无效: %s" % r
    print("token OK, account =", ACCOUNT_ID)
    comps = ["gateway", "burn", "node2"] if target == "all" else [target]
    failed = []
    for c in comps:
        if not run_component(token, c):
            failed.append(c)
    if failed:
        print("失败组件:", failed)
        sys.exit(1)
    print("全部完成")
