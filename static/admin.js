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

  async function load() {
    CAT = await readJson(await fetch(BASE + '/api/catalog'));
    render();
    setDirty(false);
    loadHistory();
  }

  // ---------- render
  function render() {
    $('#units').innerHTML = CAT.units.map(unitChip).join('');
    $('#segments').innerHTML = CAT.segments.map(segHtml).join('');
    refreshDerived();
  }
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
    return `<div class="arow" data-type="service" data-id="${esc(r.id || '')}">${move}
      <span class="kind">Service</span>
      <textarea class="r-desc" rows="${Math.max(1, (r.description || []).length)}" placeholder="Description – one bullet per line">${esc((r.description || []).join('\n'))}</textarea>
      <div class="r-fees">
        ${unitSelect(r.unit)}
        ${CAT.currencies.map(c => `<label class="r-fee"><span>${c}</span><input data-cur="${c}" inputmode="decimal" value="${fees[c] ?? ''}"></label>`).join('')}
        <label class="r-sel"><input type="checkbox" class="r-selected" ${r.selected !== false ? 'checked' : ''}> pre-selected</label>
      </div>
      <button type="button" class="del" title="Remove service">×</button></div>`;
  }

  function segHtml(s) {
    const cts = Object.entries(CAT.client_types);
    const nServices = s.rows.filter(r => r.type !== 'subheader').length;
    return `<details class="seg" data-id="${esc(s.id || '')}" ${s._open ? 'open' : ''}>
      <summary><span class="seg-name">${esc(s.name || 'New segment')}</span>
        <small class="seg-meta">${esc(s.section || '')} · ${nServices} services · default for: ${(s.default_for || []).map(id => esc(CAT.client_types[id]?.label || id)).join(', ') || 'none'}</small>
        <span class="mv"><button type="button" class="seg-up" title="Move segment up">↑</button><button type="button" class="seg-down" title="Move segment down">↓</button></span>
      </summary>
      <div class="seg-body">
        <div class="seg-fields">
          <label>Segment name (table heading)<input class="s-name" value="${esc(s.name)}" required></label>
          <label>Section (slide sub-title / HTML sub-section)<input class="s-section" list="sections" value="${esc(s.section)}"></label>
          <label>Fee column heading<input class="s-feeheader" value="${esc(s.fee_header || 'Cost')}"></label>
          <label>Footnotes<select class="s-footnotes">${Object.entries(FOOTNOTES).map(([k, v]) => `<option value="${k}"${k === (s.footnotes || 'default') ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
          <div class="s-default"><b>Switched on by default for</b>
            ${cts.map(([id, t]) => `<label><input type="checkbox" class="s-ct" value="${id}" ${(s.default_for || []).includes(id) ? 'checked' : ''}> ${esc(t.label)}</label>`).join('')}
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
    return {
      units: units(),
      segments: $$('.seg').map(d => ({
        id: d.dataset.id, name: $('.s-name', d).value, section: $('.s-section', d).value,
        fee_header: $('.s-feeheader', d).value, footnotes: $('.s-footnotes', d).value,
        bullets: $('.s-bullets', d).checked, default_for: $$('.s-ct:checked', d).map(c => c.value),
        rows: $$('.arow', d).map(r => r.dataset.type === 'subheader'
          ? { type: 'subheader', text: $('.r-text', r).value, note: $('.r-note', r).value }
          : { type: 'service', id: r.dataset.id, description: $('.r-desc', r).value.split('\n'), unit: $('.r-unit', r).value,
              selected: $('.r-selected', r).checked,
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
    if (e.target.matches('.s-name')) { $('.seg-name', e.target.closest('.seg')).textContent = e.target.value || 'New segment'; refreshDerived(); }
    if (e.target.matches('.s-section')) refreshDerived();
    if (e.target.matches('.r-desc')) e.target.rows = Math.max(1, e.target.value.split('\n').length);
  });
  document.addEventListener('change', e => {
    if (e.target.closest('main') && !e.target.matches('#history')) setDirty(true);
    if (e.target.matches('.r-unit')) $$('.r-fee input', e.target.closest('.arow')).forEach(i => i.disabled = e.target.value === 'Included');
  });

  document.addEventListener('click', e => {
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
      $('.arows', seg).insertAdjacentHTML('beforeend', rowHtml({ type: 'service', unit: '', description: [], fees: {}, selected: true }));
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
    $('#segments').insertAdjacentHTML('beforeend', segHtml({ name: '', section: '', default_for: [], footnotes: 'default', bullets: true, rows: [], _open: true }));
    const d = $$('.seg').at(-1); $('.s-name', d).focus(); d.scrollIntoView({ behavior: 'smooth' });
    refreshDerived(); setDirty(true);
  };

  // ---------- save / discard / history
  $('#save').onclick = async () => {
    const st = $('#status'); st.className = 'status'; st.textContent = 'Saving…';
    const open = new Set($$('.seg[open]').map(d => $('.s-name', d).value));
    const r = await fetch(BASE + '/api/admin/catalog', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(serialise()) });
    const j = await readJson(r);
    if (!r.ok) { st.className = 'status err'; st.textContent = j.error || 'Could not save'; return; }
    CAT = j; CAT.segments.forEach(s => s._open = open.has(s.name));
    render(); setDirty(false); loadHistory();
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
