(async function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const CAT = await (await fetch('/api/catalog')).json();
  let clientType = 'accounting';
  let titleTouched = false;

  // ---------- step navigation
  function go(n) {
    $$('.step').forEach(s => s.classList.toggle('on', s.id === 'step-' + n));
    $$('#steps li').forEach(li => li.classList.toggle('on', li.dataset.step == n));
    if (n == 4) renderSummary();
    window.scrollTo({ top: 0 });
  }
  $$('[data-next]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.next !== '1' && !$('#company').value.trim()) { go(1); $('#company').focus(); $('#company').reportValidity(); return; }
    go(b.dataset.next);
  }));
  $$('#steps li').forEach(li => li.addEventListener('click', () => $(`[data-next="${li.dataset.step}"]`) && $(`[data-next="${li.dataset.step}"]`).click()));

  // ---------- step 1
  $('#date').valueAsDate = new Date();
  $('#types').innerHTML = Object.entries(CAT.client_types).map(([id, t]) =>
    `<label class="type${id === clientType ? ' on' : ''}"><input type="radio" name="ctype" value="${id}"${id === clientType ? ' checked' : ''}>
      <b>${esc(t.label)}</b><small>${t.groups.length} service groups · ${esc(t.proposal_title)}</small></label>`).join('');
  $('#scope').innerHTML = CAT.scope_fields.map(f => `<label>${esc(f.label)}<input data-scope="${f.id}"></label>`).join('');
  $('#title').addEventListener('input', () => titleTouched = true);
  $$('input[name=ctype]').forEach(r => r.addEventListener('change', () => { clientType = r.value; applyType(); }));

  function applyType() {
    const t = CAT.client_types[clientType];
    $$('.type').forEach(l => l.classList.toggle('on', $('input', l).value === clientType));
    if (!titleTouched) $('#title').value = t.proposal_title;
    buildGroups();
  }

  // ---------- step 2: group editors
  function rowHtml(r) {
    if (r.type === 'subheader') {
      return `<div class="row sub" data-type="subheader"><span></span>
        <input class="text" value="${esc(r.text)}" placeholder="Sub-heading">
        <button class="del" title="Remove" type="button">×</button></div>`;
    }
    const inc = r.include !== false;
    return `<div class="row${inc ? '' : ' off'}" data-type="item" data-id="${esc(r.id || '')}">
      <span class="inc"><input type="checkbox" ${inc ? 'checked' : ''} title="Include in proposal"></span>
      <input class="fee" value="${esc(r.fee ?? '')}" placeholder="Fee">
      <input class="unit" value="${esc(r.unit || '')}" placeholder="Unit (Monthly…)" list="units">
      <textarea class="desc" rows="${Math.max(1, (r.description || []).length)}" placeholder="Service description – one bullet per line">${esc((r.description || []).join('\n'))}</textarea>
      <button class="del" title="Remove" type="button">×</button></div>`;
  }

  function groupHtml(g, on) {
    const note = g.rows.find(r => r.type === 'subheader' && r.note);
    return `<div class="group${on ? '' : ' off'}" data-id="${g.id}" data-section="${esc(g.section)}" data-footnotes="${esc(g.footnotes || 'default')}"
               data-bullets="${g.bullets === false ? '0' : '1'}" data-feeheader="${esc(g.fee_header || 'Cost')}" data-title="${esc(g.title)}">
      <div class="ghead">
        <input type="checkbox" class="gon" ${on ? 'checked' : ''} title="Include this group">
        <span class="gt">${esc(g.title)}<small>${esc(g.section)}</small></span>
        <label style="flex-direction:row;align-items:center;gap:6px;font-weight:normal;color:#fff">Currency
          <select class="cur">${['USD', 'ILS', 'EUR', 'GBP'].map(c => `<option${c === g.currency ? ' selected' : ''}>${c}</option>`).join('')}</select></label>
      </div>
      <div class="rows">
        ${note ? `<label style="margin-top:8px">Basis / assumption shown in the fee column<input class="note" value="${esc(note.note)}"></label>` : ''}
        <div class="rowhead"><span></span><span>Fee</span><span>Unit</span><span>Description (one bullet per line)</span><span></span></div>
        <div class="rowlist">${g.rows.map(rowHtml).join('')}</div>
        <div class="gfoot"><button type="button" class="small-btn add-item">+ Add service</button><button type="button" class="small-btn add-sub">+ Add sub-heading</button></div>
      </div></div>`;
  }

  function buildGroups() {
    const t = CAT.client_types[clientType];
    const mine = t.groups.map(id => CAT.groups.find(g => g.id === id)).filter(Boolean);
    const others = CAT.groups.filter(g => !t.groups.includes(g.id));
    $('#groups').innerHTML = mine.map(g => groupHtml(g, true)).join('');
    $('#groupsMore').innerHTML = others.map(g => groupHtml(g, false)).join('') || '<p class="hint">All groups are already listed.</p>';
    $('.more').style.display = others.length ? '' : 'none';
  }

  document.addEventListener('change', e => {
    if (e.target.matches('.gon')) e.target.closest('.group').classList.toggle('off', !e.target.checked);
    if (e.target.matches('.inc input')) e.target.closest('.row').classList.toggle('off', !e.target.checked);
  });
  document.addEventListener('click', e => {
    const g = e.target.closest('.group');
    if (e.target.matches('.del')) e.target.closest('.row').remove();
    if (e.target.matches('.add-item')) { $('.rowlist', g).insertAdjacentHTML('beforeend', rowHtml({ type: 'item', fee: '', unit: 'Monthly', description: [] })); $('.rowlist .row:last-child .fee', g).focus(); }
    if (e.target.matches('.add-sub')) $('.rowlist', g).insertAdjacentHTML('beforeend', rowHtml({ type: 'subheader', text: '' }));
  });
  document.addEventListener('input', e => { if (e.target.matches('textarea.desc')) { e.target.rows = Math.max(1, e.target.value.split('\n').length); } });
  document.body.insertAdjacentHTML('beforeend', `<datalist id="units">${['Monthly', 'Annual', 'Annually', 'One time', 'Per case', 'Per hour', 'Hourly', 'Per Employee', 'Quarterly'].map(u => `<option value="${u}">`).join('')}</datalist>`);

  // ---------- collect
  function collect() {
    const groups = [];
    $$('.group').forEach(g => {
      if (!$('.gon', g).checked) return;
      const note = $('.note', g);
      let noteUsed = false;
      const rows = $$('.rowlist .row', g).map(r => {
        if (r.dataset.type === 'subheader') {
          const row = { type: 'subheader', text: $('.text', r).value, note: '' };
          if (note && !noteUsed) { row.note = note.value; noteUsed = true; }
          return row;
        }
        return { type: 'item', id: r.dataset.id, include: $('.inc input', r).checked, fee: $('.fee', r).value,
                 unit: $('.unit', r).value, description: $('.desc', r).value.split('\n') };
      });
      groups.push({ id: g.dataset.id, section: g.dataset.section, title: g.dataset.title, currency: $('.cur', g).value,
                    fee_header: g.dataset.feeheader, footnotes: g.dataset.footnotes, bullets: g.dataset.bullets === '1', rows });
    });
    const scope = {};
    $$('[data-scope]').forEach(i => { if (i.value.trim()) scope[i.dataset.scope] = i.value.trim(); });
    return {
      client: { company: $('#company').value, contact_name: $('#contact').value, salutation: $('#salutation').value,
                opportunity: $('#opportunity').value, date: $('#date').value, client_type: clientType, title: $('#title').value },
      team: $$('input[name=bio]:checked').map(c => c.value),
      scope, groups,
    };
  }

  function renderSummary() {
    const p = collect();
    const items = p.groups.reduce((n, g) => n + g.rows.filter(r => r.type === 'item' && r.include).length, 0);
    const team = $$('input[name=bio]:checked').map(c => c.dataset.name);
    $('#summary').innerHTML = `<b>${esc(p.client.company)}</b> · ${esc(CAT.client_types[clientType].label)} · ${esc(p.client.title)}<br>
      Contact: ${esc((p.client.salutation + ' ' + p.client.contact_name).trim() || '—')} · Opportunity ${esc(p.client.opportunity || '000000')}<br>
      Engagement team: ${team.length ? esc(team.join(', ')) : '<i>none selected</i>'}<br>
      ${p.groups.length} service groups, ${items} services:
      <ul>${p.groups.map(g => `<li>${esc(g.title)} <small>(${esc(g.section)}, ${g.currency})</small> – ${g.rows.filter(r => r.type === 'item' && r.include).length} services</li>`).join('')}</ul>`;
  }

  // ---------- generate
  $('#generate').addEventListener('click', async () => {
    const formats = $$('input[name=fmt]:checked').map(c => c.value);
    const res = $('#result');
    if (!formats.length) { res.innerHTML = '<div class="err">Choose at least one format.</div>'; return; }
    const btn = $('#generate'); btn.disabled = true; btn.textContent = 'Generating…';
    res.innerHTML = '';
    try {
      const r = await fetch('/api/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal: collect(), formats }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      const label = { pptx: 'Download PowerPoint', pdf: 'Download PDF', html: 'Download HTML file', online: 'Open online proposal ↗' };
      res.innerHTML = `<div class="ok"><b>Proposal ready.</b> Reference ${esc(j.id)}<br>
        ${Object.entries(j.files).map(([k, u]) => `<a class="dl" href="${esc(u)}" ${k === 'online' ? 'target="_blank" rel="noopener"' : ''}>${label[k] || k}</a>`).join('')}
        ${j.files.online ? `<p style="font-size:13px;margin:12px 0 0">Send the client the HTML file or the online link (${esc(j.files.online)}). When they sign, the digitally signed PDF is saved under this proposal and listed in “Previous proposals”.</p>` : ''}
        ${Object.entries(j.errors || {}).map(([k, v]) => `<p class="err" style="margin-top:10px">${esc(k.toUpperCase())}: ${esc(v)}</p>`).join('')}</div>`;
    } catch (e) {
      res.innerHTML = `<div class="err">${esc(e.message)}</div>`;
    } finally { btn.disabled = false; btn.textContent = 'Generate'; }
  });

  // ---------- history
  $('#historyLink').addEventListener('click', async e => {
    e.preventDefault();
    const rows = await (await fetch('/proposals')).json();
    $('#histTable').innerHTML = '<tr><th>Date</th><th>Client</th><th>Services</th><th>Signed copies</th><th></th></tr>' + (rows.map(r =>
      `<tr><td>${esc(r.date)}</td><td>${esc(r.company)}</td><td>${esc(r.title)}</td>
        <td>${r.signed.length ? r.signed.map(u => `<a href="${esc(u)}">PDF</a>`).join(' ') : '—'}</td>
        <td><a href="/p/${esc(r.id)}" target="_blank" rel="noopener">Open</a></td></tr>`).join('') || '<tr><td colspan="5">No proposals yet.</td></tr>');
    $$('.step').forEach(s => s.classList.toggle('on', s.id === 'step-history'));
    $$('#steps li').forEach(li => li.classList.remove('on'));
  });

  // ---------- engagement team (bios)
  function bioCard(b, checked) {
    const exp = (b.experience || []).map(e => `<p>${esc(e)}</p>`).join('');
    return `<div class="bio${checked ? ' on' : ''}">
      <label class="bio-head">
        <input type="checkbox" name="bio" value="${esc(b.id)}" data-name="${esc(b.name)}" ${checked ? 'checked' : ''}>
        ${b.has_photo ? `<img src="/team/${esc(b.id)}/photo" alt="">` : '<span class="nophoto"></span>'}
        <span><b>${esc(b.name)}</b>${b.default ? ' <em class="tag">default</em>' : ''}<br>
          <small>${esc([b.credentials, b.title].filter(Boolean).join(' · '))}</small>
          ${b.email ? `<br><small>${esc(b.email)}${b.phone ? ' · ' + esc(b.phone) : ''}</small>` : ''}</span>
      </label>
      <details><summary>Read bio</summary>
        ${b.role ? `<h4>Current role at BDO</h4><p>${esc(b.role)}</p>` : ''}
        ${exp ? `<h4>Relevant experience</h4>${exp}` : ''}
        <p><a href="/team/${esc(b.id)}/slide">Download slide (PPTX)</a></p>
      </details></div>`;
  }
  async function loadBios(selectId) {
    const prev = new Set($$('input[name=bio]:checked').map(c => c.value));
    const first = !$$('input[name=bio]').length;
    const bios = await (await fetch('/api/team')).json();
    $('#bios').innerHTML = bios.map(b => bioCard(b, first ? b.default : (prev.has(b.id) || b.id === selectId))).join('')
      || '<p class="hint">No bios yet – add one with “Add a bio”.</p>';
    countBios();
  }
  function countBios() {
    const n = $$('input[name=bio]:checked').length;
    $('#bioCount').textContent = `${n} of ${$$('input[name=bio]').length} selected`;
    $$('.bio').forEach(el => el.classList.toggle('on', $('input', el).checked));
  }
  $('#bios').addEventListener('change', countBios);
  $('#bioAll').onclick = () => { $$('input[name=bio]').forEach(c => c.checked = true); countBios(); };
  $('#bioNone').onclick = () => { $$('input[name=bio]').forEach(c => c.checked = false); countBios(); };
  $('#bioUpload').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    const msg = $('#bioMsg'); msg.className = 'bio-msg'; msg.textContent = `Uploading ${f.name}…`;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await fetch('/api/team', { method: 'POST', body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      await loadBios(j.id);
      msg.className = 'bio-msg ok';
      msg.textContent = `Added ${j.name}. Check the details below; to fine-tune the text edit assets/team/${j.id}.json.`;
    } catch (err) { msg.className = 'bio-msg err'; msg.textContent = err.message; }
    e.target.value = '';
  });

  await loadBios();
  applyType();
})();
