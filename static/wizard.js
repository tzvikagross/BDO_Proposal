(async function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const BASE = window.APP_BASE || '';   // set when the app runs under a sub-path (IIS application)
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const CAT = await (await fetch(BASE + '/api/catalog')).json();
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
  const NO_AMOUNT = new Set(['Included']);
  const fmt = v => (v === null || v === undefined || v === '') ? '' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 });
  let currency = CAT.client_types[clientType].default_currency || CAT.currencies[0];
  let currencyTouched = false;
  $('#date').valueAsDate = new Date();
  const segCount = id => CAT.segments.filter(s => (s.default_for || []).includes(id)).length;
  $('#types').innerHTML = Object.entries(CAT.client_types).map(([id, t]) =>
    `<label class="type${id === clientType ? ' on' : ''}"><input type="radio" name="ctype" value="${id}"${id === clientType ? ' checked' : ''}>
      <b>${esc(t.label)}</b><small>${segCount(id)} service segments · ${esc(t.proposal_title)}</small></label>`).join('');
  $('#scope').innerHTML = CAT.scope_fields.map(f => `<label>${esc(f.label)}<input data-scope="${f.id}"></label>`).join('');
  $$('select.currency').forEach(sel => sel.innerHTML = CAT.currencies.map(c => `<option>${c}</option>`).join(''));
  $('#title').addEventListener('input', () => titleTouched = true);
  $$('input[name=ctype]').forEach(r => r.addEventListener('change', () => { clientType = r.value; applyType(); }));
  $$('select.currency').forEach(sel => sel.addEventListener('change', () => {
    if (!setCurrency(sel.value)) sel.value = currency; else currencyTouched = true;
  }));

  function applyType() {
    const t = CAT.client_types[clientType];
    $$('.type').forEach(l => l.classList.toggle('on', $('input', l).value === clientType));
    if (!titleTouched) $('#title').value = t.proposal_title;
    if (!currencyTouched && t.default_currency) currency = t.default_currency;
    $$('select.currency').forEach(s => s.value = currency);
    buildGroups();
  }

  // returns false if the user cancels
  function setCurrency(c) {
    if (c === currency) return true;
    const edited = $$('.row.edited').length;
    if (edited && !confirm(`Switching to ${c} resets the ${edited} fee(s) you changed to the ${c} default prices. Continue?`)) return false;
    currency = c;
    $$('select.currency').forEach(s => s.value = c);
    $$('.row[data-type=item]').forEach(r => {
      const fees = JSON.parse(r.dataset.fees || '{}');
      if (c in fees) { $('.fee', r).value = fmt(fees[c]); r.classList.remove('edited'); }
      renderDefaults(r);
    });
    $$('.cur-label').forEach(el => el.textContent = c);
    return true;
  }

  // ---------- step 3: segment editors
  function unitOptions(sel) {
    const units = CAT.units.includes(sel) || !sel ? CAT.units : [...CAT.units, sel];
    return units.map(u => `<option${u === sel ? ' selected' : ''}>${esc(u)}</option>`).join('');
  }
  function defaultsHtml(fees, unit) {
    if (!fees || !Object.keys(fees).length) return '<span>Custom service – no default price</span>';
    if (NO_AMOUNT.has(unit)) return '<span>No charge – included</span>';
    return 'Defaults: ' + CAT.currencies.map(c => `<span class="${c === currency ? 'cur-on' : ''}">${c} ${fees[c] == null ? '—' : fmt(fees[c])}</span>`).join(' · ')
      + ' <a href="#" class="reset" title="Use the default price">reset</a>';
  }
  function renderDefaults(r) {
    $('.defaults', r).innerHTML = defaultsHtml(JSON.parse(r.dataset.fees || '{}'), $('.unit', r).value);
    $('.fee', r).disabled = NO_AMOUNT.has($('.unit', r).value);
  }
  function rowHtml(r) {
    if (r.type === 'subheader') {
      return `<div class="row sub" data-type="subheader"><span></span>
        <input class="text" value="${esc(r.text)}" placeholder="Sub-heading">
        <button class="del" title="Remove" type="button">×</button></div>`;
    }
    const inc = r.selected !== false && r.include !== false;
    const fees = r.fees || {};
    const fee = currency in fees ? fees[currency] : r.fee;
    const noAmt = NO_AMOUNT.has(r.unit);
    return `<div class="row${inc ? '' : ' off'}" data-type="item" data-id="${esc(r.id || '')}" data-fees="${esc(JSON.stringify(fees))}">
      <span class="inc"><input type="checkbox" ${inc ? 'checked' : ''} title="Include in proposal"></span>
      <div class="feebox"><span class="cur-label">${currency}</span><input class="fee" inputmode="decimal" value="${esc(fmt(fee))}" placeholder="Fee" ${noAmt ? 'disabled' : ''}></div>
      <select class="unit" title="Fee unit">${unitOptions(r.unit || 'Monthly')}</select>
      <textarea class="desc" rows="${Math.max(1, (r.description || []).length)}" placeholder="Service description – one bullet per line">${esc((r.description || []).join('\n'))}</textarea>
      <button class="del" title="Remove" type="button">×</button>
      <div class="defaults">${defaultsHtml(fees, r.unit)}</div></div>`;
  }

  function groupHtml(s, on) {
    const note = s.rows.find(r => r.type === 'subheader' && r.note);
    return `<div class="group${on ? '' : ' off'}" data-id="${s.id}" data-section="${esc(s.section)}" data-footnotes="${esc(s.footnotes || 'default')}"
               data-bullets="${s.bullets === false ? '0' : '1'}" data-feeheader="${esc(s.fee_header || 'Cost')}" data-title="${esc(s.name)}">
      <div class="ghead">
        <input type="checkbox" class="gon" ${on ? 'checked' : ''} title="Include this segment">
        <span class="gt">${esc(s.name)}<small>${esc(s.section)}</small></span>
        <span class="gcount"></span>
      </div>
      <div class="rows">
        ${note ? `<label style="margin-top:8px">Basis / assumption shown in the fee column<input class="note" value="${esc(note.note)}"></label>` : ''}
        <div class="rowhead"><span></span><span>Fee</span><span>Unit</span><span>Description (one bullet per line)</span><span></span></div>
        <div class="rowlist">${s.rows.map(rowHtml).join('')}</div>
        <div class="gfoot"><button type="button" class="small-btn add-item">+ Add service</button><button type="button" class="small-btn add-sub">+ Add sub-heading</button></div>
      </div></div>`;
  }

  function countGroup(g) {
    const items = $$('.row[data-type=item]', g);
    $('.gcount', g).textContent = `${items.filter(r => $('.inc input', r).checked).length} of ${items.length} services`;
  }
  function buildGroups() {
    const mine = CAT.segments.filter(s => (s.default_for || []).includes(clientType));
    const others = CAT.segments.filter(s => !(s.default_for || []).includes(clientType));
    $('#groups').innerHTML = mine.map(s => groupHtml(s, true)).join('') || '<p class="hint">No segments are set as default for this client type – pick from “Other service segments” or set defaults in Admin.</p>';
    $('#groupsMore').innerHTML = others.map(s => groupHtml(s, false)).join('');
    $('.more').style.display = others.length ? '' : 'none';
    $$('.group').forEach(countGroup);
  }

  document.addEventListener('change', e => {
    const g = e.target.closest('.group');
    if (e.target.matches('.gon')) g.classList.toggle('off', !e.target.checked);
    if (e.target.matches('.inc input')) e.target.closest('.row').classList.toggle('off', !e.target.checked);
    if (e.target.matches('select.unit')) renderDefaults(e.target.closest('.row'));
    if (g) countGroup(g);
  });
  document.addEventListener('click', e => {
    const g = e.target.closest('.group');
    if (e.target.matches('.del')) { e.target.closest('.row').remove(); countGroup(g); }
    if (e.target.matches('.reset')) {
      e.preventDefault();
      const r = e.target.closest('.row'); const fees = JSON.parse(r.dataset.fees || '{}');
      $('.fee', r).value = fmt(fees[currency]); r.classList.remove('edited');
    }
    if (e.target.matches('.add-item')) {
      $('.rowlist', g).insertAdjacentHTML('beforeend', rowHtml({ type: 'item', unit: 'Monthly', description: [], fees: {} }));
      $('.rowlist .row:last-child .desc', g).focus(); countGroup(g);
    }
    if (e.target.matches('.add-sub')) $('.rowlist', g).insertAdjacentHTML('beforeend', rowHtml({ type: 'subheader', text: '' }));
  });
  document.addEventListener('input', e => {
    if (e.target.matches('textarea.desc')) e.target.rows = Math.max(1, e.target.value.split('\n').length);
    if (e.target.matches('input.fee')) {
      const r = e.target.closest('.row'); const fees = JSON.parse(r.dataset.fees || '{}');
      const v = e.target.value.replace(/,/g, '').trim();
      r.classList.toggle('edited', currency in fees && String(fees[currency] ?? '') !== v);
    }
  });

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
        return { type: 'item', id: r.dataset.id, include: $('.inc input', r).checked, fee: $('.fee', r).value.replace(/,/g, '').trim(),
                 unit: $('.unit', r).value, description: $('.desc', r).value.split('\n') };
      });
      groups.push({ id: g.dataset.id, section: g.dataset.section, title: g.dataset.title,
                    fee_header: g.dataset.feeheader, footnotes: g.dataset.footnotes, bullets: g.dataset.bullets === '1', rows });
    });
    const scope = {};
    $$('[data-scope]').forEach(i => { if (i.value.trim()) scope[i.dataset.scope] = i.value.trim(); });
    return {
      client: { company: $('#company').value, contact_name: $('#contact').value, salutation: $('#salutation').value,
                opportunity: $('#opportunity').value, date: $('#date').value, client_type: clientType, title: $('#title').value,
                currency },
      team: $$('input[name=bio]:checked').map(c => c.value),
      scope, groups,
    };
  }

  function renderSummary() {
    const p = collect();
    const items = p.groups.reduce((n, g) => n + g.rows.filter(r => r.type === 'item' && r.include).length, 0);
    const team = $$('input[name=bio]:checked').map(c => c.dataset.name);
    const missing = p.groups.flatMap(g => g.rows.filter(r => r.type === 'item' && r.include && !NO_AMOUNT.has(r.unit) && !r.fee).map(r => r.description[0] || '(no description)'));
    $('#summary').innerHTML = `<b>${esc(p.client.company)}</b> · ${esc(CAT.client_types[clientType].label)} · ${esc(p.client.title)} · fees in <b>${currency}</b><br>
      Contact: ${esc((p.client.salutation + ' ' + p.client.contact_name).trim() || '—')} · Opportunity ${esc(p.client.opportunity || '000000')}<br>
      Engagement team: ${team.length ? esc(team.join(', ')) : '<i>none selected</i>'}<br>
      ${p.groups.length} service segments, ${items} services:
      <ul>${p.groups.map(g => `<li>${esc(g.title)} <small>(${esc(g.section)})</small> – ${g.rows.filter(r => r.type === 'item' && r.include).length} services</li>`).join('')}</ul>
      ${missing.length ? `<p class="warn">No fee entered for: ${missing.map(esc).join('; ')}</p>` : ''}`;
  }

  // ---------- generate
  $('#generate').addEventListener('click', async () => {
    const formats = $$('input[name=fmt]:checked').map(c => c.value);
    const res = $('#result');
    if (!formats.length) { res.innerHTML = '<div class="err">Choose at least one format.</div>'; return; }
    const btn = $('#generate'); btn.disabled = true; btn.textContent = 'Generating…';
    res.innerHTML = '';
    try {
      const r = await fetch(BASE + '/api/proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal: collect(), formats }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      const label = { pptx: 'Download PowerPoint', pdf: 'Download PDF', html: 'Download HTML file (to email)', online: 'Preview HTML ↗' };
      res.innerHTML = `<div class="ok"><b>Proposal ready.</b> Reference ${esc(j.id)}<br>
        ${Object.entries(j.files).map(([k, u]) => `<a class="dl" href="${esc(u)}" ${k === 'online' ? 'target="_blank" rel="noopener"' : ''}>${label[k] || k}</a>`).join('')}
        ${j.files.html ? `<p style="font-size:13px;margin:12px 0 0">Email the HTML file to the client. They open it on their own computer, sign in the <b>Accept &amp; Sign</b> tab with their name or initials, download the signed PDF and email it back to you. The file works offline and never contacts this server.</p>` : ''}
        ${Object.entries(j.errors || {}).map(([k, v]) => `<p class="err" style="margin-top:10px">${esc(k.toUpperCase())}: ${esc(v)}</p>`).join('')}</div>`;
    } catch (e) {
      res.innerHTML = `<div class="err">${esc(e.message)}</div>`;
    } finally { btn.disabled = false; btn.textContent = 'Generate'; }
  });

  // ---------- history
  $('#historyLink').addEventListener('click', async e => {
    e.preventDefault();
    const rows = await (await fetch(BASE + '/proposals')).json();
    $('#histTable').innerHTML = '<tr><th>Date</th><th>Client</th><th>Services</th><th>Files</th><th></th></tr>' + (rows.map(r =>
      `<tr><td>${esc(r.date)}</td><td>${esc(r.company)}</td><td>${esc(r.title)}</td>
        <td>${Object.entries(r.files || {}).map(([k, u]) => `<a href="${esc(u)}">${k.toUpperCase()}</a>`).join(' · ') || '—'}</td>
        <td><a href="${esc(r.online)}" target="_blank" rel="noopener">Preview</a></td></tr>`).join('') || '<tr><td colspan="5">No proposals yet.</td></tr>');
    $$('.step').forEach(s => s.classList.toggle('on', s.id === 'step-history'));
    $$('#steps li').forEach(li => li.classList.remove('on'));
  });

  // ---------- engagement team (bios)
  function bioCard(b, checked) {
    const exp = (b.experience || []).map(e => `<p>${esc(e)}</p>`).join('');
    return `<div class="bio${checked ? ' on' : ''}">
      <label class="bio-head">
        <input type="checkbox" name="bio" value="${esc(b.id)}" data-name="${esc(b.name)}" ${checked ? 'checked' : ''}>
        ${b.has_photo ? `<img src="${BASE}/team/${esc(b.id)}/photo" alt="">` : '<span class="nophoto"></span>'}
        <span><b>${esc(b.name)}</b>${b.default ? ' <em class="tag">default</em>' : ''}<br>
          <small>${esc([b.credentials, b.title].filter(Boolean).join(' · '))}</small>
          ${b.email ? `<br><small>${esc(b.email)}${b.phone ? ' · ' + esc(b.phone) : ''}</small>` : ''}</span>
      </label>
      <details><summary>Read bio</summary>
        ${b.role ? `<h4>Current role at BDO</h4><p>${esc(b.role)}</p>` : ''}
        ${exp ? `<h4>Relevant experience</h4>${exp}` : ''}
        <p><a href="${BASE}/team/${esc(b.id)}/slide">Download slide (PPTX)</a></p>
      </details></div>`;
  }
  async function loadBios(selectId) {
    const prev = new Set($$('input[name=bio]:checked').map(c => c.value));
    const first = !$$('input[name=bio]').length;
    const bios = await (await fetch(BASE + '/api/team')).json();
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
      const r = await fetch(BASE + '/api/team', { method: 'POST', body: fd });
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
