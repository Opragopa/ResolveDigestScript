// Deploy once under the maintainer's account. Never distribute GITHUB_TOKEN.
const REPO = 'Opragopa/ResolveDigestScript';
const reply = (status, data) => Response.json(data, { status });

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname !== '/report') return reply(404, { error: 'not_found' });
    if (request.method !== 'POST') return reply(405, { error: 'method' });
    if (!env.GITHUB_TOKEN || !env.REPORTS || !env.REPORT_LIMIT) {
      return reply(503, { error: 'not_configured' });
    }
    try {
      const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
      if (!(await env.REPORT_LIMIT.limit({ key: ip })).success ||
          !(await env.REPORT_LIMIT.limit({ key: 'all-reports' })).success) {
        return reply(429, { error: 'rate_limit' });
      }
      // Enforce size while reading, including requests without Content-Length.
      const reader = request.body?.getReader();
      if (!reader) return reply(400, { error: 'body' });
      const chunks = [];
      let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 64000) {
          await reader.cancel();
          return reply(413, { error: 'size' });
        }
        chunks.push(value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      let data;
      try { data = JSON.parse(new TextDecoder().decode(bytes)); }
      catch { return reply(400, { error: 'json' }); }
      if (!data || typeof data.id !== 'string' || !/^[a-f0-9]{64}$/.test(data.id) ||
          typeof data.stage !== 'string' || !data.stage || data.stage.length > 200 ||
          typeof data.details !== 'string' || !data.details || data.details.length > 18000) {
        return reply(400, { error: 'schema' });
      }
      const previous = await env.REPORTS.get(data.id);
      if (previous) return reply(200, { issue_url: previous });
      // Neutralize Markdown fences and GitHub mentions in received logs.
      const clean = text => text.replaceAll('```', '` ` `').replaceAll('@', '＠');
      const response = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json',
          'User-Agent': 'ResolveDigest-Diagnostics' },
        body: JSON.stringify({ title: `[Auto report] ${clean(data.stage).replace(/[\r\n]/g, ' ')}`,
          body: `Автоматический отчёт Resolve Digest\n\nReport ID: ${data.id}\n\n\`\`\`text\n${clean(data.details)}\n\`\`\`` }),
        signal: AbortSignal.timeout(6000),
      });
      if (!response.ok) return reply(502, { error: 'github_unavailable' });
      const issue = await response.json();
      if (!/^https:\/\/github\.com\/Opragopa\/ResolveDigestScript\/issues\/\d+$/.test(issue.html_url)) {
        return reply(502, { error: 'github_response' });
      }
      await env.REPORTS.put(data.id, issue.html_url, { expirationTtl: 604800 });
      return reply(201, { issue_url: issue.html_url });
    } catch {
      return reply(503, { error: 'temporarily_unavailable' });
    }
  },
};
