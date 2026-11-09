(async function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const BASE = window.APP_BASE || '';   // set when the app runs under a sub-path (IIS application)
  // read a JSON reply; if the server sent something else (e.g. an error page), say so clearly
  async function readJson(r) {
    const text = await r.text();
    try { return JSON.parse(text); }
    catch (e) { throw new Error(`The server returned an unexpected reply (HTTP ${r.status}). Details are in the logs folder on the server.`); }
  }
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const FOOTNOTES = { default: 'Standard (VAT + digital invoices)', fund: 'Funds (VAT + out-of-pocket + digital invoices)' };
  let CAT, dirty = false;
  let TYPES = [];                                        // types of client, edited in the first section
  const newId = () => 'new_' + Math.random().toString(36).slice(2, 9);

  async function load() {
    CAT = await readJson(await fetch(BASE + '/api/catalog'));
    render();
    setDirty(false);
    loadHistory();
  }

  // ---------- render
  function render(openTypes = new Set()) {
    TYPES = Object.entries(CAT.client_types).map(([id, t]) => ({
      id, label: t.label, code: t.code || '', proposal_title: t.proposal_title || '', default_currency: t.default_currency,
      segments: [...(t.segments || [])], excluded: JSON.parse(JSON.stringify(t.excluded || {})), _open: openTypes.has(id),
    }));
    $('#units').innerHTML = CAT.units.map(unitChip).join('');
    $('#segments').innerHTML = CAT.segments.map(segHtml).join('');
    renderTypes();
    refreshDerived();
  }

  // ---------- types of client
  const segName = d => $('.s-name', d).value.trim() || 'New segment';
  // the segments and services as they currently stand on the page (including unsaved edits)
  const liveSegments = () => $$('.seg').map(d => ({
    id: d.dataset.id, name: segName(d), section: $('.s-section', d).value.trim(),
    services: $$('.arow[data-type=service]', d).map(r => ({ id: r.dataset.id, name: ($('.r-desc', r).value.split('\n')[0] || '').trim() || 'New service' })),
  }));
  function typeCard(t) {
    return `<details class="tcard" data-id="${esc(t.id)}" ${t._open ? 'open' : ''}>
      <summary><span class="code-chip">${esc(t.code || '??')}</span><span class="t-name">${esc(t.label || 'New type of client')}</span>
        <small class="t-meta"></small></summary>
      <div class="t-body">
        <div class="t-fields">
          <label>Name<input class="t-label" value="${esc(t.label)}" placeholder="e.g. Accounting client"></label>
          <label>Letters<input class="t-code" value="${esc(t.code)}" maxlength="2" placeholder="LF" title="Two capital letters, used at the start of proposal numbers, e.g. LF26-0001"></label>
          <label>Cover title<input class="t-title" value="${esc(t.proposal_title)}" placeholder="e.g. Accounting & Outsourcing Services"></label>
          <label>Default currency<select class="t-cur">${CAT.currencies.map(c => `<option${c === t.default_currency ? ' selected' : ''}>${c}</option>`).join('')}</select></label>
        </div>
        <p class="t-help">Tick the segments this type of client gets. Inside each ticked segment, tick the services that start ticked in the wizard (they can still be changed for each proposal).</p>
        <div class="t-segs"></div>
        <div class="gfoot"><button type="button" class="small-btn danger del-type">Delete this type of client</button></div>
      </div></details>`;
  }
  function typeSegsHtml(t) {
    const segs = liveSegments();
    if (!segs.length) return '<p class="hint">No segments yet.</p>';
    return segs.map(sg => {
      const on = t.segments.includes(sg.id);
      const off = new Set(t.excluded[sg.id] || []);
      const ticked = sg.services.filter(v => !off.has(v.id)).length;
      return `<div class="t-seg${on ? ' on' : ''}" data-seg="${esc(sg.id)}">
        <label class="t-seg-head"><input type="checkbox" class="t-segbox" ${on ? 'checked' : ''}> <b>${esc(sg.name)}</b>
          <small>${esc(sg.section)}${on ? ` · ${ticked} of ${sg.services.length} services ticked` : ''}</small></label>
        ${on && sg.services.length ? `<div class="t-svcs">${sg.services.map(v => `<label><input type="checkbox" class="t-svcbox" data-svc="${esc(v.id)}" ${off.has(v.id) ? '' : 'checked'}> ${esc(v.name)}</label>`).join('')}</div>` : ''}
      </div>`;
    }).join('');
  }
  function readType(card) {
    const t = TYPES.find(x => x.id === card.dataset.id);
    t.label = $('.t-label', card).value.trim();
    t.code = $('.t-code', card).value.trim().toUpperCase();
    t.proposal_title = $('.t-title', card).value.trim();
    t.default_currency = $('.t-cur', card).value;
    t._open = card.open;
    $$('.t-seg', card).forEach(el => {
      const sid = el.dataset.seg, on = $('.t-segbox', el).checked;
      t.segments = t.segments.filter(x => x !== sid);
      if (on) t.segments.push(sid);
      if (on && $$('.t-svcbox', el).length) t.excluded[sid] = $$('.t-svcbox', el).filter(c => !c.checked).map(c => c.dataset.svc);
    });
    return t;
  }
  function renderTypeSegs(card) {
    const t = TYPES.find(x => x.id === card.dataset.id);
    $('.t-segs', card).innerHTML = typeSegsHtml(t);
    $('.t-meta', card).textContent = `${t.segments.filter(id => $$('.seg').some(d => d.dataset.id === id)).length} segments · cover: ${t.proposal_title || '—'} · ${t.default_currency}`;
    $('.code-chip', card).textContent = t.code || '??';
    $('.t-name', card).textContent = t.label || 'New type of client';
  }
  function renderTypes() {
    $('#types').innerHTML = TYPES.map(typeCard).join('');
    $$('.tcard').forEach(renderTypeSegs);
    refreshUsedBy();
  }
  // after segments/services change further down the page, update the type checklists
  let typesTimer = null;
  function refreshTypesSoon() {
    clearTimeout(typesTimer);
    typesTimer = setTimeout(() => { $$('.tcard').forEach(c => { readType(c); renderTypeSegs(c); }); refreshUsedBy(); }, 250);
  }
  function refreshUsedBy() {
    $$('.seg').forEach(d => {
      const users = TYPES.filter(t => t.segments.includes(d.dataset.id)).map(t => t.code || t.label || '?');
      $('.s-usedby', d).textContent = users.length ? users.join(', ') : 'no type of client (only under “Other service segments”)';
      const n = $$('.arow[data-type=service]', d).length;
      $('.seg-meta', d).textContent = `${$('.s-section', d).value.trim()} · ${n} services · used by: ${users.join(', ') || 'none'}`;
    });
  }
  $('#types').addEventListener('input', e => {
    const card = e.target.closest('.tcard'); if (!card) return;
    if (e.target.matches('.t-code')) e.target.value = e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2);
    readType(card);
    $('.code-chip', card).textContent = TYPES.find(x => x.id === card.dataset.id).code || '??';
    $('.t-name', card).textContent = $('.t-label', card).value.trim() || 'New type of client';
    refreshUsedBy();
  });
  $('#types').addEventListener('change', e => {
    const card = e.target.closest('.tcard'); if (!card) return;
    readType(card);
    if (e.target.matches('.t-segbox, .t-svcbox, .t-cur')) renderTypeSegs(card);
    refreshUsedBy();
  });
  $('#types').addEventListener('click', e => {
    if (!e.target.matches('.del-type')) return;
    const card = e.target.closest('.tcard');
    if (TYPES.length <= 1) { alert('Keep at least one type of client.'); return; }
    const t = readType(card);
    if (!confirm(`Delete the type of client “${t.label || 'new'}”? Existing proposals are not affected.`)) return;
    TYPES = TYPES.filter(x => x.id !== t.id); card.remove(); refreshUsedBy(); setDirty(true);
  });
  $('#addType').onclick = () => {
    $$('.tcard').forEach(readType);
    TYPES.push({ id: newId(), label: '', code: '', proposal_title: '', default_currency: CAT.currencies[0], segments: [], excluded: {}, _open: true });
    renderTypes(); setDirty(true);
    const c = $$('.tcard').at(-1); $('.t-label', c).focus(); c.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  const unitChip = u => `<span class="chip" data-unit="${esc(u)}">${esc(u)}<button type="button" class="chip-x" title="Remove unit">×</button></span>`;
  const units = () => $$('#units .chip').map(c => c.dataset.unit);

  function unitSelect(sel) {
    const list = units();
    const opts = (sel && !list.includes(sel) ? [sel, ...list] : list);
    return `<select class="r-unit"><option value="">– unit –</option>${opts.map(u => `<option${u === sel ? ' selected' : ''}>${esc(u)}</option>`).join('')}</select>`;
  }

  function rowHtml(r) {
    const move = `<span class="mv"><button type="button" class="up" title="Move up">↑</button><button type="button" class="down" title="Move down">↓</button></span>`;
    if (r.type === 'subheader') {
      return `<div class="arow sub" data-type="subheader">${move}
        <span class="kind">Sub-heading</span>
        <input class="r-text" value="${esc(r.text)}" placeholder="Sub-heading text">
        <input class="r-note" value="${esc(r.note || '')}" placeholder="Note in fee column (optional)">
        <button type="button" class="del" title="Remove">×</button></div>`;
    }
    const fees = r.fees || {};
    return `<div class="arow" data-type="service" data-id="${esc(r.id || newId())}">${move}
      <span class="kind">Service</span>
      <textarea class="r-desc" rows="${Math.max(1, (r.description || []).length)}" placeholder="Description – one bullet per line">${esc((r.description || []).join('\n'))}</textarea>
      <div class="r-fees">
        ${unitSelect(r.unit)}
        ${CAT.currencies.map(c => `<label class="r-fee"><span>${c}</span><input data-cur="${c}" inputmode="decimal" value="${fees[c] ?? ''}"></label>`).join('')}
      </div>
      <button type="button" class="del" title="Remove service">×</button></div>`;
  }

  function segHtml(s) {
    return `<details class="seg" data-id="${esc(s.id || newId())}" ${s._open ? 'open' : ''}>
      <summary><span class="seg-name">${esc(s.name || 'New segment')}</span>
        <small class="seg-meta"></small>
        <span class="mv"><button type="button" class="seg-up" title="Move segment up">↑</button><button type="button" class="seg-down" title="Move segment down">↓</button></span>
      </summary>
      <div class="seg-body">
        <div class="seg-fields">
          <label>Segment name (table heading)<input class="s-name" value="${esc(s.name)}" required></label>
          <label>Section (slide sub-title / HTML sub-section)<input class="s-section" list="sections" value="${esc(s.section)}"></label>
          <label>Fee column heading<input class="s-feeheader" value="${esc(s.fee_header || 'Cost')}"></label>
          <label>Footnotes<select class="s-footnotes">${Object.entries(FOOTNOTES).map(([k, v]) => `<option value="${k}"${k === (s.footnotes || 'default') ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
          <div class="s-default"><span><b>Used by:</b> <span class="s-usedby"></span> <small>(set under Types of client)</small></span>
            <label><input type="checkbox" class="s-bullets" ${s.bullets !== false ? 'checked' : ''}> show descriptions as bullets</label>
          </div>
        </div>
        <div class="arows">${s.rows.map(rowHtml).join('')}</div>
        <div class="gfoot">
          <button type="button" class="small-btn add-svc">+ Add service</button>
          <button type="button" class="small-btn add-sub">+ Add sub-heading</button>
          <button type="button" class="small-btn danger del-seg">Delete segment</button>
        </div>
      </div></details>`;
  }

  function refreshDerived() {
    const secs = [...new Set($$('.s-section').map(i => i.value.trim()).filter(Boolean))];
    $('#sections').innerHTML = secs.map(s => `<option value="${esc(s)}">`).join('');
    $('#jump').innerHTML = $$('.seg').map((d, i) => `<a href="#" data-i="${i}">${esc($('.s-name', d).value || 'New segment')}</a>`).join('');
  }

  // ---------- serialise
  function serialise() {
    $$('.tcard').forEach(readType);
    const live = new Set($$('.seg').map(d => d.dataset.id));
    return {
      units: units(),
      client_types: TYPES.map(t => ({ id: t.id, label: t.label, code: t.code, proposal_title: t.proposal_title,
        default_currency: t.default_currency, segments: t.segments.filter(id => live.has(id)),
        excluded: Object.fromEntries(Object.entries(t.excluded).filter(([id]) => live.has(id) && t.segments.includes(id))) })),
      segments: $$('.seg').map(d => ({
        id: d.dataset.id, name: $('.s-name', d).value, section: $('.s-section', d).value,
        fee_header: $('.s-feeheader', d).value, footnotes: $('.s-footnotes', d).value,
        bullets: $('.s-bullets', d).checked,
        rows: $$('.arow', d).map(r => r.dataset.type === 'subheader'
          ? { type: 'subheader', text: $('.r-text', r).value, note: $('.r-note', r).value }
          : { type: 'service', id: r.dataset.id, description: $('.r-desc', r).value.split('\n'), unit: $('.r-unit', r).value,
              fees: Object.fromEntries($$('.r-fee input', r).map(i => [i.dataset.cur, i.value.replace(/,/g, '').trim()])) }),
      })),
    };
  }

  // ---------- state
  function setDirty(v) {
    dirty = v;
    $('#save').disabled = $('#discard').disabled = !v;
    const st = $('#status');
    st.className = 'status' + (v ? ' dirty' : '');
    st.textContent = v ? 'Unsaved changes' : 'All changes saved';
  }
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('input', e => {
    if (e.target.closest('main')) setDirty(true);
    if (e.target.matches('.s-name')) { $('.seg-name', e.target.closest('.seg')).textContent = e.target.value || 'New segment'; refreshDerived(); refreshTypesSoon(); }
    if (e.target.matches('.s-section')) { refreshDerived(); refreshTypesSoon(); }
    if (e.target.matches('.r-desc')) refreshTypesSoon();
    if (e.target.matches('.r-desc')) e.target.rows = Math.max(1, e.target.value.split('\n').length);
  });
  document.addEventListener('change', e => {
    if (e.target.closest('main') && !e.target.matches('#history')) setDirty(true);
    if (e.target.matches('.r-unit')) $$('.r-fee input', e.target.closest('.arow')).forEach(i => i.disabled = e.target.value === 'Included');
  });

  document.addEventListener('click', e => {
    if (e.target.closest('#segments') && e.target.matches('button')) refreshTypesSoon();
    const t = e.target, seg = t.closest('.seg'), row = t.closest('.arow');
    const move = (el, dir) => { const sib = dir < 0 ? el.previousElementSibling : el.nextElementSibling; if (sib) dir < 0 ? sib.before(el) : sib.after(el); setDirty(true); };
    if (t.matches('.up')) move(row, -1);
    else if (t.matches('.down')) move(row, 1);
    else if (t.matches('.seg-up, .seg-down')) { e.preventDefault(); move(seg, t.matches('.seg-up') ? -1 : 1); refreshDerived(); }
    else if (t.matches('.arow .del')) {
      const d = row.dataset.type === 'subheader' ? $('.r-text', row).value : $('.r-desc', row).value.split('\n')[0];
      if (!d || confirm(`Remove “${d}”?`)) { row.remove(); setDirty(true); }
    }
    else if (t.matches('.add-svc')) {
      $('.arows', seg).insertAdjacentHTML('beforeend', rowHtml({ type: 'service', unit: '', description: [], fees: {} }));
      $('.arows .arow:last-child .r-desc', seg).focus(); setDirty(true);
    }
    else if (t.matches('.add-sub')) {
      $('.arows', seg).insertAdjacentHTML('beforeend', rowHtml({ type: 'subheader', text: '' }));
      $('.arows .arow:last-child .r-text', seg).focus(); setDirty(true);
    }
    else if (t.matches('.del-seg')) {
      if (confirm(`Delete the segment “${$('.s-name', seg).value}” and all its services?`)) { seg.remove(); refreshDerived(); setDirty(true); }
    }
    else if (t.matches('.chip-x')) {
      const u = t.parentElement.dataset.unit;
      const used = $$('.r-unit').filter(s => s.value === u).length;
      if (used) { alert(`“${u}” is used by ${used} service(s). Change their unit first.`); return; }
      t.parentElement.remove(); updateUnitSelects(); setDirty(true);
    }
    else if (t.matches('#jump a')) {
      e.preventDefault();
      const d = $$('.seg')[+t.dataset.i]; d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  function updateUnitSelects() {
    $$('.r-unit').forEach(s => { const v = s.value; s.outerHTML = unitSelect(v); });
  }
  $('#addUnit').onclick = () => {
    const v = $('#newUnit').value.trim();
    if (!v) return;
    if (units().some(u => u.toLowerCase() === v.toLowerCase())) { alert('That unit already exists.'); return; }
    $('#units').insertAdjacentHTML('beforeend', unitChip(v));
    $('#newUnit').value = ''; updateUnitSelects(); setDirty(true);
  };
  $('#newUnit').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('#addUnit').click(); } });

  $('#addSegment').onclick = () => {
    $('#segments').insertAdjacentHTML('beforeend', segHtml({ name: '', section: '', footnotes: 'default', bullets: true, rows: [], _open: true }));
    const d = $$('.seg').at(-1); $('.s-name', d).focus(); d.scrollIntoView({ behavior: 'smooth' });
    refreshDerived(); refreshTypesSoon(); setDirty(true);
  };

  // ---------- save / discard / history
  $('#save').onclick = async () => {
    const st = $('#status'); st.className = 'status'; st.textContent = 'Saving…';
    const open = new Set($$('.seg[open]').map(d => $('.s-name', d).value));
    const openTypes = new Set($$('.tcard[open]').map(c => $('.t-label', c).value.trim()));
    const r = await fetch(BASE + '/api/admin/catalog', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(serialise()) });
    const j = await readJson(r);
    if (!r.ok) { st.className = 'status err'; st.textContent = j.error || 'Could not save'; return; }
    CAT = j; CAT.segments.forEach(s => s._open = open.has(s.name));
    render(new Set(Object.entries(CAT.client_types).filter(([, t]) => openTypes.has(t.label)).map(([id]) => id)));
    setDirty(false); loadHistory();
  };
  $('#discard').onclick = () => { if (confirm('Discard all unsaved changes?')) load(); };

  async function loadHistory() {
    const list = await readJson(await fetch(BASE + '/api/admin/history'));
    const label = n => { const m = n.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/); return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : n; };
    $('#history').innerHTML = `<option value="">${list.length ? 'choose…' : 'no saved versions yet'}</option>` + list.map(n => `<option value="${esc(n)}">${label(n)}</option>`).join('');
  }
  $('#history').addEventListener('change', async e => {
    const name = e.target.value; if (!name) return;
    if (!confirm(`Replace the current list of services with the version saved on ${e.target.selectedOptions[0].text}? (The current list is kept in the history.)`)) { e.target.value = ''; return; }
    const r = await fetch(BASE + '/api/admin/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    const j = await readJson(r);
    if (!r.ok) { alert(j.error); return; }
    CAT = j; render(); setDirty(false); loadHistory();
  });

  load();
})();
