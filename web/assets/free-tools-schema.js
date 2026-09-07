const form = document.getElementById('form');
if (form) {
  const message = document.getElementById('message'), result = document.getElementById('result'), summary = document.getElementById('summary'), rows = document.getElementById('rows'), download = document.getElementById('download');
  let report = '';
  const addRow = (label, value) => {
    const row = document.createElement('div');
    const text = document.createElement('span');
    const status = document.createElement('strong');
    row.className = 'row';
    text.textContent = label;
    status.textContent = value;
    row.append(text, status);
    rows.append(row);
  };
  form.addEventListener('submit', async (event) => { event.preventDefault(); message.textContent = 'Checking...'; result.hidden = true; try { const response = await fetch('/api/v1/public/schema-tool', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: document.getElementById('url').value})}); const data = await response.json(); if (!response.ok) throw new Error(data.error === 'public_audit_rate_limited' ? 'This tool has reached its hourly limit. Try again later.' : data.detail?.error || data.error || 'Check failed'); summary.textContent = `${data.url} · ${data.jsonld_count} JSON-LD block(s) · ${data.sampling_mode}`; rows.replaceChildren(); (data.checks || []).forEach((item) => addRow(item.message || '', item.ok ? 'Pass' : 'Review')); if (data.types?.length) addRow('Observed types', data.types.join(', ')); report = JSON.stringify(data, null, 2); result.hidden = false; message.textContent = 'Diagnosis ready.'; } catch (error) { message.textContent = error.message; } });
  download.addEventListener('click', () => { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([report], {type: 'application/json;charset=utf-8'})); link.download = 'schema-diagnosis.json'; link.click(); URL.revokeObjectURL(link.href); });
}
