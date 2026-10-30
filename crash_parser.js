(function (g) {
  function demangle(s) {
    if (!s || s.indexOf('_Z') !== 0) return s || '';
    let i = s[2] === 'N' ? 3 : 2;
    const parts = [];
    while (i < s.length) {
      const m = /^(\d+)/.exec(s.slice(i));
      if (!m) break;
      const n = parseInt(m[1], 10);
      i += m[1].length;
      parts.push(s.substr(i, n));
      i += n;
    }
    return parts.length ? parts.join('::') : s;
  }

  const FRAME = /^#(\d+) pc ([0-9a-fA-F]+)\s+(\S+)\s*(.*)$/;

  function parseFrame(l) {
    const m = FRAME.exec(l);
    if (!m) return null;
    let rest = m[4].replace(/^\(offset 0x[0-9a-fA-F]+\)\s*/, '').trim();
    let func = '';
    let plus = '';
    let deleted = false;
    if (rest === '(deleted)') {
      deleted = true;
    } else if (rest[0] === '(' && rest[rest.length - 1] === ')') {
      rest = rest.slice(1, -1);
      const p = /^(.*)\+(\d+)$/.exec(rest);
      func = p ? p[1] : rest;
      plus = p ? p[2] : '';
    }
    return {
      n: +m[1],
      pc: m[2].replace(/^0+/, '') || '0',
      path: m[3],
      lib: m[3].split('!')[0].split('/').pop(),
      func: func,
      plus: plus,
      deleted: deleted
    };
  }

  function stackStrings(lines) {
    const bytes = [];
    lines.forEach(function (l) {
      const m = /^\s*((?:[0-9A-F]{2} ){1,16})\(SP\+0x[0-9A-F]+\)/.exec(l);
      if (m) m[1].trim().split(' ').forEach(function (h) { bytes.push(parseInt(h, 16)); });
    });
    const out = [];
    let cur = '';
    const flush = function () {
      if (cur.length >= 5 && /[A-Za-z]{3}/.test(cur) && out.indexOf(cur) < 0) out.push(cur);
      cur = '';
    };
    bytes.forEach(function (b) {
      if (b >= 0x20 && b <= 0x7e) cur += String.fromCharCode(b);
      else flush();
    });
    flush();
    return out.slice(0, 12);
  }

  function parse(text) {
    const t = String(text || '').replace(/\r\n/g, '\n');
    const lines = t.split('\n');
    const p = {
      valid: false, signal: 0, signalName: '', signalCode: '', faultHex: '', pcHex: '',
      reasons: [], libBase: '', crashLib: '', crashOff: '', crashFunc: '',
      device: { sdk: 0, brand: '', model: '' }, regs: {}, mods: [], threads: [],
      crashThread: '', crashFrames: [], handlerFrames: [], stackStrings: []
    };
    let m = /Exception Signal (\d+) - (\w+) \((\w+)\)/.exec(t);
    if (m) {
      p.signal = +m[1];
      p.signalName = m[2];
      p.signalCode = m[3];
      p.valid = true;
    }
    m = /Fault address: (0x[0-9A-Fa-f]+) \(0x[0-9A-Fa-f]+\)(?: at (0x[0-9A-Fa-f]+))?/.exec(t);
    if (m) {
      p.faultHex = m[1];
      p.pcHex = m[2] || '';
    }
    const ri = lines.findIndex(function (l) { return /A POSSIBLE \(!\) reason/.test(l); });
    if (ri >= 0) {
      for (let i = ri + 1; i < lines.length && /^- /.test(lines[i]); i++) p.reasons.push(lines[i].slice(2));
    }
    const bi = lines.findIndex(function (l) { return /^Library base:/.test(l); });
    if (bi >= 0) {
      p.libBase = lines[bi].split(':')[1].trim();
      m = /^(\S+) \+ (0x[0-9A-Fa-f]+)(?: \((.*)\))?$/.exec(lines[bi + 1] || '');
      if (m) {
        p.crashLib = m[1];
        p.crashOff = m[2];
        p.crashFunc = demangle(m[3] || '');
      }
    }
    m = /Android SDK Version: (\d+)/.exec(t);
    p.device.sdk = m ? +m[1] : 0;
    m = /^Brand: (.*)$/m.exec(t);
    p.device.brand = m ? m[1].trim() : '';
    m = /^Device: (.*)$/m.exec(t);
    p.device.model = m ? m[1].trim() : '';

    const rr = /^(X\d+|SP|PC|CPSR):\t(-?\d+)\t(0x[0-9A-Fa-f]+)(?: \((\S+) \+ (0x[0-9A-Fa-f]+)\))?/gm;
    while ((m = rr.exec(t))) {
      p.regs[m[1]] = { dec: Number(m[2]), hex: m[3], lib: m[4] || '', off: m[5] || '' };
    }

    const mi = lines.findIndex(function (l) { return /^List of loaded mods/.test(l); });
    if (mi >= 0) {
      let cur = null;
      for (let i = mi + 1; i < lines.length && !/^-{10,}/.test(lines[i]); i++) {
        const l = lines[i];
        const gm = /^\s*- GUID: (.*?) \| Base: (\S+) \| Path: (.*)$/.exec(l);
        if (gm && cur) {
          cur.guid = gm[1];
          cur.path = gm[3];
          cur.lib = gm[3].split('/').pop();
        } else if (l.trim() && !/^\s/.test(l)) {
          const nm = /^(.*) \(([^()]*), version ([^()]*)\)$/.exec(l);
          cur = { name: nm ? nm[1] : l.trim(), author: nm ? nm[2] : '', version: nm ? nm[3] : '', guid: '', path: '', lib: '' };
          p.mods.push(cur);
        }
      }
    }

    let th = null;
    lines.forEach(function (l) {
      const tm = /^"(.*)" sysTid=(\d+)/.exec(l);
      if (tm) {
        th = { name: tm[1], tid: tm[2], frames: [] };
        p.threads.push(th);
        return;
      }
      if (/^-----/.test(l)) {
        th = null;
        return;
      }
      if (th) {
        const f = parseFrame(l);
        if (f) th.frames.push(f);
      }
    });

    const sig = function (f) { return /sigreturn/.test(f.func); };
    let ct = p.threads.find(function (x) { return x.frames.some(sig); });
    if (!ct) ct = p.threads.find(function (x) { return x.name === 'MainThread'; });
    if (ct) {
      const si = ct.frames.findIndex(sig);
      p.crashThread = ct.name;
      p.handlerFrames = si >= 0 ? ct.frames.slice(0, si) : [];
      p.crashFrames = si >= 0 ? ct.frames.slice(si + 1) : ct.frames;
    }
    p.stackStrings = stackStrings(lines);
    return p;
  }

  g.CrashParser = { parse: parse, demangle: demangle };
})(typeof window !== 'undefined' ? window : globalThis);
