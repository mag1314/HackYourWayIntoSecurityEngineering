// ==UserScript==
// @name         secjobs - fill Lever application
// @namespace    secjobs.local
// @version      1.0
// @description  Fills a jobs.lever.co application from your local secjobs server. You still review and click Submit.
// @match        https://jobs.lever.co/*/*/apply*
// @match        https://jobs.lever.co/*/*/thanks*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';
  const API = 'http://127.0.0.1:8765';

  // ---------- tiny UI ----------
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:999999;background:#111;color:#eee;' +
    'font:13px/1.4 system-ui,sans-serif;padding:12px 14px;border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,.4);max-width:360px';
  box.innerHTML = '<div style="font-weight:600;margin-bottom:6px">secjobs</div><div id="sj-msg">connecting…</div>' +
    '<div style="margin-top:8px"><button id="sj-fill" style="padding:6px 10px;border:0;border-radius:6px;background:#3b82f6;color:#fff;cursor:pointer">Fill from secjobs</button> ' +
    '<button id="sj-done" style="padding:6px 10px;border:0;border-radius:6px;background:#22c55e;color:#fff;cursor:pointer;display:none">Mark applied</button></div>';
  document.body.appendChild(box);
  const msg = (t, color) => { const m = box.querySelector('#sj-msg'); m.innerHTML = t; m.style.color = color || '#eee'; };

  const gm = (method, path, data) => new Promise((res, rej) => GM_xmlhttpRequest({
    method, url: API + path, data: data ? JSON.stringify(data) : undefined,
    headers: { 'Content-Type': 'application/json' }, timeout: 20000,
    onload: r => { try { res(JSON.parse(r.responseText)); } catch (e) { rej(e); } },
    onerror: rej, ontimeout: rej,
  }));

  // ---------- thank-you page: report success ----------
  if (location.pathname.endsWith('/thanks')) {
    const pid = sessionStorage.getItem('sj_pid');
    if (pid) gm('POST', '/applied', { posting_id: pid }).then(() => msg('✓ recorded as applied', '#86efac'))
      .catch(() => msg('submitted, but could not reach secjobs serve to record it', '#fbbf24'));
    else msg('submitted (no secjobs record for this page)');
    box.querySelector('#sj-fill').style.display = 'none';
    return;
  }

  // ---------- helpers ----------
  const setVal = (el, v) => {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, v);
    ['input', 'change', 'blur'].forEach(t => el.dispatchEvent(new Event(t, { bubbles: true })));
    return true;
  };
  const tick = el => { if (!el) return false; el.checked = true; ['input', 'change', 'click'].forEach(t => el.dispatchEvent(new Event(t, { bubbles: true }))); return el.checked; };
  const selectByText = (sel, wanted) => {
    if (!sel || !wanted) return false;
    const w = wanted.toLowerCase(), opts = [...sel.options];
    let o = opts.find(x => x.text.trim().toLowerCase() === w) ||
      opts.find(x => w.split(/[^a-z]+/).filter(Boolean).every(t => x.text.toLowerCase().includes(t))) ||
      opts.find(x => x.text.toLowerCase().includes(w.split(' ')[0]));
    if (!o) return false;
    sel.value = o.value; sel.dispatchEvent(new Event('change', { bubbles: true })); return true;
  };
  const labelOf = el => (el.closest('label')?.innerText || (el.id && document.querySelector(`label[for="${el.id}"]`)?.innerText) || el.value || '').trim();
  const matchAnswer = (label, answers) => {
    const l = label.toLowerCase();
    for (const a of answers) if ((a.match || []).some(m => l.includes(String(m).toLowerCase()))) return String(a.answer);
    return null;
  };
  const STANDARD = ['full name', 'email', 'phone', 'current company', 'current location', 'resume', 'cv', 'additional information', 'linkedin', 'github', 'portfolio', 'twitter', 'other website', 'cover letter'];

  const answerQuestion = (q, ans) => {
    if (!ans) return false;
    const a = ans.toLowerCase();
    const sel = q.querySelector('select');
    if (sel) {
      const o = [...sel.options].find(x => x.text.trim().toLowerCase() === a) || [...sel.options].find(x => x.text.trim() && x.text.toLowerCase().includes(a));
      if (!o) return false; sel.value = o.value; sel.dispatchEvent(new Event('change', { bubbles: true })); return true;
    }
    for (const kind of ['radio', 'checkbox']) {
      const inputs = [...q.querySelectorAll(`input[type=${kind}]`)];
      if (!inputs.length) continue;
      if (kind === 'checkbox' && inputs.length === 1 && ['yes', 'y', 'true', 'agree', 'i agree', 'acknowledge', 'confirm'].includes(a)) return tick(inputs[0]);
      const c = inputs.map(el => ({ el, t: labelOf(el).toLowerCase(), v: (el.value || '').toLowerCase() }));
      const hit = c.find(x => x.t === a || x.v === a) || c.find(x => x.t.startsWith(a) || x.v.startsWith(a)) || c.find(x => x.t.includes(a) || x.v.includes(a));
      return hit ? tick(hit.el) : false;
    }
    const ta = q.querySelector('textarea'); if (ta) return setVal(ta, ans);
    const inp = q.querySelector('input[type=text],input[type=url],input[type=tel],input:not([type])'); if (inp) return setVal(inp, ans);
    return false;
  };

  const b64ToFile = (b64, name) => {
    const bin = atob(b64), arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new File([arr], name, { type: 'application/pdf' });
  };

  // ---------- main fill ----------
  async function fill() {
    msg('fetching from secjobs…');
    let job;
    try { job = await gm('GET', '/job?url=' + encodeURIComponent(location.href)); }
    catch (e) { return msg('cannot reach secjobs. Run <code>secjobs serve</code> in PowerShell.', '#f87171'); }
    if (!job.known) return msg('this posting is not in the secjobs ledger (run scan/generate first). Filling contact fields only.', '#fbbf24');
    if (!job.generated) return msg('no tailored resume for this posting yet. Run <code>secjobs generate</code>.', '#fbbf24');
    if (job.status === 'applied') return msg('⚠ ledger says you already applied to this one.', '#fbbf24');
    sessionStorage.setItem('sj_pid', job.posting_id);

    const c = job.candidate, F = document.querySelector('form') || document;
    const q = s => F.querySelector(s);

    // resume first (Lever parses it and may overwrite name/email)
    const resume = q('input[name="resume"]');
    if (resume) {
      const dt = new DataTransfer(); dt.items.add(b64ToFile(job.resume_b64, job.resume_name));
      resume.files = dt.files; resume.dispatchEvent(new Event('change', { bubbles: true }));
      await new Promise(r => setTimeout(r, 2500));
    }
    setVal(q('input[name="name"]'), c.full_name);
    setVal(q('input[name="email"]'), c.email);
    setVal(q('input[name="phone"]'), c.phone);
    setVal(q('input[name="urls[LinkedIn]"]'), c.linkedin);
    const loc = q('input[name="location"]');
    if (loc) { setVal(loc, c.location); await new Promise(r => setTimeout(r, 1200)); const s = document.querySelector('.dropdown-location .dropdown-item, [class*=dropdown] li'); if (s) s.click(); }
    setVal(q('textarea[name="comments"]'), job.cover_letter);

    selectByText(q('select[name="eeo[gender]"]'), job.eeo.gender);
    selectByText(q('select[name="eeo[race]"]'), job.eeo.race);
    selectByText(q('select[name="eeo[veteran]"]'), job.eeo.veteran);
    selectByText(q('select[name="eeo[disability]"]'), job.eeo.disability);

    const unanswered = [];
    for (const block of document.querySelectorAll('.application-question')) {
      const lbl = block.querySelector('.application-label, label');
      if (!lbl) continue;
      const raw = lbl.innerText.replace(/[✱*]/g, '').trim();
      const first = raw.split('\n')[0].trim();
      const required = /✱|\*/.test(lbl.innerText) || !!block.querySelector('[required]');
      if (block.querySelector('input[type=file]')) continue;
      if (STANDARD.some(k => first.toLowerCase().startsWith(k))) continue;
      const ans = matchAnswer(first, job.answers);
      let ok = false; try { ok = answerQuestion(block, ans); } catch (e) {}
      if (required && !ok) unanswered.push(first);
    }

    box.querySelector('#sj-done').style.display = 'inline-block';
    const flags = (job.flags || []).length ? `<div style="margin-top:6px;color:#fbbf24">⚠ resume review flags: ${job.flags.join(', ')}</div>` : '';
    if (unanswered.length) {
      gm('POST', '/needs_input', { posting_id: job.posting_id, unanswered }).catch(() => {});
      msg(`filled. <b style="color:#fbbf24">${unanswered.length} required question(s) need you:</b><ul style="margin:4px 0 0 16px;padding:0">${unanswered.map(u => `<li>${u.slice(0, 90)}</li>`).join('')}</ul>${flags}<div style="margin-top:6px">Answer them, review, then click Lever's Submit.</div>`);
    } else {
      msg(`filled — review the form, then click Lever's <b>Submit</b>.${flags}`);
    }
  }

  box.querySelector('#sj-fill').onclick = fill;
  box.querySelector('#sj-done').onclick = async () => {
    const pid = sessionStorage.getItem('sj_pid'); if (!pid) return;
    try { await gm('POST', '/applied', { posting_id: pid }); msg('✓ recorded as applied', '#86efac'); } catch (e) { msg('could not reach secjobs serve', '#f87171'); }
  };
  gm('GET', '/ping').then(() => msg('ready')).catch(() => msg('secjobs serve is not running', '#f87171'));
})();
