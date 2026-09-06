const form = document.getElementById('form');
if (form) {
  const message = document.getElementById('message');
  const result = document.getElementById('result');
  const rows = document.getElementById('rows');
  const scope = document.getElementById('scope');
  const workspaceLink = document.getElementById('workspace-link');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = 'Checking...';
    result.hidden = true;
    try {
      const response = await fetch('/api/v1/public/crawler-check', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: document.getElementById('url').value})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error === 'public_audit_rate_limited' ? 'This tool has reached its hourly limit. Try again later.' : data.detail?.error || data.error || 'Check failed');
      scope.textContent = `${data.url} · ${data.robots_present ? 'robots.txt found' : 'robots.txt not found'} · ${data.sampling_mode}`;
      rows.innerHTML = data.bots.map((item) => `<div class="row"><span>${item.name}</span><strong>${item.blocked ? 'Blocked' : 'Not blocked'}</strong></div>`).join('');
      workspaceLink.href = `/app#/onboarding?domain=${encodeURIComponent(data.url)}`;
      result.hidden = false;
      message.textContent = 'Check complete.';
    } catch (error) { message.textContent = error.message; }
  });
}
