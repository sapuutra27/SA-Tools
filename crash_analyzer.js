(function (g) {
  const LBL = {
    id: { error: 'Kesalahan', info: 'Info', problem: 'Masalah', solution: 'Solusi', warn: 'Peringatan', main: 'Kemungkinan utama', other: 'Kemungkinan lain', bad: 'Format crashlog tidak dikenali. Pastikan file berasal dari AML (aml_crashlog.txt).' },
    en: { error: 'Error', info: 'Info', problem: 'Problem', solution: 'Solution', warn: 'Warning', main: 'Most likely', other: 'Also possible', bad: 'Unrecognized crashlog format. Make sure the file comes from AML (aml_crashlog.txt).' }
  };

  const S = {
    id: {
      warnH: 'Hasil ini perkiraan berdasarkan pola crash (heuristik), bukan kepastian. Gunakan sebagai petunjuk arah pencarian.',
      loc: 'Lokasi crash: ', chain: 'Rantai pemanggil: ', fault: 'Alamat error: ',
      modsChain: 'Mod pada rantai pemanggil (bisa hanya hook, belum tentu pelaku): ',
      regs: 'Register berisi alamat di: ',
      x7: ' = 0x7F7F7F7F7F7F7F7F adalah sisa operasi string (strlen atau strchr), biasanya bukan penyebab',
      files: 'File data yang terlihat di stack, kemungkinan sedang dimuat saat crash: ',
      strs: 'Teks yang terlihat di stack (sering nama model atau file yang sedang diproses): ',
      evH: ' Bukti: ', devH: ' Perangkat: ', modsWord: ' mod', sdk: 'Android SDK ',
      limits: 'Beberapa limit adjuster aktif bersamaan (', limits2: '). Bila batas yang sama diubah oleh lebih dari satu mod, hasilnya bisa saling menimpa.',
      many: 'Banyak mod aktif (', many2: '). Semakin banyak mod, semakin besar peluang konflik dan kehabisan batas.',
      rel: 'Mod terkait yang terpasang: ',
      fNull: ': alamat sangat kecil, kemungkinan pointer null dengan offset anggota ',
      fNeg: ': kemungkinan indeks atau nilai -1 dipakai sebagai alamat',
      fPat: ': pola khas memori tidak diinisialisasi atau sudah dibebaskan',
      fProt: ': area memori dilindungi (hanya baca)',
      fWild: ': alamat tidak dipetakan atau pointer rusak'
    },
    en: {
      warnH: 'This result is an estimate based on crash patterns (heuristics), not a certainty. Use it as a hint for where to look.',
      loc: 'Crash location: ', chain: 'Call chain: ', fault: 'Fault address: ',
      modsChain: 'Mods in the call chain (may only be hooks, not necessarily the culprit): ',
      regs: 'Registers contain addresses in: ',
      x7: ' = 0x7F7F7F7F7F7F7F7F is a leftover of string operations (strlen or strchr) and is usually not the cause',
      files: 'Data files visible on the stack, probably being loaded when the crash happened: ',
      strs: 'Text visible on the stack (often the model or file being processed): ',
      evH: ' Evidence: ', devH: ' Device: ', modsWord: ' mods', sdk: 'Android SDK ',
      limits: 'Several limit adjusters are active at the same time (', limits2: '). If more than one mod changes the same limit, they may overwrite each other.',
      many: 'Many mods are active (', many2: '). The more mods, the higher the chance of conflicts and exhausted limits.',
      rel: 'Related installed mods: ',
      fNull: ': very small address, probably a null pointer with member offset ',
      fNeg: ': probably an index or value of -1 used as an address',
      fPat: ': typical pattern of uninitialized or freed memory',
      fProt: ': protected (read-only) memory area',
      fWild: ': unmapped address or corrupted pointer'
    }
  };

  const SYS = /^(libGTASA|libc\.so|libc\+\+|libm\.so|libdl|libandroid|libart|libEGL|libGLES|libmali|libAML|liblog|libbinder|libutils|libstdc|libplugin_fastman92|boot|app_process|\[vdso)/;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function shortFn(f) {
    if (f.func) return f.func.replace(/\(.*$/, '');
    return f.lib + '+0x' + f.pc.toUpperCase();
  }

  function resolve(lib, off) {
    if (!/libGTASA/.test(lib || '') || !off) return '';
    const n = parseInt(off, 16);
    let best = null;
    g.CRASH_KB.offsets.forEach(function (o) {
      if (o[0] <= n && n < o[0] + 0x800 && (!best || o[0] > best[0])) best = o;
    });
    return best ? best[1] : '';
  }

  function faultClass(p) {
    const h = p.faultHex.toUpperCase().replace(/^0X/, '');
    if (!h) return 'wild';
    if (parseInt(h, 16) < 0x1000) return 'null';
    if (/^F{8,}/.test(h)) return 'neg';
    if (/DEADBEEF|BAADF00D|CDCDCDCD|FEEEFEEE|ABABABAB|7F7F7F7F|5A5A5A5A|DDDDDDDD/.test(h)) return 'pattern';
    if (p.signalCode === 'SEGV_ACCERR') return 'prot';
    return 'wild';
  }

  function faultText(p, cls, T) {
    const h = p.faultHex;
    if (cls === 'null') return h + T.fNull + h;
    if (cls === 'neg') return h + T.fNeg;
    if (cls === 'pattern') return h + T.fPat;
    if (cls === 'prot') return h + T.fProt;
    return h + T.fWild;
  }

  function buildCtx(p) {
    const frames = p.crashFrames.map(function (f) {
      const isMod = !SYS.test(f.lib) && (p.mods.some(function (m) { return m.lib === f.lib; }) || /\/files\/lib|\/mods\//.test(f.path) || f.deleted);
      return Object.assign({}, f, { isMod: isMod });
    });
    const funcs = frames.map(function (f) { return f.func || ''; });
    let top = funcs[0] || p.crashFunc || resolve(p.crashLib, p.crashOff) || '';
    if (!funcs.length && top) funcs.push(top);
    else if (!funcs[0] && top) funcs[0] = top;
    const libs = frames.length ? frames.map(function (f) { return f.lib; }) : [p.crashLib];
    return { p: p, frames: frames, funcs: funcs, libs: libs, top: top, faultClass: faultClass(p) };
  }

  function evaluate(rule, c) {
    let s = 0;
    let hit = '';
    if (rule.fn) {
      const i = c.funcs.findIndex(function (f) { return f && rule.fn.test(f); });
      if (i >= 0) {
        const v = rule.base * (1 - 0.07 * Math.min(i, 8));
        if (v > s) { s = v; hit = c.funcs[i]; }
      }
    }
    if (rule.lib) {
      const i = c.libs.slice(0, 4).findIndex(function (l) { return rule.lib.test(l); });
      if (i >= 0) {
        const v = rule.base * (1 - 0.1 * i);
        if (v > s) { s = v; hit = c.libs[i]; }
      }
    }
    if (rule.sig && rule.sig.test(c.p.signalName) && rule.base * 0.8 > s) s = rule.base * 0.8;
    if (rule.when) {
      const w = rule.when(c);
      if (w && w.score > s) { s = w.score; hit = w.hit || hit; }
    }
    if (s <= 0) return null;
    let ev = [];
    if (rule.extra) {
      const x = rule.extra(c);
      s += x.bonus || 0;
      ev = x.ev || [];
    }
    return { rule: rule, score: Math.min(0.96, s), hit: hit, ev: ev };
  }

  function relatedMods(rule, c) {
    if (!rule.mods) return [];
    return c.p.mods.filter(function (m) { return rule.mods.test(m.name + ' ' + m.lib); }).map(function (m) { return m.name + (m.version ? ' v' + m.version : ''); });
  }

  function analyze(text, lang) {
    const en = /^en/i.test(lang || '');
    const L = en ? LBL.en : LBL.id;
    const T = en ? S.en : S.id;
    const KE = en && g.CRASH_KB_EN ? g.CRASH_KB_EN : null;
    const tr = function (r) {
      const t = KE && (r.id === 'fault' ? KE.fault[r.fid] : KE.rules[r.id]);
      return t ? { title: t.title, c: t.c, f: t.f } : r;
    };
    const p = g.CrashParser.parse(text);
    if (!p.valid) return [L.error + ': ' + L.bad];
    const c = buildCtx(p);
    c.en = en;
    const out = [];

    let where = p.crashLib + ' + ' + p.crashOff;
    if (c.top) where += ' (' + c.top + ')';
    out.push(L.error + ': ' + p.signalName + ' (' + p.signalCode + ') ' + where);

    out.push(L.warn + ': ' + T.warnH);

    let results = g.CRASH_KB.rules.map(function (r) { return evaluate(r, c); }).filter(Boolean);
    const fb = g.CRASH_KB.fault[c.faultClass];
    results.push({ rule: { id: 'fault', fid: c.faultClass, title: fb.title, c: fb.c, f: fb.f }, score: fb.s, hit: '', ev: [] });
    results.sort(function (a, b) { return b.score - a.score; });
    results = results.filter(function (r, i) { return i < 3 && (i === 0 || r.score >= 0.3); });

    const ev = [];
    ev.push(T.loc + where);
    if (c.frames.length) ev.push(T.chain + c.frames.slice(0, 8).map(shortFn).join(' ← '));
    if (p.faultHex) ev.push(T.fault + faultText(p, c.faultClass, T));
    const modFrames = c.frames.filter(function (f) { return f.isMod; }).map(function (f) { return f.lib; });
    if (modFrames.length) ev.push(T.modsChain + modFrames.filter(function (v, i, a) { return a.indexOf(v) === i; }).join(', '));
    const regLibs = [];
    Object.keys(p.regs).forEach(function (k) {
      const l = p.regs[k].lib;
      if (l && !SYS.test(l) && regLibs.indexOf(l) < 0) regLibs.push(l);
    });
    if (regLibs.length) ev.push(T.regs + regLibs.join(', '));
    const x7 = Object.keys(p.regs).filter(function (k) { return /^0x7F7F7F7F7F7F7F7F$/i.test(p.regs[k].hex); });
    if (x7.length) ev.push(x7.join(', ') + T.x7);
    results.forEach(function (r) { r.ev.forEach(function (e) { if (ev.indexOf(e) < 0) ev.push(e); }); });
    if (results.some(function (r) { return r.rule.strings; }) && p.stackStrings.length) {
      ev.push(T.strs + p.stackStrings.slice(0, 8).join(', '));
    }
    const files = p.stackStrings.filter(function (s) { return /\.(ide|ipl|dat|img|txd|dff|col|ifp|scm|gxt|cfg)$/i.test(s); });
    if (files.length) ev.push(T.files + files.join(', '));
    out.push(L.info + T.evH + ev.map(esc).join('\n• ').replace(/^/, '• '));

    const dev = [(p.device.brand + ' ' + p.device.model).trim(), p.device.sdk ? T.sdk + p.device.sdk : '', p.mods.length + T.modsWord].filter(Boolean).join(' · ');
    out.push(L.info + T.devH + esc(dev));

    const limits = p.mods.filter(function (m) { return /limit.?adjust/i.test(m.name + m.lib); }).map(function (m) { return m.name; });
    const f92 = p.handlerFrames.some(function (f) { return /fastman92/i.test(f.lib); });
    if (limits.length + (f92 ? 1 : 0) >= 2) {
      out.push(L.warn + ': ' + T.limits + esc(limits.concat(f92 ? ['fastman92 limit adjuster'] : []).join(', ')) + T.limits2);
    }
    if (p.mods.length >= 30) out.push(L.warn + ': ' + T.many + p.mods.length + T.many2);

    results.forEach(function (r, i) {
      const mods = relatedMods(r.rule, c);
      const x = tr(r.rule);
      const head = (i === 0 ? L.main : L.other) + ' (±' + Math.round(r.score * 100) + '%): ' + x.title;
      out.push(L.problem + ': ' + esc(head) + '\n' + x.c.map(function (t) { return '• ' + esc(t); }).join('\n') + (mods.length ? '\n• ' + T.rel + esc(mods.join(', ')) : ''));
      out.push(L.solution + ': ' + x.f.map(function (t, k) { return (k + 1) + '. ' + esc(t); }).join('\n'));
    });
    return out;
  }

  function install() {
    const out = document.getElementById('output');
    if (!out) return;
    let busy = false;
    new MutationObserver(function () {
      if (busy) return;
      let nf = '';
      let log = '';
      try {
        nf = currentTexts.notFound;
        log = crashLogContent;
      } catch (e) { return; }
      if (!nf || !log || out.textContent !== nf) return;
      busy = true;
      try {
        renderCrashLines(analyze(log, navigator.language || ''));
        const ft = document.getElementById('footerNote');
        if (ft) ft.classList.remove('show');
      } catch (e) {
        console.error('Analisis crash gagal:', e);
      }
      busy = false;
    }).observe(out, { childList: true, characterData: true });
  }

  g.CrashAnalyzer = { analyze: analyze, install: install };
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
    else install();
  }
})(typeof window !== 'undefined' ? window : globalThis);
