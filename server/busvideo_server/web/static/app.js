(() => {
  const $ = (id) => document.getElementById(id);
  const fmtBytes = (n) => n == null ? '—' : n >= 1e9 ? (n / 1e9).toFixed(2) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(0) + ' MB' : (n / 1e3).toFixed(0) + ' KB';
  const fmtDur = (s) => { if (s == null) return '—'; s = Math.round(s); const m = Math.floor(s / 60), r = s % 60; return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`; };
  const fmtDate = (iso) => { if (!iso) return '—'; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString('pt-BR'); };
  const ago = (sec) => sec == null ? '—' : sec < 60 ? 'agora' : sec < 3600 ? `${Math.floor(sec / 60)} min atrás` : sec < 86400 ? `${Math.floor(sec / 3600)} h atrás` : `${Math.floor(sec / 86400)} d atrás`;
  const STATUS = { updated: ['Atualizado', 'badge-updated'], pending: ['Pendente', 'badge-pending'], downloading: ['Baixando', 'badge-downloading'], offline: ['Offline', 'badge-offline'], error: ['Erro', 'badge-error'] };

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (r.status === 401) { location.href = '/login'; throw new Error('sessão expirada'); }
    return r;
  }

  async function loadCurrent() {
    const r = await api('/api/video/latest');
    if (r.status === 204) { $('current-empty').hidden = false; $('current-info').hidden = true; $('preview-details').hidden = true; return null; }
    const v = await r.json();
    $('current-empty').hidden = true; $('current-info').hidden = false;
    $('cur-name').textContent = v.filename; $('cur-version').textContent = v.version;
    $('cur-date').textContent = fmtDate(v.published_at); $('cur-duration').textContent = fmtDur(v.duration);
    $('cur-res').textContent = v.width && v.height ? `${v.width}x${v.height}` : '—'; $('cur-size').textContent = fmtBytes(v.size);
    const prev = $('preview'); const src = v.download_url + '?v=' + v.version;
    if (prev.getAttribute('data-src') !== src) { prev.setAttribute('data-src', src); prev.src = src; }
    $('preview-details').hidden = false;
    return v;
  }

  const DEVICES_PREVIEW = 10;           // quantos ônibus aparecem antes de "Ver todos"
  let showAllDevices = false, lastDevices = [];
  $('devices-toggle').onclick = () => { showAllDevices = !showAllDevices; renderDevices(lastDevices); };

  async function loadDevices() {
    const r = await api('/api/devices'); const list = await r.json();
    lastDevices = list; renderDevices(list);
  }

  function renderDevices(list) {
    const counts = {}; for (const d of list) counts[d.status] = (counts[d.status] || 0) + 1;
    const summary = ['updated', 'pending', 'downloading', 'error', 'offline'].filter(k => counts[k])
      .map(k => `${counts[k]} ${(STATUS[k] || [k])[0].toLowerCase()}`).join(' · ');
    $('devices-count').textContent = list.length ? `(${list.length}) ${summary}` : '';
    $('devices-empty').hidden = list.length > 0; $('devices-table').hidden = list.length === 0;
    const shown = showAllDevices ? list : list.slice(0, DEVICES_PREVIEW);
    const more = $('devices-more'); more.hidden = list.length <= DEVICES_PREVIEW;
    if (!more.hidden) {
      $('devices-more-text').textContent = showAllDevices ? `Mostrando todos os ${list.length} ônibus` : `Mostrando ${shown.length} de ${list.length} ônibus`;
      $('devices-toggle').textContent = showAllDevices ? `MOSTRAR SÓ OS PRIMEIROS ${DEVICES_PREVIEW}` : `VER TODOS (${list.length})`;
    }
    const tb = $('devices-table').querySelector('tbody'); tb.innerHTML = '';
    for (const d of shown) {
      const [label, cls] = STATUS[d.status] || [d.status, 'badge-offline'];
      // Tudo que vem do dispositivo entra como texto (textContent), nunca como HTML.
      const tr = document.createElement('tr');
      const note = d.last_error ? `⚠ ${d.last_error}` : (d.free_space_mb != null ? `${(d.free_space_mb / 1024).toFixed(1)} GB livres` : '');
      const cell = (content, cls2) => { const td = document.createElement('td'); if (cls2) td.className = cls2; td.append(content); return td; };
      const strong = document.createElement('strong'); strong.textContent = d.device_id;
      const badge = document.createElement('span'); badge.className = `badge ${cls}`;
      badge.textContent = (d.status === 'downloading' && d.progress != null) ? `${label} ${d.progress}%` : label;
      const seen = cell(ago(d.seconds_since_seen)); seen.title = fmtDate(d.last_seen);
      const rm = document.createElement('button'); rm.type = 'button'; rm.className = 'btn-remove'; rm.title = 'Remover da lista';
      rm.textContent = '×';
      rm.onclick = async () => {
        if (!confirm(`Remover ${d.device_id} da lista? Se o ônibus ainda existir, ele volta sozinho no próximo contato.`)) return;
        const r = await api(`/api/devices/${encodeURIComponent(d.device_id)}`, { method: 'DELETE' });
        if (r.ok) loadDevices();
      };
      tr.append(cell(strong), cell(String(d.current_version ?? '—')), cell(badge), seen, cell(note, 'small muted'), cell(rm));
      tb.appendChild(tr);
    }
  }

  let selectedFile = null, uploadedVideo = null;
  $('select-btn').onclick = () => $('file-input').click();
  $('file-input').onchange = (e) => {
    selectedFile = e.target.files[0] || null; uploadedVideo = null;
    $('validation').hidden = true; $('upload-error').hidden = true; $('publish-ok').hidden = true;
    $('selected-file').hidden = !selectedFile;
    if (selectedFile) $('selected-file').textContent = `Selecionado: ${selectedFile.name} (${fmtBytes(selectedFile.size)})`;
    $('upload-btn').disabled = !selectedFile;
  };

  $('upload-btn').onclick = () => {
    if (!selectedFile) return;
    $('upload-btn').disabled = true; $('select-btn').disabled = true;
    $('progress-wrap').hidden = false; $('upload-error').hidden = true; $('validation').hidden = true;
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/video/upload');
    xhr.setRequestHeader('X-Filename', selectedFile.name);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      const p = Math.round(ev.loaded / ev.total * 100);
      $('progress-bar').style.width = p + '%';
      $('progress-text').textContent = p < 100 ? `Enviando… ${p}%` : 'Validando o vídeo…';
    };
    xhr.onload = () => {
      $('select-btn').disabled = false; $('progress-wrap').hidden = true; $('progress-bar').style.width = '0';
      let j = {}; try { j = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 401) { location.href = '/login'; return; }
      if (xhr.status >= 400 && j.id == null) { $('upload-error').textContent = '✗ ' + (j.detail || `Erro ${xhr.status}`); $('upload-error').hidden = false; return; }
      showValidation(j);
    };
    xhr.onerror = () => { $('select-btn').disabled = false; $('progress-wrap').hidden = true; $('upload-error').textContent = '✗ Falha de rede durante o envio'; $('upload-error').hidden = false; };
    xhr.send(selectedFile);
  };

  function showValidation(v) {
    uploadedVideo = v;
    $('val-name').textContent = v.filename; $('val-duration').textContent = fmtDur(v.duration);
    $('val-res').textContent = `${v.width}x${v.height}`;
    $('val-codec').textContent = (v.video_codec || '?').toUpperCase() + (v.audio_codec && v.audio_codec !== 'none' ? ' / ' + v.audio_codec.toUpperCase() : ' (sem áudio)');
    $('val-fps').textContent = v.fps; $('val-size').textContent = fmtBytes(v.size);
    const st = $('val-status'); st.textContent = v.compatible ? '✓ Compatível' : '✗ Incompatível';
    st.className = 'v ' + (v.compatible ? 'status-ok' : 'status-bad');
    const ul = $('val-reasons'); ul.innerHTML = '';
    for (const r of (v.reasons || [])) { const li = document.createElement('li'); li.textContent = '✗ ' + r; ul.appendChild(li); }
    $('publish-btn').disabled = !v.compatible; $('validation').hidden = false;
  }

  $('publish-btn').onclick = async () => {
    if (!uploadedVideo) return;
    $('publish-btn').disabled = true;
    const r = await api(`/api/video/${uploadedVideo.id}/publish`, { method: 'POST' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { $('upload-error').textContent = '✗ ' + (j.detail || 'Falha ao publicar'); $('upload-error').hidden = false; $('publish-btn').disabled = false; return; }
    $('publish-ok').textContent = `✓ Publicado como versão ${j.version}. Os ônibus receberão o vídeo ao entrar na garagem.`;
    $('publish-ok').hidden = false; $('validation').hidden = true; $('selected-file').hidden = true;
    selectedFile = null; uploadedVideo = null; $('file-input').value = ''; $('upload-btn').disabled = true;
    await refresh();
  };

  $('logout').onclick = async () => { await fetch('/api/auth/logout', { method: 'POST' }); location.href = '/login'; };

  // --- Senha de acesso: qualquer usuário troca a própria; o administrador redefine a de qualquer conta ---
  const ME = document.body.dataset.user, ROLE = document.body.dataset.role;
  const ROLE_LABEL = { admin: 'administrador', operator: 'operador' };
  function pwTarget() { return ROLE === 'admin' ? $('pw-target').value || ME : ME; }
  function pwSyncFields() {
    const own = pwTarget() === ME;
    $('pw-current-label').hidden = !own; $('pw-current').required = own;
    $('pw-help').textContent = own
      ? 'Informe a senha atual e escolha a nova.'
      : `Você vai definir uma nova senha para a conta "${pwTarget()}". A senha antiga deixa de valer na hora; avise quem usa essa conta.`;
  }
  async function pwOpen() {
    $('pw-error').hidden = true; $('pw-ok').hidden = true; $('pw-form').reset();
    if (ROLE === 'admin') {
      const r = await api('/api/auth/users'); const users = r.ok ? await r.json() : [];
      const sel = $('pw-target'); sel.replaceChildren();
      for (const u of users) {
        const o = document.createElement('option'); o.value = u.user;
        o.textContent = `${u.user} (${ROLE_LABEL[u.role] || u.role}${u.has_password ? '' : ', sem senha'})`;
        if (u.role === 'operator') o.selected = true;
        sel.appendChild(o);
      }
      $('pw-target-label').hidden = false;
    }
    pwSyncFields();
    $('password-card').hidden = false; $('password-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  $('pw-btn').onclick = pwOpen;
  $('pw-cancel').onclick = () => { $('password-card').hidden = true; };
  $('pw-target').onchange = pwSyncFields;
  $('pw-form').onsubmit = async (ev) => {
    ev.preventDefault();
    $('pw-error').hidden = true; $('pw-ok').hidden = true;
    const n1 = $('pw-new').value, n2 = $('pw-new2').value;
    if (n1.length < 8) { $('pw-error').textContent = 'A nova senha precisa ter pelo menos 8 caracteres.'; $('pw-error').hidden = false; return; }
    if (n1 !== n2) { $('pw-error').textContent = 'As duas senhas novas não são iguais.'; $('pw-error').hidden = false; return; }
    const body = { username: pwTarget(), new_password: n1 };
    if (pwTarget() === ME) body.current_password = $('pw-current').value;
    const r = await api('/api/auth/password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { $('pw-error').textContent = '✗ ' + (j.detail || 'Não foi possível trocar a senha'); $('pw-error').hidden = false; return; }
    $('pw-form').reset(); pwSyncFields();
    $('pw-ok').textContent = `✓ Senha de "${j.user}" alterada.`; $('pw-ok').hidden = false;
  };

  async function refresh() { try { await loadCurrent(); await loadDevices(); } catch (e) { console.warn(e); } }
  refresh(); setInterval(loadDevices, 5000);
})();
