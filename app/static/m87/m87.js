/* Página interna: a primeira foto de um buraco negro (M87*).
 *
 * Segurança: arquivo externo carregado com `defer` (a CSP permite só
 * script-src 'self'). Não usa eval, innerHTML com dados nem recursos de
 * terceiros. Todo texto dinâmico entra por textContent.
 */
"use strict";

(function () {
  document.documentElement.classList.add("js");

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const DPR = Math.min(2, window.devicePixelRatio || 1);
  const $ = (id) => document.getElementById(id);

  /** Executa `fn` quando `el` entra na tela (uma única vez). */
  function onVisible(el, fn, threshold = 0.35) {
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { io.disconnect(); fn(); }
    }, { threshold });
    io.observe(el);
  }

  /** Loop de animação que pausa quando o elemento sai da tela. */
  function animateWhileVisible(el, frame) {
    let running = false, visible = false;
    const tick = (t) => { if (!visible) { running = false; return; } frame(t); requestAnimationFrame(tick); };
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible && !running) { running = true; requestAnimationFrame(tick); }
    }).observe(el);
  }

  /* ------------------------------------------------------------------ *
   * 1. Abertura: buraco negro com lente gravitacional
   * ------------------------------------------------------------------ */
  (function hero() {
    const c = $("bh"); if (!c) return;
    const x = c.getContext("2d");
    let W = 0, H = 0, stars = [], t = 0;
    let mx = 0.5, my = 0.42, tx = 0.5, ty = 0.42;

    function resize() {
      W = c.width = Math.round(c.clientWidth * DPR);
      H = c.height = Math.round(c.clientHeight * DPR);
      const n = Math.round(Math.min(1100, (W * H) / (1800 * DPR)));
      stars = Array.from({ length: n }, () => ({
        x: Math.random() * W, y: Math.random() * H,
        r: (Math.random() * 1.2 + 0.25) * DPR, a: 0.35 + Math.random() * 0.65,
      }));
      draw();
    }

    function draw() {
      mx += (tx - mx) * 0.06; my += (ty - my) * 0.06;
      x.fillStyle = "#04050a"; x.fillRect(0, 0, W, H);
      const cx = mx * W, cy = my * H, R = Math.min(W, H) * 0.11, E = R * 1.6;

      // Estrelas deslocadas pela lente: posição aparente r' = (r + √(r² + 4θE²)) / 2
      x.fillStyle = "#fff";
      for (const s of stars) {
        const dx = s.x - cx, dy = s.y - cy, r = Math.hypot(dx, dy) || 1;
        const r2 = (r + Math.sqrt(r * r + 4 * E * E)) / 2;
        if (r2 < R * 1.05) continue;
        const stretch = 1 + (E * E) / (r2 * r2) * 2.2; // estrelas perto do anel ficam esticadas
        x.globalAlpha = s.a;
        x.beginPath();
        x.ellipse(cx + (dx / r) * r2, cy + (dy / r) * r2, s.r, s.r * stretch, Math.atan2(dy, dx) + Math.PI / 2, 0, 7);
        x.fill();
      }
      x.globalAlpha = 1;

      // Disco de acréscimo (parte de trás), com o lado que se aproxima mais brilhante (efeito Doppler)
      x.save(); x.translate(cx, cy); x.scale(1, 0.28);
      for (let i = 0; i < 90; i++) {
        const a = t * 3 + (i / 90) * Math.PI * 2, rr = R * (2.1 + Math.sin(i * 7.3) * 0.35);
        const b = 0.55 + 0.45 * Math.cos(a);
        x.strokeStyle = `rgba(255,${(120 + b * 90) | 0},${(40 + b * 60) | 0},${0.05 + b * 0.12})`;
        x.lineWidth = R * 0.35; x.beginPath(); x.arc(0, 0, rr, a, a + 0.25); x.stroke();
      }
      x.restore();

      // Anel de fótons e sombra
      const g = x.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.5);
      g.addColorStop(0, "rgba(255,200,120,.95)"); g.addColorStop(0.25, "rgba(255,138,61,.5)"); g.addColorStop(1, "rgba(255,77,46,0)");
      x.fillStyle = g; x.beginPath(); x.arc(cx, cy, R * 1.5, 0, 7); x.fill();
      x.fillStyle = "#000"; x.beginPath(); x.arc(cx, cy, R, 0, 7); x.fill();

      // Parte da frente do disco, passando na frente da sombra
      x.save(); x.translate(cx, cy); x.scale(1, 0.28);
      x.strokeStyle = "rgba(255,170,90,.55)"; x.lineWidth = R * 0.3;
      x.beginPath(); x.arc(0, 0, R * 2, 0, Math.PI); x.stroke();
      x.restore();
    }

    c.parentElement.addEventListener("pointermove", (e) => {
      const b = c.getBoundingClientRect();
      tx = 0.5 + ((e.clientX - b.left) / b.width - 0.5) * 0.25;
      ty = 0.42 + ((e.clientY - b.top) / b.height - 0.5) * 0.18;
      if (reduceMotion) { mx = tx; my = ty; draw(); }
    });
    window.addEventListener("resize", resize);
    resize();
    if (!reduceMotion) animateWhileVisible(c, () => { t += 0.004; draw(); });
  })();

  /* ------------------------------------------------------------------ *
   * 2. A foto real se formando a partir de ruído
   * ------------------------------------------------------------------ */
  (function reveal() {
    const c = $("reveal"), prog = $("prog"); if (!c) return;
    const x = c.getContext("2d"), N = c.width;

    function proceduralRing() { // reserva caso a foto não carregue
      const t = new Float32Array(N * N * 3);
      for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
        const dx = i - N / 2, dy = j - N / 2, r = Math.hypot(dx, dy), a = Math.atan2(dy, dx);
        const v = Math.min(1, Math.exp(-((r - N / 4) ** 2) / (2 * (N / 16) ** 2)) * (0.55 + 0.45 * Math.sin(a + 1.9)) * 1.25);
        const q = (j * N + i) * 3; t[q] = Math.min(1, v * 1.25); t[q + 1] = 0.67 * v * v + 0.12 * v; t[q + 2] = 0.24 * v * v * v;
      }
      return t;
    }

    function run(target, label) {
      const img = x.createImageData(N, N);
      let k = reduceMotion ? 1 : 0;
      (function frame() {
        const noise = 1 - k;
        for (let p = 0, q = 0; p < N * N; p++, q += 3) {
          const n = (Math.random() - 0.35) * noise;
          img.data[p * 4] = 255 * Math.max(0, Math.min(1, target[q] * k + n));
          img.data[p * 4 + 1] = 255 * Math.max(0, Math.min(1, target[q + 1] * k + n * 0.6));
          img.data[p * 4 + 2] = 255 * Math.max(0, Math.min(1, target[q + 2] * k + n * 0.3));
          img.data[p * 4 + 3] = 255;
        }
        x.putImageData(img, 0, 0);
        prog.textContent = k >= 1 ? label : `reconstruindo os dados… ${Math.round(k * 100)}%`;
        if (k < 1) { k = Math.min(1, k + 0.01 + k * 0.012); requestAnimationFrame(frame); }
      })();
    }

    function start() {
      const im = new Image();
      im.onload = () => {
        const off = document.createElement("canvas"); off.width = off.height = N;
        const o = off.getContext("2d");
        const s = Math.min(im.width, im.height); // recorte quadrado central
        o.drawImage(im, (im.width - s) / 2, (im.height - s) / 2, s, s, 0, 0, N, N);
        const d = o.getImageData(0, 0, N, N).data, t = new Float32Array(N * N * 3);
        for (let p = 0; p < N * N; p++) { t[p * 3] = d[p * 4] / 255; t[p * 3 + 1] = d[p * 4 + 1] / 255; t[p * 3 + 2] = d[p * 4 + 2] / 255; }
        run(t, "reconstrução concluída ✓");
      };
      im.onerror = () => run(proceduralRing(), "simulação (arquivo da foto não encontrado)");
      im.src = c.dataset.src;
    }
    onVisible(c, start, 0.4);
  })();

  /* ------------------------------------------------------------------ *
   * 3. Linha do tempo que acende com o scroll
   * ------------------------------------------------------------------ */
  (function timeline() {
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("on"); io.unobserve(e.target); }
    }), { threshold: 0.4 });
    document.querySelectorAll(".ev").forEach((el) => io.observe(el));
  })();

  /* ------------------------------------------------------------------ *
   * 4. Globo com os 8 observatórios do EHT em 2017
   * ------------------------------------------------------------------ */
  (function globe() {
    const c = $("globe"), list = $("obs-list"), info = $("info"); if (!c) return;
    const x = c.getContext("2d");
    const OBS = [
      { id: "ALMA", nome: "Atacama Large Millimeter/submillimeter Array", local: "Planalto de Chajnantor, Deserto do Atacama, Chile", lat: -23.03, lon: -67.75 },
      { id: "APEX", nome: "Atacama Pathfinder Experiment", local: "Planalto de Chajnantor, Deserto do Atacama, Chile", lat: -23.01, lon: -67.76 },
      { id: "IRAM 30 m", nome: "Radiotelescópio de 30 metros do IRAM", local: "Pico Veleta, Serra Nevada, Espanha", lat: 37.07, lon: -3.39 },
      { id: "JCMT", nome: "James Clerk Maxwell Telescope", local: "Maunakea, Havaí, EUA", lat: 19.82, lon: -155.48 },
      { id: "SMA", nome: "Submillimeter Array", local: "Maunakea, Havaí, EUA", lat: 19.82, lon: -155.48 },
      { id: "LMT", nome: "Large Millimeter Telescope Alfonso Serrano", local: "Vulcão Sierra Negra, Puebla, México", lat: 18.99, lon: -97.31 },
      { id: "SMT", nome: "Submillimeter Telescope", local: "Monte Graham, Arizona, EUA", lat: 32.70, lon: -109.89 },
      { id: "SPT", nome: "South Pole Telescope", local: "Estação Amundsen-Scott, Polo Sul, Antártida", lat: -89.99, lon: -45 },
    ];
    const RAD = Math.PI / 180;
    let rotLon = 80, rotLat = -15, land = [], selected = null, dragging = false, last = null, idle = 0, goal = null, S = 0;

    function resize() { S = c.width = c.height = Math.round(c.clientWidth * DPR); draw(); }

    function vec(lat, lon) { // coordenadas → vetor 3D já girado pela vista atual
      const la = lat * RAD, lo = (lon + rotLon) * RAD, cl = Math.cos(la);
      const X = cl * Math.sin(lo), Y = Math.sin(la), Z = cl * Math.cos(lo);
      const r = rotLat * RAD;
      return [X, Y * Math.cos(r) - Z * Math.sin(r), Y * Math.sin(r) + Z * Math.cos(r)];
    }
    const R = () => S * 0.44;
    const scr = (v) => [S / 2 + v[0] * R(), S / 2 - v[1] * R()];

    function draw() {
      if (!S) return;
      x.clearRect(0, 0, S, S);
      const g = x.createRadialGradient(S * 0.42, S * 0.4, R() * 0.1, S / 2, S / 2, R());
      g.addColorStop(0, "#16203a"); g.addColorStop(1, "#070a14");
      x.fillStyle = g; x.beginPath(); x.arc(S / 2, S / 2, R(), 0, 7); x.fill();
      x.strokeStyle = "#7aa7ff33"; x.lineWidth = DPR; x.stroke();

      // Meridianos e paralelos
      x.strokeStyle = "#7aa7ff14";
      for (let lo = -180; lo < 180; lo += 30) line(Array.from({ length: 61 }, (_, i) => [-90 + i * 3, lo]));
      for (let la = -60; la <= 60; la += 30) line(Array.from({ length: 121 }, (_, i) => [la, -180 + i * 3]));

      // Continentes em pontos
      for (const p of land) {
        const v = vec(p[0], p[1]); if (v[2] <= 0) continue;
        const [sx, sy] = scr(v);
        x.fillStyle = `rgba(236,232,225,${0.12 + v[2] * 0.4})`;
        x.fillRect(sx - DPR, sy - DPR, 1.6 * DPR, 1.6 * DPR);
      }

      // Linhas de base (arcos de grande círculo) entre os locais
      x.lineWidth = 1.2 * DPR;
      for (let i = 0; i < OBS.length; i++) for (let j = i + 1; j < OBS.length; j++) {
        const hot = selected && (OBS[i] === selected || OBS[j] === selected);
        x.strokeStyle = hot ? "#ffc46baa" : "#7aa7ff30";
        line(arc(OBS[i], OBS[j]), true);
      }

      // Marcadores
      const pulse = reduceMotion ? 0 : (performance.now() / 1200) % 1;
      for (const o of OBS) {
        const v = vec(o.lat, o.lon); if (v[2] <= 0) continue;
        const [sx, sy] = scr(v), on = o === selected;
        x.strokeStyle = `rgba(255,196,107,${(1 - pulse) * 0.8})`; x.lineWidth = DPR;
        x.beginPath(); x.arc(sx, sy, (5 + pulse * 12) * DPR, 0, 7); x.stroke();
        x.fillStyle = on ? "#fff" : "#ffc46b";
        x.beginPath(); x.arc(sx, sy, (on ? 6 : 4.5) * DPR, 0, 7); x.fill();
      }
    }

    function line(pts, isArc) {
      x.beginPath(); let pen = false;
      for (const p of pts) {
        const v = isArc ? p : vec(p[0], p[1]);
        if (v[2] <= 0) { pen = false; continue; }
        const [sx, sy] = scr(v);
        pen ? x.lineTo(sx, sy) : x.moveTo(sx, sy); pen = true;
      }
      x.stroke();
    }

    function arc(a, b) { // interpolação esférica entre dois locais
      const va = vec(a.lat, a.lon), vb = vec(b.lat, b.lon);
      const d = Math.acos(Math.max(-1, Math.min(1, va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2])));
      if (d < 1e-3) return [];
      const out = [];
      for (let i = 0; i <= 40; i++) {
        const t = i / 40, s1 = Math.sin((1 - t) * d) / Math.sin(d), s2 = Math.sin(t * d) / Math.sin(d);
        out.push([va[0] * s1 + vb[0] * s2, va[1] * s1 + vb[1] * s2, va[2] * s1 + vb[2] * s2]);
      }
      return out;
    }

    function select(o) {
      selected = o;
      const vizinhos = OBS.filter((p) => p !== o && p.lat === o.lat && p.lon === o.lon).map((p) => p.id);
      info.replaceChildren();
      const b = document.createElement("b"); b.textContent = `${o.id} · ${o.nome}`;
      const p = document.createElement("span");
      p.textContent = o.local + (vizinhos.length ? ` (mesmo local que ${vizinhos.join(", ")})` : "");
      info.append(b, p);
      list.querySelectorAll("button").forEach((btn) => btn.setAttribute("aria-pressed", String(btn.dataset.id === o.id)));
      goal = { lon: -o.lon, lat: Math.max(-60, Math.min(60, o.lat)) };
      idle = 0; draw();
    }

    OBS.forEach((o) => {
      const li = document.createElement("li"), btn = document.createElement("button");
      btn.type = "button"; btn.dataset.id = o.id; btn.textContent = o.id; btn.setAttribute("aria-pressed", "false");
      btn.addEventListener("click", () => select(o));
      li.append(btn); list.append(li);
    });

    c.addEventListener("pointerdown", (e) => { dragging = true; last = [e.clientX, e.clientY, e.clientX, e.clientY]; c.setPointerCapture(e.pointerId); c.classList.add("drag"); goal = null; });
    c.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      rotLon += (e.clientX - last[0]) * 0.4;
      rotLat = Math.max(-80, Math.min(80, rotLat - (e.clientY - last[1]) * 0.4));
      last[0] = e.clientX; last[1] = e.clientY; idle = 0; draw();
    });
    c.addEventListener("pointerup", (e) => {
      dragging = false; c.classList.remove("drag");
      if (Math.hypot(e.clientX - last[2], e.clientY - last[3]) > 5) return; // foi arraste, não clique
      const b = c.getBoundingClientRect(), px = (e.clientX - b.left) * (S / b.width), py = (e.clientY - b.top) * (S / b.height);
      let best = null, bestD = 18 * DPR;
      for (const o of OBS) {
        const v = vec(o.lat, o.lon); if (v[2] <= 0) continue;
        const [sx, sy] = scr(v), d = Math.hypot(sx - px, sy - py);
        if (d < bestD) { best = o; bestD = d; }
      }
      if (best) select(best);
    });

    function buildLand(rings) { // pontos em grade sobre os continentes (teste ponto-no-polígono)
      const polys = rings.map((r) => {
        const pts = []; let a = 180, b = -180, c2 = 90, d = -90;
        for (let i = 0; i < r.length; i += 2) { pts.push([r[i], r[i + 1]]); a = Math.min(a, r[i]); b = Math.max(b, r[i]); c2 = Math.min(c2, r[i + 1]); d = Math.max(d, r[i + 1]); }
        return { pts, box: [a, b, c2, d] };
      });
      const inside = (lo, la) => polys.some(({ pts, box }) => {
        if (lo < box[0] || lo > box[1] || la < box[2] || la > box[3]) return false;
        let inn = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
          const [xi, yi] = pts[i], [xj, yj] = pts[j];
          if ((yi > la) !== (yj > la) && lo < ((xj - xi) * (la - yi)) / (yj - yi) + xi) inn = !inn;
        }
        return inn;
      });
      const out = [];
      for (let la = -88; la <= 88; la += 2) {
        const step = 2 / Math.max(0.2, Math.cos(la * RAD));
        for (let lo = -180; lo < 180; lo += step) if (inside(lo, la)) out.push([la, lo]);
      }
      return out;
    }

    fetch(c.dataset.land, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : []))
      .then((rings) => { land = buildLand(rings); draw(); })
      .catch(() => {});

    window.addEventListener("resize", resize);
    resize();
    animateWhileVisible(c, () => {
      if (goal) {
        const dl = ((goal.lon - rotLon + 540) % 360) - 180;
        rotLon += dl * 0.08; rotLat += (goal.lat - rotLat) * 0.08;
        if (Math.abs(dl) < 0.2 && Math.abs(goal.lat - rotLat) < 0.2) goal = null;
      } else if (!dragging && !reduceMotion && ++idle > 120) {
        rotLon += 0.12; // gira sozinho depois de ~2 s parado
      }
      draw();
    });
  })();

  /* ------------------------------------------------------------------ *
   * 5. As pessoas: 200 pontos que se acendem
   * ------------------------------------------------------------------ */
  (function people() {
    const d = $("dots"); if (!d) return;
    const dots = Array.from({ length: 200 }, () => d.appendChild(document.createElement("i")));
    onVisible(d, () => {
      if (reduceMotion) { dots.forEach((e, n) => e.classList.add(n % 7 ? "lit" : "hi")); return; }
      const order = dots.map((_, i) => i).sort(() => Math.random() - 0.5);
      order.forEach((idx, n) => setTimeout(() => dots[idx].classList.add(n % 7 ? "lit" : "hi"), n * 9));
    });
  })();

  /* ------------------------------------------------------------------ *
   * 6. Laboratório: massa → tamanho do horizonte de eventos
   * ------------------------------------------------------------------ */
  (function lab() {
    const c = $("lab"), m = $("massa"); if (!c || !m) return;
    const x = c.getContext("2d"), W = c.width;
    const G = 6.674e-11, MSUN = 1.989e30, C = 2.998e8, UA = 1.496e11;
    const LOG_MAX = Math.log10(6.5e9); // M87*: o slider termina exatamente nela
    const fmt = (v, d = 0) => v.toLocaleString("pt-BR", { maximumFractionDigits: d });

    function nomeMassa(M) {
      if (M >= 1e9) return `${fmt(M / 1e9, 1)} bilhões de sóis`;
      if (M >= 1e6) return `${fmt(M / 1e6, 1)} milhões de sóis`;
      if (M >= 1e3) return `${fmt(M / 1e3, 1)} mil sóis`;
      return M < 1.95 ? "1 sol" : `${fmt(M, 0)} sóis`;
    }
    function nomeRaio(rs) {
      const km = rs / 1e3;
      if (rs >= 0.05 * UA) return `${fmt(km / 1e6, 1)} milhões de km (${fmt(rs / UA, 1)} UA)`;
      if (km >= 1e6) return `${fmt(km / 1e6, 1)} milhões de km`;
      return `${fmt(km, km < 100 ? 1 : 0)} km`;
    }
    function comparar(M, rs) {
      if (M < 2) return "O Sol, se fosse comprimido até virar um buraco negro, caberia numa cidade pequena.";
      if (M < 100) return "Buraco negro estelar: nasce do colapso de uma estrela gigante.";
      if (M < 1e5) return "Buraco negro de massa intermediária: raro e difícil de encontrar.";
      if (M < 2e7) return "Na faixa de Sagitário A*, no centro da Via Láctea (cerca de 4 milhões de sóis).";
      if (M < 6.4e9) return "Buraco negro supermassivo, no centro de grandes galáxias.";
      return `M87*: o horizonte tem cerca de ${fmt(rs / UA / 39.5, 0)} vezes o raio médio da órbita de Plutão.`;
    }

    function draw() {
      const logM = (m.value / m.max) * LOG_MAX, M = 10 ** logM, rs = (2 * G * M * MSUN) / (C * C);
      const r = 18 + (logM / LOG_MAX) * W * 0.3;
      x.fillStyle = "#000"; x.fillRect(0, 0, W, W);
      const g = x.createRadialGradient(W / 2, W / 2, r, W / 2, W / 2, r * 1.6);
      g.addColorStop(0, "rgba(255,196,107,.95)"); g.addColorStop(0.3, "rgba(255,138,61,.55)"); g.addColorStop(1, "rgba(255,77,46,0)");
      x.fillStyle = g; x.beginPath(); x.arc(W / 2, W / 2, r * 1.6, 0, 7); x.fill();
      x.fillStyle = "#000"; x.beginPath(); x.arc(W / 2, W / 2, r, 0, 7); x.fill();
      $("ro-massa").textContent = nomeMassa(M);
      $("ro-raio").textContent = nomeRaio(rs);
      const comp = $("ro-comp"); comp.textContent = comparar(M, rs); comp.classList.toggle("hit", M >= 6.4e9);
    }
    m.addEventListener("input", draw);
    draw();
  })();
})();
