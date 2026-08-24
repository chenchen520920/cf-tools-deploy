// AI 极简网关：/translate + /image，Workers AI 内部绑定，访问 key 鉴权
const MODEL_TRANSLATE = '@cf/zai-org/glm-4.7-flash';
const MODEL_IMAGE = '@cf/black-forest-labs/flux-1-schnell';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, x-api-key',
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status, headers: { 'Content-Type': 'application/json;charset=utf-8', ...CORS },
  });
}

function authed(request, env) {
  if (!env.API_KEY) return true;
  const url = new URL(request.url);
  const k = request.headers.get('x-api-key') || url.searchParams.get('key') || '';
  return k === env.API_KEY;
}

const HOME = `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI 网关</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#222}code{background:#f2f2f2;padding:2px 6px;border-radius:4px}h1{font-size:22px}</style></head>
<body><h1>AI 极简网关</h1>
<p><b>POST /translate</b> — 头 <code>x-api-key</code>，JSON 体 <code>{"text":"要翻译的内容","to":"English"}</code></p>
<p><b>POST /image</b> — 头 <code>x-api-key</code>，JSON 体 <code>{"prompt":"a cute cat"}</code>，直接返回 PNG</p>
<p><b>GET /health</b> — 存活检查（无需 key）</p>
</body></html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
    if (url.pathname === '/' ) return new Response(HOME, { headers: { 'Content-Type': 'text/html;charset=utf-8', ...CORS } });
    if (url.pathname === '/health') return json({ ok: true, ts: Date.now() });
    if (!authed(request, env)) return json({ error: 'unauthorized' }, 401);

    if (url.pathname === '/translate' && request.method === 'POST') {
      try {
        const { text, to = 'English', from } = await request.json();
        if (!text || typeof text !== 'string') return json({ error: 'missing text' }, 400);
        if (text.length > 20000) return json({ error: 'text too long (>20000)' }, 400);
        const sys = `你是专业翻译引擎。把用户输入翻译成${to}${from ? '（源语言：' + from + '）' : '（自动检测源语言）'}。只输出译文，不要解释，不要加注。保持原文格式与换行。`;
        const r = await env.AI.run(MODEL_TRANSLATE, {
          messages: [{ role: 'system', content: sys }, { role: 'user', content: text }],
          max_tokens: 4096,
        });
        return json({ result: (r.response || '').trim(), model: MODEL_TRANSLATE });
      } catch (e) {
        return json({ error: String(e && e.message || e) }, 500);
      }
    }

    if (url.pathname === '/image' && request.method === 'POST') {
      try {
        const { prompt, steps = 4 } = await request.json();
        if (!prompt) return json({ error: 'missing prompt' }, 400);
        const r = await env.AI.run(MODEL_IMAGE, { prompt, steps: Math.min(Math.max(+steps || 4, 1), 8) });
        const bin = Uint8Array.from(atob(r.image), c => c.charCodeAt(0));
        return new Response(bin, { headers: { 'Content-Type': 'image/png', ...CORS } });
      } catch (e) {
        return json({ error: String(e && e.message || e) }, 500);
      }
    }

    return json({ error: 'not found' }, 404);
  },
};
