// 阅后即焚：浏览器端 AES-GCM 加密，密钥只存在于链接 #  fragment，读取一次即删除
const TTL = 7 * 24 * 3600; // 7 天未读自动过期

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json;charset=utf-8' },
  });
}

const STYLE = `body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#222;background:#fafafa}
h1{font-size:22px}textarea{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:14px}
button{background:#111;color:#fff;border:0;border-radius:8px;padding:10px 22px;font-size:15px;cursor:pointer}
button:disabled{background:#999}input[type=password]{padding:8px;border:1px solid #ccc;border-radius:8px}
.card{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:20px;margin-top:16px}
.row{margin:12px 0}.muted{color:#888;font-size:13px}.linkbox{word-break:break-all;background:#f2f2f2;padding:10px;border-radius:8px;font-size:13px}
#out{white-space:pre-wrap;word-break:break-all}.err{color:#c00}`;

const UPLOAD_PAGE = `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>阅后即焚</title><style>${STYLE}</style></head>
<body><h1>阅后即焚</h1>
<p class="muted">内容在你的浏览器里加密后才上传，密钥只存在于链接中（# 后面的部分不发给服务器）。对方打开一次，内容即销毁；7 天未读自动过期。</p>
<div class="card">
  <div class="row"><textarea id="txt" rows="6" placeholder="粘贴要分享的文本（密码 / token / 备注……）"></textarea></div>
  <div class="row"><input type="file" id="file"> <span class="muted">或选文件（≤10MB）</span></div>
  <div class="row"><input type="password" id="key" placeholder="访问口令（可选，加了更稳）"></div>
  <div class="row"><button id="go">加密并生成链接</button></div>
  <div class="row" id="result"></div>
</div>
<script>
const $ = id => document.getElementById(id);
const b64 = buf => btoa(String.fromCharCode(...new Uint8Array(buf)));
$('go').onclick = async () => {
  try {
    $('go').disabled = true;
    let payload, fname = null;
    const f = $('file').files[0];
    if (f) {
      if (f.size > 10 * 1024 * 1024) throw new Error('文件超过 10MB');
      payload = await f.arrayBuffer(); fname = f.name;
    } else {
      const t = $('txt').value.trim();
      if (!t) throw new Error('请输入文本或选择文件');
      payload = new TextEncoder().encode(t);
    }
    const k = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, k, payload);
    const rawKey = await crypto.subtle.exportKey('raw', k);
    const secret = b64(rawKey) + '.' + b64(iv);
    const headers = { 'Content-Type': 'application/json' };
    const pw = $('key').value.trim();
    if (pw) headers['x-burn-key'] = pw;
    const r = await fetch('/api/put', { method: 'POST', headers,
      body: JSON.stringify({ data: b64(ct), name: fname }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.status);
    const link = location.origin + '/s/' + j.id + '#' + secret;
    $('result').innerHTML = '<p>链接（打开一次即毁）：</p><div class="linkbox">' + link + '</div>' +
      '<p class="muted"><button onclick="navigator.clipboard.writeText(\\'' + link + '\\')">复制链接</button></p>';
  } catch (e) {
    $('result').innerHTML = '<p class="err">' + e.message + '</p>';
  } finally { $('go').disabled = false; }
};
</script></body></html>`;

const VIEW_PAGE = `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>阅后即焚 · 查看</title><style>${STYLE}</style></head>
<body><h1>阅后即焚</h1><div class="card" id="out">读取中（读取的同时内容已从服务器删除）……</div>
<script>
const $ = id => document.getElementById(id);
const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
(async () => {
  try {
    const id = location.pathname.split('/').pop();
    const secret = location.hash.slice(1);
    if (!secret) throw new Error('链接缺少解密密钥（# 之后的部分）');
    const [kb, ivb] = secret.split('.');
    const headers = { 'Content-Type': 'application/json' };
    const pw = sessionStorage.getItem('burn-key');
    if (pw) headers['x-burn-key'] = pw;
    const r = await fetch('/api/get', { method: 'POST', headers, body: JSON.stringify({ id }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || '内容不存在或已被销毁');
    const k = await crypto.subtle.importKey('raw', unb64(kb), { name: 'AES-GCM' }, false, ['decrypt']);
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(ivb) }, k, unb64(j.data));
    if (j.name) {
      const blob = new Blob([pt]);
      $('out').innerHTML = '<p>文件：<b>' + j.name + '</b>（已解密，服务器副本已销毁）</p>' +
        '<p><a download="' + j.name + '" href="' + URL.createObjectURL(blob) + '"><button>下载文件</button></a></p>';
    } else {
      $('out').innerHTML = '<div id="out">' + new TextDecoder().decode(pt).replace(/[<>&]/g,
        c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c])) + '</div><p class="muted">以上内容已从服务器销毁，刷新将无法再看。</p>';
    }
  } catch (e) {
    $('out').innerHTML = '<p class="err">' + e.message + '</p>';
  }
})();
</script></body></html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/') return new Response(UPLOAD_PAGE, { headers: { 'Content-Type': 'text/html;charset=utf-8' } });
    if (url.pathname.startsWith('/s/')) return new Response(VIEW_PAGE, { headers: { 'Content-Type': 'text/html;charset=utf-8' } });

    if (url.pathname === '/api/put' && request.method === 'POST') {
      try {
        if (env.BURN_KEY) {
          const k = request.headers.get('x-burn-key') || '';
          if (k !== env.BURN_KEY) return json({ error: '口令不对' }, 401);
        }
        const { data, name = null } = await request.json();
        if (!data || typeof data !== 'string') return json({ error: 'missing data' }, 400);
        if (data.length > 14 * 1024 * 1024) return json({ error: 'too large' }, 400);
        const id = crypto.randomUUID().replace(/-/g, '').slice(0, 16);
        await env.KV.put(id, JSON.stringify({ data, name }), { expirationTtl: TTL });
        return json({ id });
      } catch (e) {
        return json({ error: String(e && e.message || e) }, 500);
      }
    }

    if (url.pathname === '/api/get' && request.method === 'POST') {
      try {
        const { id } = await request.json();
        if (!id || !/^[a-f0-9]{16}$/.test(id)) return json({ error: 'bad id' }, 400);
        const v = await env.KV.get(id);
        if (!v) return json({ error: '内容不存在或已被销毁' }, 404);
        await env.KV.delete(id); // 读取即焚
        return new Response(v, { headers: { 'Content-Type': 'application/json;charset=utf-8' } });
      } catch (e) {
        return json({ error: String(e && e.message || e) }, 500);
      }
    }

    return json({ error: 'not found' }, 404);
  },
};
