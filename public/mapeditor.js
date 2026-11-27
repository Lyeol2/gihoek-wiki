/* 레벨 맵 — 지도(위에서 본 모습)와 플랫포밍(옆에서 본 모습)을 칸으로 그리고, 보고, 점프로 갈 수 있는지 검사한다.
   값 모양: { mode: 'top'|'side', rows: ['..##..', ...], markers: [{x, y, kind, label, note}], jump: {h, d} }
   md 파일에는 글자 그림(```map 블록)으로 저장돼서 메모장으로도 읽고 고칠 수 있다. */
(() => {
  const U = 10;            // 한 칸 = SVG 좌표 10
  const MAX_W = 80, MAX_H = 40, MIN_W = 8, MIN_H = 6;
  const SIZE = { top: [32, 20], side: [48, 16] };

  // [글자, 이름, 색 클래스]
  const TILES = {
    top: [['.', '지우개', ''], ['o', '바닥', 'floor'], ['#', '벽', 'wall'], [':', '길', 'path'], ['+', '문', 'door'],
      ['~', '물', 'water'], ['^', '높은 곳', 'high'], ['*', '수풀', 'bush'], ['x', '위험 지대', 'danger']],
    side: [['.', '지우개', ''], ['#', '땅', 'ground'], ['=', '발판', 'plat'], ['m', '움직이는 발판', 'move'], ['b', '부서지는 블록', 'break'],
      ['H', '사다리', 'ladder'], ['^', '가시', 'spike'], ['~', '물', 'water']],
  };
  const KINDS = [['start', '시작'], ['goal', '목표'], ['enemy', '적'], ['boss', '보스'], ['item', '아이템'],
    ['npc', 'NPC'], ['save', '체크포인트'], ['note', '메모']];
  const KIND_NAME = Object.fromEntries(KINDS);

  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const clamp = (n, a, b) => Math.max(a, Math.min(b, Math.round(+n) || a));
  const tileOf = (mode, ch) => TILES[mode].find(t => t[0] === ch);
  const width = v => v.rows.reduce((m, r) => Math.max(m, r.length), 0);

  function normalize(v, mode) {
    mode = mode === 'side' ? 'side' : 'top';
    v = v && typeof v === 'object' ? v : {};
    let rows = Array.isArray(v.rows) ? v.rows.map(r => String(r || '')) : [];
    const [dw, dh] = SIZE[mode];
    const w = clamp(rows.length ? Math.max(...rows.map(r => r.length)) : dw, MIN_W, MAX_W);
    const h = clamp(rows.length || dh, MIN_H, MAX_H);
    rows = Array.from({ length: h }, (_, y) => {
      // 세로가 모자라면 옆에서 본 맵은 위쪽을, 지도는 아래쪽을 채운다
      const src = mode === 'side' ? rows[y - (h - rows.length)] : rows[y];
      return [...(src || '').slice(0, w).padEnd(w, '.')].map(c => (tileOf(mode, c) ? c : '.')).join('');
    });
    const markers = (Array.isArray(v.markers) ? v.markers : []).filter(m => m && typeof m === 'object').map(m => ({
      x: clamp(m.x, 0, w - 1), y: clamp(m.y, 0, h - 1), kind: KIND_NAME[m.kind] ? m.kind : 'note',
      label: String(m.label || ''), note: String(m.note || ''),
    }));
    const out = { mode, rows, markers };
    if (mode === 'side') out.jump = { h: clamp(v.jump?.h ?? 3, 1, 12), d: clamp(v.jump?.d ?? 4, 1, 20) };
    return out;
  }

  const isBlank = v => !v || !Array.isArray(v.rows) || (!(v.markers || []).length && v.rows.every(r => /^\.*$/.test(r)));

  /* ---------------------------------------------------------- 그리기 */

  function tileSvg(mode, ch, x, y, n) {
    const cls = tileOf(mode, ch)[2];
    const X = x * U, Y = y * U, W = n * U;
    if (mode === 'side') {
      if (ch === '=') return `<rect class="mt mt-plat" x="${X}" y="${Y}" width="${W}" height="3" rx="1"/>`;
      if (ch === 'm') return `<rect class="mt mt-move" x="${X}" y="${Y}" width="${W}" height="3" rx="1"/><text class="map-glyph mt-move" x="${X + W / 2}" y="${Y + 8.6}">↔</text>`;
      if (ch === 'b') return Array.from({ length: n }, (_, i) => `<rect class="mt mt-break" x="${X + i * U + 0.6}" y="${Y + 0.6}" width="${U - 1.2}" height="${U - 1.2}" rx="1"/>`).join('');
      if (ch === '~') return `<rect class="mt mt-water" x="${X}" y="${Y + 2}" width="${W}" height="8"/>`;
      if (ch === 'H') return `<path class="mt-ladder" d="${Array.from({ length: n }, (_, i) => { const a = X + i * U; return `M${a + 2.5} ${Y}v10M${a + 7.5} ${Y}v10M${a + 2.5} ${Y + 2.5}h5M${a + 2.5} ${Y + 7.5}h5`; }).join('')}"/>`;
      if (ch === '^') return `<path class="mt mt-spike" d="${Array.from({ length: n }, (_, i) => `M${X + i * U} ${Y + 10}l2.5 -7l2.5 7l2.5 -7l2.5 7z`).join('')}"/>`;
    }
    if (ch === '+') return Array.from({ length: n }, (_, i) => `<rect class="mt mt-door" x="${X + i * U + 1.5}" y="${Y + 1.5}" width="7" height="7" rx="1.2"/>`).join('');
    return `<rect class="mt mt-${cls}" x="${X}" y="${Y}" width="${W}" height="${U}"/>`;
  }

  // o: { sel, unreach: [[x,y]], probe: [[x,y]], probeAt: [x,y], rect: 미리보기 }
  function svg(v, o = {}) {
    const w = width(v), h = v.rows.length;
    const out = [`<svg class="map-svg map-${v.mode}" viewBox="0 0 ${w * U} ${h * U}" style="max-width:${w * (o.cell || 22)}px" xmlns="http://www.w3.org/2000/svg">`,
      `<rect class="map-bg" width="${w * U}" height="${h * U}"/>`];
    v.rows.forEach((row, y) => {
      for (let x = 0; x < row.length;) {
        const c = row[x];
        let n = 1;
        while (row[x + n] === c) n++;
        if (c !== '.') out.push(tileSvg(v.mode, c, x, y, n));
        x += n;
      }
    });
    let d = '';
    for (let x = 1; x < w; x++) d += `M${x * U} 0V${h * U}`;
    for (let y = 1; y < h; y++) d += `M0 ${y * U}H${w * U}`;
    out.push(`<path class="map-grid" d="${d}"/>`);
    for (const [x, y] of o.unreach || []) out.push(`<rect class="map-unreach" x="${x * U}" y="${y * U}" width="${U}" height="${U}"/>`);
    for (const [x, y] of o.probe || []) out.push(`<rect class="map-probe" x="${x * U + 1}" y="${y * U + 1}" width="${U - 2}" height="${U - 2}" rx="2"/>`);
    if (o.probeAt) out.push(`<rect class="map-probe-at" x="${o.probeAt[0] * U}" y="${o.probeAt[1] * U}" width="${U}" height="${U}"/>`);
    v.markers.forEach((m, i) => {
      const cx = m.x * U + U / 2, cy = m.y * U + U / 2;
      if (i === o.sel) out.push(`<circle class="map-sel" cx="${cx}" cy="${cy}" r="6.2"/>`);
      out.push(`<g class="map-mk mk-${m.kind}"><circle cx="${cx}" cy="${cy}" r="4.4"/><text x="${cx}" y="${cy + 1.9}">${i + 1}</text></g>`);
    });
    out.push('</svg>');
    return out.join('');
  }

  /* ---------------------------------------------------------- 점프 검사 (옆에서 본 맵)
     점프 높이 = 올라갈 수 있는 칸 수, 점프 거리 = 평지에서 건널 수 있는 빈칸 수.
     포물선으로 어림한 검사라서 실제 게임의 조작감과는 다를 수 있다. */

  const SOLID = new Set(['#', 'b']), FLOOR = new Set(['#', 'b', '=', 'm', 'H']), DEAD = new Set(['^', '~']);

  function gridOf(v) {
    const w = width(v), h = v.rows.length;
    const at = (x, y) => (x < 0 || x >= w ? '#' : y < 0 || y >= h ? '.' : v.rows[y][x] || '.');
    const stand = (x, y) => {
      if (x < 0 || x >= w || y < 0 || y >= h) return false;
      const c = at(x, y);
      return c === 'H' || (c === '.' && y + 1 < h && FLOOR.has(at(x, y + 1)));
    };
    const settle = (x, y) => { while (y < h && !stand(x, y)) y++; return y < h ? y : -1; };   // 공중에 놓은 표시는 아래 바닥으로 내린다
    return { w, h, at, stand, settle };
  }

  function canJump(g, jh, jd, x, y, x2, y2) {
    const r = y - y2, dx = x2 - x;
    if (r > jh) return false;
    for (let a = jh; a >= Math.max(r, 1); a--) {            // a = 이번 점프의 꼭대기 높이. 낮게 뛰어야 천장을 피하는 경우가 있다
      const tl = (1 + Math.sqrt(1 - r / a)) / 2;
      if (Math.abs(dx) > (jd + 1) * Math.sqrt(a / jh) * tl + 1e-6) continue;
      let ok = true;
      for (let i = 1; i < 32 && ok; i++) {
        const s = i / 32, tt = s * tl;
        const px = Math.round(x + dx * s), py = Math.round(y - 4 * a * tt * (1 - tt));
        if ((px === x && py === y) || (px === x2 && py === y2)) continue;
        const c = g.at(px, py);
        if (SOLID.has(c) || DEAD.has(c)) ok = false;
      }
      if (ok) return true;
    }
    return false;
  }

  function standCells(g) {
    const out = [];
    for (let y = 0; y < g.h; y++) for (let x = 0; x < g.w; x++) if (g.stand(x, y)) out.push([x, y]);
    return out;
  }

  function jumpTargets(v, x, y) {
    const g = gridOf(v), { h: jh, d: jd } = v.jump;
    y = g.settle(x, y);
    if (y < 0) return { at: null, cells: [] };
    return { at: [x, y], cells: standCells(g).filter(([a, b]) => (a !== x || b !== y) && canJump(g, jh, jd, x, y, a, b)) };
  }

  function analyze(v) {
    const g = gridOf(v), { h: jh, d: jd } = v.jump;
    const cells = standCells(g);
    const start = v.markers.find(m => m.kind === 'start');
    if (!start) return { start: false, cells, unreach: [], goals: [] };
    const key = (x, y) => x + ',' + y;
    const seen = new Set();
    const sy = g.settle(start.x, start.y);
    const queue = [];
    const visit = (x, y) => { if (!seen.has(key(x, y))) { seen.add(key(x, y)); queue.push([x, y]); } };
    if (sy >= 0) visit(start.x, sy);
    const maxDx = Math.ceil((jd + 1) * 2.5);
    while (queue.length) {
      const [x, y] = queue.pop();
      for (const nx of [x - 1, x + 1]) if (g.stand(nx, y)) visit(nx, y);
      if (g.at(x, y) === 'H' && g.stand(x, y - 1)) visit(x, y - 1);
      if (g.at(x, y + 1) === 'H') visit(x, y + 1);
      for (const [a, b] of cells) {
        if (seen.has(key(a, b)) || Math.abs(a - x) > maxDx || y - b > jh) continue;
        if (canJump(g, jh, jd, x, y, a, b)) visit(a, b);
      }
    }
    const goals = v.markers.map((m, i) => ({ m, i })).filter(o => o.m.kind === 'goal').map(o => {
      const gy = g.settle(o.m.x, o.m.y);
      return { i: o.i, ok: gy >= 0 && seen.has(key(o.m.x, gy)) };
    });
    return { start: true, startOk: sy >= 0, cells, unreach: cells.filter(([x, y]) => !seen.has(key(x, y))), goals };
  }

  function checkHtml(v, a) {
    const j = `점프 높이 ${v.jump.h}칸 · 거리 ${v.jump.d}칸 기준`;
    if (!a.start) return `<span class="muted">${j} — <b>시작</b> 표시를 놓으면 갈 수 있는 곳을 검사해요.</span>`;
    if (!a.startOk) return `<span class="map-bad">시작 지점 아래에 설 땅이 없어요.</span>`;
    const parts = [];
    if (!a.goals.length) parts.push('<span class="muted">목표 표시가 없어요</span>');
    for (const g of a.goals) parts.push(g.ok ? `<span class="map-ok">✓ 목표 ${g.i + 1}번까지 갈 수 있어요</span>` : `<span class="map-bad">✕ 목표 ${g.i + 1}번에 닿지 못해요</span>`);
    parts.push(a.unreach.length ? `<span class="map-bad">닿지 못하는 자리 ${a.unreach.length}칸 (빨간 칸)</span>` : '<span class="map-ok">모든 발판에 닿아요</span>');
    return `<span class="muted">${j}</span> — ${parts.join(' · ')}`;
  }

  /* ---------------------------------------------------------- 보기 */

  function viewHtml(value, f) {
    const v = normalize(value, f.mode);
    const a = v.mode === 'side' ? analyze(v) : null;
    const used = TILES[v.mode].filter(t => t[0] !== '.' && v.rows.some(r => r.includes(t[0])));
    return `<div class="map-view">
      <div class="map-board">${svg(v, { unreach: a?.unreach })}</div>
      ${used.length ? `<div class="map-legend">${used.map(t => `<span><i class="map-sw mt-${t[2]}"></i>${t[1]}</span>`).join('')}</div>` : ''}
      ${a ? `<div class="map-check">${checkHtml(v, a)}</div>` : ''}
      ${v.markers.length ? `<div class="table-wrap map-marks"><table><thead><tr><th>번호</th><th>종류</th><th>이름</th><th>메모</th></tr></thead><tbody>
        ${v.markers.map((m, i) => `<tr><td><span class="map-num mk-${m.kind}">${i + 1}</span></td><td>${KIND_NAME[m.kind]}</td><td>${esc(m.label)}</td><td>${esc(m.note)}</td></tr>`).join('')}
      </tbody></table></div>` : ''}
    </div>`;
  }

  /* ---------------------------------------------------------- 편집기 */

  function mount(el, value, f, onChange) {
    const v = normalize(value, f.mode);
    const mode = v.mode;
    let tool = { t: 'tile', ch: TILES[mode][1][0] };   // {t:'tile',ch} | {t:'mark',kind} | {t:'move'} | {t:'probe'}
    let shape = 'pen';                                 // pen | rect | fill
    let sel = -1, probe = null, drag = null;
    const undo = [];
    const snap = () => { undo.push(JSON.stringify(v)); if (undo.length > 60) undo.shift(); };
    const emit = () => onChange(v);
    const W = () => width(v), H = () => v.rows.length;
    const setCell = (x, y, ch) => {
      if (x < 0 || y < 0 || x >= W() || y >= H() || v.rows[y][x] === ch) return;
      v.rows[y] = v.rows[y].slice(0, x) + ch + v.rows[y].slice(x + 1);
    };

    el.innerHTML = `<div class="map-ed">
      <div class="map-tools">
        <div class="map-group" data-g="tiles">${TILES[mode].map(t => `<button type="button" class="map-tool" data-tile="${esc(t[0])}" title="${t[1]}">${t[2] ? `<i class="map-sw mt-${t[2]}"></i>` : '<i class="map-sw map-sw-erase"></i>'}${t[1]}</button>`).join('')}</div>
        <div class="map-group">${[['pen', '붓'], ['rect', '사각형'], ['fill', '채우기']].map(s => `<button type="button" class="map-tool" data-shape="${s[0]}">${s[1]}</button>`).join('')}</div>
        <div class="map-group">${KINDS.map(k => `<button type="button" class="map-tool" data-kind="${k[0]}" title="${k[1]} 표시 놓기"><span class="map-num mk-${k[0]}"></span>${k[1]}</button>`).join('')}
          <button type="button" class="map-tool" data-tool="move" title="표시를 끌어서 옮기기">표시 옮기기</button>
          ${mode === 'side' ? '<button type="button" class="map-tool" data-tool="probe" title="칸 위에 마우스를 올리면 거기서 한 번에 뛸 수 있는 자리를 보여줘요">점프 범위 보기</button>' : ''}</div>
      </div>
      <div class="map-opts">
        <label>가로 <input type="number" class="input" data-size="w" min="${MIN_W}" max="${MAX_W}" value="${W()}"></label>
        <label>세로 <input type="number" class="input" data-size="h" min="${MIN_H}" max="${MAX_H}" value="${H()}"></label>
        ${mode === 'side' ? `<label>점프 높이 <input type="number" class="input" data-jump="h" min="1" max="12" value="${v.jump.h}"></label>
        <label>점프 거리 <input type="number" class="input" data-jump="d" min="1" max="20" value="${v.jump.d}"></label>` : ''}
        <span class="grow"></span>
        <button type="button" class="btn ghost small" data-do="undo" title="Ctrl+Z (맥은 ⌘Z)">되돌리기</button>
        <button type="button" class="btn ghost small danger" data-do="clear">모두 지우기</button>
      </div>
      <div class="map-board" tabindex="0"></div>
      <div class="map-check"></div>
      <div class="map-list"></div>
      <div class="hint">칸을 끌어서 칠해요. 마우스 오른쪽 버튼은 지우개. 표시는 종류를 고른 뒤 칸을 클릭하고, 아래 목록에서 이름과 메모를 적어요.${mode === 'side' ? ' 점프 높이는 올라갈 수 있는 칸 수, 점프 거리는 평지에서 건널 수 있는 빈칸 수예요.' : ''}</div>
    </div>`;
    const board = el.querySelector('.map-board'), listEl = el.querySelector('.map-list'), checkEl = el.querySelector('.map-check');

    const paint = () => {
      const a = mode === 'side' ? analyze(v) : null;
      board.innerHTML = svg(v, { sel, unreach: a?.unreach, probe: probe?.cells, probeAt: probe?.at });
      checkEl.innerHTML = a ? checkHtml(v, a) : '';
    };
    const tools = () => {
      el.querySelectorAll('.map-tool').forEach(b => {
        const d = b.dataset;
        b.classList.toggle('on', !!((d.tile !== undefined && tool.t === 'tile' && tool.ch === d.tile) || (d.kind && tool.t === 'mark' && tool.kind === d.kind) ||
          (d.tool && tool.t === d.tool) || (d.shape && tool.t === 'tile' && shape === d.shape)));
        if (d.shape) b.disabled = tool.t !== 'tile';
      });
      board.dataset.cursor = tool.t;
    };
    const list = () => {
      listEl.innerHTML = v.markers.map((m, i) => `<div class="map-mrow${i === sel ? ' on' : ''}" data-mi="${i}">
        <span class="map-num mk-${m.kind}">${i + 1}</span>
        <select class="input" data-mp="kind">${KINDS.map(k => `<option value="${k[0]}"${k[0] === m.kind ? ' selected' : ''}>${k[1]}</option>`).join('')}</select>
        <input class="input" data-mp="label" placeholder="이름" value="${esc(m.label)}">
        <input class="input" data-mp="note" placeholder="메모 (예: 순찰 범위, 등장 조건)" value="${esc(m.note)}">
        <button type="button" class="row-x" data-mdel="${i}" title="표시 삭제">×</button></div>`).join('');
    };
    const all = () => { paint(); list(); tools(); };

    const cellAt = e => {
      const r = board.firstElementChild.getBoundingClientRect();
      return [Math.floor((e.clientX - r.left) / r.width * W()), Math.floor((e.clientY - r.top) / r.height * H())];
    };
    const markerAt = (x, y) => { for (let i = v.markers.length - 1; i >= 0; i--) if (v.markers[i].x === x && v.markers[i].y === y) return i; return -1; };
    const line = (x0, y0, x1, y1, ch) => {
      const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1);
      for (let i = 0; i <= n; i++) setCell(Math.round(x0 + (x1 - x0) * i / n), Math.round(y0 + (y1 - y0) * i / n), ch);
    };
    const flood = (x, y, ch) => {
      const from = v.rows[y]?.[x];
      if (from === undefined || from === ch) return;
      const todo = [[x, y]];
      while (todo.length) {
        const [a, b] = todo.pop();
        if (v.rows[b]?.[a] !== from) continue;
        setCell(a, b, ch);
        todo.push([a + 1, b], [a - 1, b], [a, b + 1], [a, b - 1]);
      }
    };

    board.addEventListener('contextmenu', e => e.preventDefault());
    board.addEventListener('pointerdown', e => {
      if (!board.firstElementChild) return;
      const [x, y] = cellAt(e);
      if (x < 0 || y < 0 || x >= W() || y >= H()) return;
      board.focus({ preventScroll: true });
      if (tool.t === 'probe') return;
      const erase = e.button === 2;
      if (tool.t === 'tile' || erase) {
        const ch = erase ? '.' : tool.ch;
        snap();
        if (shape === 'fill' && !erase) { flood(x, y, ch); emit(); return paint(); }
        drag = shape === 'rect' && !erase ? { t: 'rect', x0: x, y0: y, base: [...v.rows], ch } : { t: 'pen', x, y, ch };
        setCell(x, y, ch);
      } else {
        let i = markerAt(x, y);
        if (i < 0 && tool.t === 'mark') {
          snap();
          const old = tool.kind === 'start' ? v.markers.findIndex(m => m.kind === 'start') : -1;   // 시작은 하나만
          if (old >= 0) { v.markers[old].x = x; v.markers[old].y = y; i = old; }
          else { v.markers.push({ x, y, kind: tool.kind, label: '', note: '' }); i = v.markers.length - 1; }
          emit();
        } else if (i >= 0) snap();
        sel = i;
        if (i >= 0) drag = { t: 'mark', i };
        list();
      }
      board.setPointerCapture(e.pointerId);
      paint();
    });
    board.addEventListener('pointermove', e => {
      if (!board.firstElementChild) return;
      const [x, y] = cellAt(e);
      if (tool.t === 'probe') {
        const k = x + ',' + y;
        if (probe?.k === k) return;
        probe = x >= 0 && y >= 0 && x < W() && y < H() ? { k, ...jumpTargets(v, x, y) } : null;
        return paint();
      }
      if (!drag) return;
      const cx = clamp(x, 0, W() - 1), cy = clamp(y, 0, H() - 1);
      if (drag.t === 'pen') { if (cx === drag.x && cy === drag.y) return; line(drag.x, drag.y, cx, cy, drag.ch); drag.x = cx; drag.y = cy; }
      else if (drag.t === 'rect') {
        v.rows = [...drag.base];
        for (let b = Math.min(drag.y0, cy); b <= Math.max(drag.y0, cy); b++) for (let a = Math.min(drag.x0, cx); a <= Math.max(drag.x0, cx); a++) setCell(a, b, drag.ch);
      } else if (drag.t === 'mark') { const m = v.markers[drag.i]; if (m.x === cx && m.y === cy) return; m.x = cx; m.y = cy; }
      paint();
    });
    const end = () => { if (drag) { drag = null; emit(); } };
    board.addEventListener('pointerup', end);
    board.addEventListener('pointercancel', end);
    board.addEventListener('pointerleave', () => { if (probe) { probe = null; paint(); } });

    const doUndo = () => {
      const s = undo.pop();
      if (!s) return;
      const o = JSON.parse(s);
      v.rows = o.rows; v.markers = o.markers; if (o.jump) v.jump = o.jump;
      sel = -1;
      el.querySelector('[data-size=w]').value = W(); el.querySelector('[data-size=h]').value = H();
      emit(); all();
    };
    const removeMarker = i => { snap(); v.markers.splice(i, 1); sel = -1; emit(); paint(); list(); };
    board.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(); }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && sel >= 0) { e.preventDefault(); removeMarker(sel); }
    });

    el.querySelector('.map-ed').addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      const d = b.dataset;
      if (d.tile !== undefined) tool = { t: 'tile', ch: d.tile };
      else if (d.shape) shape = d.shape;
      else if (d.kind) tool = { t: 'mark', kind: d.kind };
      else if (d.tool) tool = { t: d.tool };
      else if (d.do === 'undo') return doUndo();
      else if (d.do === 'clear') {
        if (!confirm('맵을 모두 지울까요? (되돌리기로 살릴 수 있어요)')) return;
        snap(); v.rows = v.rows.map(r => '.'.repeat(r.length)); v.markers = []; sel = -1; emit(); return all();
      } else if (d.mdel !== undefined) return removeMarker(+d.mdel);
      else return;
      if (tool.t !== 'probe' && probe) { probe = null; paint(); }
      tools();
    });

    el.querySelector('.map-opts').addEventListener('change', e => {
      const d = e.target.dataset;
      if (d.size) {
        snap();
        const w = clamp(el.querySelector('[data-size=w]').value, MIN_W, MAX_W), h = clamp(el.querySelector('[data-size=h]').value, MIN_H, MAX_H);
        const dy = mode === 'side' ? h - H() : 0;   // 옆에서 본 맵은 바닥을 기준으로 위쪽을 늘리고 줄인다
        const rows = Array.from({ length: h }, (_, y) => (v.rows[y - dy] || '').slice(0, w).padEnd(w, '.'));
        v.rows = rows;
        v.markers = v.markers.map(m => ({ ...m, y: m.y + dy })).filter(m => m.x < w && m.y >= 0 && m.y < h);
        sel = -1;
        el.querySelector('[data-size=w]').value = w; el.querySelector('[data-size=h]').value = h;
        emit(); all();
      } else if (d.jump) {
        v.jump[d.jump] = clamp(e.target.value, 1, d.jump === 'h' ? 12 : 20);
        e.target.value = v.jump[d.jump];
        emit(); paint();
      }
    });

    const onList = e => {
      const row = e.target.closest('[data-mi]'), p = e.target.dataset.mp;
      if (!row || !p) return;
      const m = v.markers[+row.dataset.mi];
      if (p === 'kind') {
        if (e.type !== 'change') return;
        if (e.target.value === 'start') v.markers.forEach(o => { if (o !== m && o.kind === 'start') o.kind = 'note'; });
        m.kind = e.target.value; emit(); paint(); list();
      } else { m[p] = e.target.value; emit(); }
    };
    listEl.addEventListener('input', onList);
    listEl.addEventListener('change', onList);
    listEl.addEventListener('focusin', e => {
      const row = e.target.closest('[data-mi]');
      if (!row || sel === +row.dataset.mi) return;
      sel = +row.dataset.mi;
      listEl.querySelectorAll('.map-mrow').forEach(r => r.classList.toggle('on', r === row));
      paint();
    });

    all();
  }

  window.LevelMap = { normalize, isBlank, svg, viewHtml, mount, analyze, jumpTargets, TILES, KINDS };
})();
