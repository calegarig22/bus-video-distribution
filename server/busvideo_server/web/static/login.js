document.getElementById('login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target, err = document.getElementById('login-error');
  err.hidden = true;
  const r = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({username: f.username.value, password: f.password.value})});
  if (r.ok) { location.href = '/'; return; }
  const j = await r.json().catch(() => ({}));
  err.textContent = j.detail || 'Falha no login'; err.hidden = false;
});
