// Edit PDF and Sign PDF.  Pages are drawn in the browser; additions are kept as
// objects positioned in fractions of the page, and sent to the server on Save.
import { h, setStatus } from "./ui.js";
import { openPdf, renderInto } from "./pdfview.js";

const MODES = [
  ["select", "Select"], ["text", "Text"], ["image", "Image"], ["sign", "Signature"],
  ["highlight", "Highlight"], ["whiteout", "White-out"], ["rect", "Box"], ["draw", "Draw"],
];
const FONTS = { sans: ["PF Sans", 400], "sans-bold": ["PF Sans", 700], serif: ["PF Serif", 400], "serif-bold": ["PF Serif", 700], mono: ["PF Mono", 400] };
const SIZES = [8, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64, 72];
let nextId = 1;

export function mount(view, { tool, id, caps, toolHead, dropSheet, submit }) {
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  const result = h("div");
  const state = { file: null, doc: null, pages: [], objects: [], selected: null, mode: "select", history: [],
    color: "#1d2b3a", size: 14, font: "sans", width: 0 };

  // ---------- toolbar
  const modeButtons = MODES.map(([m, label]) => h("button", { class: "etool", type: "button", "aria-pressed": String(m === "select"), "data-mode": m, onclick: () => setMode(m) }, label));
  const color = h("input", { type: "color", value: state.color, title: "Colour", "aria-label": "Colour" });
  const size = h("select", { "aria-label": "Text size", title: "Text size" }, ...SIZES.map((s) => h("option", { value: s, selected: s === state.size }, `${s} pt`)));
  const font = h("select", { "aria-label": "Font", title: "Font" },
    h("option", { value: "sans" }, "Sans"), h("option", { value: "sans-bold" }, "Sans bold"),
    h("option", { value: "serif" }, "Serif"), h("option", { value: "serif-bold" }, "Serif bold"), h("option", { value: "mono" }, "Mono"));
  const undoBtn = h("button", { class: "etool", type: "button", onclick: undo, disabled: true }, "Undo");
  const delBtn = h("button", { class: "etool", type: "button", onclick: removeSelected, disabled: true }, "Delete");
  const save = h("button", { class: "btn", type: "button" }, id === "sign" ? "Save signed PDF" : "Save PDF");
  const toolbar = h("div", { class: "etools", role: "toolbar", "aria-label": "Editing tools" },
    h("div", { class: "seg" }, ...modeButtons),
    h("div", { class: "seg" }, color, size, font),
    h("div", { class: "seg" }, undoBtn, delBtn),
    h("div", { class: "seg" }, save));
  const pagesBox = h("div", { class: "epages" });
  const editor = h("div", { class: "editor hidden", "data-mode": "select" }, toolbar, status, result, pagesBox);
  const imageInput = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "hidden" });
  const sheetStatus = h("div", { class: "status", role: "status" });

  color.addEventListener("input", () => { state.color = color.value; applyStyle({ color: color.value }); });
  size.addEventListener("change", () => { state.size = Number(size.value); applyStyle({ size: state.size }); });
  font.addEventListener("change", () => { state.font = font.value; applyStyle({ font: font.value }); });

  const sheet = dropSheet({ big: "Drop your PDF here", hint: `.pdf · up to ${caps.limits.max_file_mb} MB`, accept: ["pdf"], compact: true,
    onFiles: (files) => load(files[0]) });

  async function load(f) {
    if (!f.name.toLowerCase().endsWith(".pdf")) return setStatus(sheetStatus, "Choose a PDF file.", true);
    setStatus(sheetStatus, "Opening…");
    try {
      state.doc = await openPdf(f);
      if (state.doc.numPages > caps.limits.max_pages) throw new Error(`This PDF has ${state.doc.numPages} pages; the limit is ${caps.limits.max_pages}.`);
    } catch (e) { return setStatus(sheetStatus, e.message, true); }
    state.file = f;
    state.objects = []; state.history = []; state.selected = null;
    sheet.classList.add("hidden"); sheetStatus.replaceChildren();
    editor.classList.remove("hidden");
    await layout();
    setStatus(status, id === "sign" ? "Draw your signature, then drag it into place." : "Choose a tool, then click or drag on the page.");
    if (id === "sign") { setMode("sign"); }
  }

  // ---------- pages
  async function layout() {
    const avail = Math.min(pagesBox.clientWidth || view.clientWidth || 800, 920);
    state.width = Math.max(260, avail - 4);
    pagesBox.replaceChildren();
    state.pages = [];
    for (let i = 1; i <= state.doc.numPages; i++) {
      const page = await state.doc.getPage(i);
      const canvas = h("canvas");
      const info = await renderInto(canvas, page, state.width);
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "ink");
      svg.setAttribute("viewBox", `0 0 ${info.width} ${info.height}`);
      svg.setAttribute("preserveAspectRatio", "none");
      const layer = h("div", { class: "layer" });
      const el = h("div", { class: "epage", style: `width:${state.width}px;height:${Math.round(info.height * info.scale)}px` }, canvas, svg, layer);
      const p = { index: i - 1, el, layer, svg, ...info };
      state.pages.push(p);
      bindPage(p);
      pagesBox.append(h("div", {}, el, h("div", { class: "pagelabel" }, `Page ${i} of ${state.doc.numPages}`)));
    }
    redrawAll();
  }

  let resizeTimer;
  window.addEventListener("resize", () => {
    if (!state.doc || !document.body.contains(editor)) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (Math.abs(Math.min(pagesBox.clientWidth, 920) - 4 - state.width) > 30) layout(); }, 300);
  });

  // ---------- objects
  function snapshot() {
    state.history.push(JSON.stringify(state.objects));
    if (state.history.length > 100) state.history.shift();
    undoBtn.disabled = false;
  }
  function undo() {
    if (!state.history.length) return;
    state.objects = JSON.parse(state.history.pop());
    select(null);
    redrawAll();
    undoBtn.disabled = !state.history.length;
  }
  function removeSelected() {
    if (!state.selected) return;
    snapshot();
    state.objects = state.objects.filter((o) => o.id !== state.selected);
    select(null);
    redrawAll();
  }
  function applyStyle(change) {
    const o = state.objects.find((x) => x.id === state.selected);
    if (!o) return;
    snapshot();
    if (o.type === "text") Object.assign(o, change);
    else if (o.type === "ink" && change.color) o.color = change.color;
    else if (o.type === "rect" && o.stroke && change.color) o.stroke = change.color;
    redrawAll();
  }
  function select(oid) {
    state.selected = oid;
    delBtn.disabled = !oid;
    for (const p of state.pages) p.layer.querySelectorAll(".obj").forEach((e) => e.classList.toggle("selected", e.dataset.id === String(oid)));
    const o = state.objects.find((x) => x.id === oid);
    if (o?.type === "text") { color.value = o.color; size.value = String(nearest(o.size)); font.value = o.font; }
  }
  const nearest = (s) => SIZES.reduce((a, b) => (Math.abs(b - s) < Math.abs(a - s) ? b : a));

  function redrawAll() {
    for (const p of state.pages) { p.layer.replaceChildren(); p.svg.replaceChildren(); }
    for (const o of state.objects) draw(o);
    select(state.selected && state.objects.some((o) => o.id === state.selected) ? state.selected : null);
  }

  function draw(o) {
    const p = state.pages[o.page];
    if (!p) return;
    if (o.type === "ink") {
      const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      line.setAttribute("points", o.points.map(([x, y]) => `${x * p.width},${y * p.height}`).join(" "));
      line.setAttribute("fill", "none"); line.setAttribute("stroke", o.color); line.setAttribute("stroke-width", o.width);
      line.setAttribute("stroke-linecap", "round"); line.setAttribute("stroke-linejoin", "round");
      p.svg.append(line);
      // an invisible box over the stroke so it can be selected and moved
      const xs = o.points.map((q) => q[0]), ys = o.points.map((q) => q[1]);
      const pad = 0.01;
      const box = h("div", { class: "obj r", "data-id": o.id, style: pos(Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) - Math.min(...xs) + 2 * pad, Math.max(...ys) - Math.min(...ys) + 2 * pad) });
      bindObj(box, o, p);
      p.layer.append(box);
      return;
    }
    let el;
    if (o.type === "text") {
      const [family, weight] = FONTS[o.font] || FONTS.sans;
      el = h("div", { class: "obj t", "data-id": o.id, style: `left:${o.x * 100}%;top:${o.y * 100}%;font-family:'${family}';font-weight:${weight};font-size:${o.size * p.scale}px;color:${o.color}` });
      el.textContent = o.text;
    } else if (o.type === "image") {
      el = h("div", { class: "obj i", "data-id": o.id, style: pos(o.x, o.y, o.w, o.h) }, h("img", { src: o.data, alt: "" }), h("span", { class: "grip", "aria-hidden": "true" }));
    } else if (o.type === "rect") {
      const style = pos(o.x, o.y, o.w, o.h) + (o.fill ? `;background:${hexA(o.fill, o.opacity)}` : "") + (o.stroke ? `;border:${o.stroke_width * p.scale}px solid ${o.stroke}` : "");
      el = h("div", { class: "obj r", "data-id": o.id, style }, h("span", { class: "grip", "aria-hidden": "true" }));
    }
    bindObj(el, o, p);
    p.layer.append(el);
  }
  const pos = (x, y, w, hh) => `left:${x * 100}%;top:${y * 100}%;width:${w * 100}%;height:${hh * 100}%`;
  const hexA = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };

  function frac(p, e) {
    const r = p.layer.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  }

  // move / resize an existing object
  function bindObj(el, o, p) {
    el.addEventListener("pointerdown", (e) => {
      if (state.mode !== "select") return;
      if (el.isContentEditable) return;
      e.stopPropagation();
      e.preventDefault();
      select(o.id);
      const resizing = e.target.classList.contains("grip");
      const [sx, sy] = frac(p, e);
      const start = JSON.parse(JSON.stringify(o));
      let moved = false;
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const [cx, cy] = frac(p, ev);
        const dx = cx - sx, dy = cy - sy;
        if (!moved && Math.hypot(dx, dy) < 0.003) return;
        if (!moved) { snapshot(); moved = true; }
        if (resizing) {
          o.w = Math.max(0.02, start.w + dx);
          o.h = o.type === "image" ? o.w * start.h / start.w : Math.max(0.01, start.h + dy);
        } else if (o.type === "ink") {
          o.points = start.points.map(([x, y]) => [x + dx, y + dy]);
        } else { o.x = start.x + dx; o.y = start.y + dy; }
        redrawAll();
      };
      const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
    });
    if (o.type === "text") el.addEventListener("dblclick", () => editText(el, o));
  }

  function editText(el, o, isNew = false) {
    if (!isNew) snapshot();
    el.contentEditable = "true";
    el.focus();
    const range = document.createRange(); range.selectNodeContents(el);
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    el.addEventListener("blur", () => {
      el.contentEditable = "false";
      o.text = el.innerText.replace(/\n$/, "");
      if (!o.text.trim()) state.objects = state.objects.filter((x) => x !== o);
      redrawAll();
    }, { once: true });
    el.addEventListener("keydown", (e) => { if (e.key === "Escape") el.blur(); });
  }

  // creating new objects on a page
  function bindPage(p) {
    p.layer.addEventListener("pointerdown", (e) => {
      if (e.target !== p.layer) return;
      const [x, y] = frac(p, e);
      if (state.mode === "select") { select(null); return; }
      if (state.mode === "text") {
        e.preventDefault();
        snapshot();
        const o = { id: nextId++, page: p.index, type: "text", x, y, text: "", size: state.size, color: state.color, font: state.font };
        state.objects.push(o);
        draw(o);
        const el = p.layer.querySelector(`[data-id="${o.id}"]`);
        setMode("select");
        select(o.id);
        editText(el, o, true);
        return;
      }
      if (["highlight", "whiteout", "rect", "draw"].includes(state.mode)) {
        e.preventDefault();
        snapshot();
        const style = { highlight: { fill: "#f6e27a", opacity: 0.45 }, whiteout: { fill: "#ffffff", opacity: 1 },
          rect: { stroke: state.color, stroke_width: 2, opacity: 1 } }[state.mode];
        const o = state.mode === "draw"
          ? { id: nextId++, page: p.index, type: "ink", points: [[x, y]], color: state.color, width: 2 }
          : { id: nextId++, page: p.index, type: "rect", x, y, w: 0, h: 0, ...style };
        state.objects.push(o);
        p.layer.setPointerCapture(e.pointerId);
        const move = (ev) => {
          const [cx, cy] = frac(p, ev);
          if (o.type === "ink") o.points.push([cx, cy]);
          else { o.w = Math.abs(cx - x); o.h = Math.abs(cy - y); o.x = Math.min(cx, x); o.y = Math.min(cy, y); }
          redrawAll();
        };
        const up = () => {
          p.layer.removeEventListener("pointermove", move); p.layer.removeEventListener("pointerup", up); p.layer.removeEventListener("pointercancel", up);
          const tiny = o.type === "ink" ? o.points.length < 2 : (o.w < 0.005 || o.h < 0.003);
          if (tiny) { state.objects = state.objects.filter((q) => q !== o); state.history.pop(); undoBtn.disabled = !state.history.length; }
          redrawAll();
        };
        p.layer.addEventListener("pointermove", move);
        p.layer.addEventListener("pointerup", up);
        p.layer.addEventListener("pointercancel", up);
      }
    });
  }

  function addImage(dataUrl, naturalW, naturalH, widthFrac = 0.3) {
    const p = visiblePage();
    const w = widthFrac, hh = w * (naturalH / naturalW) * (p.width / p.height);
    snapshot();
    const o = { id: nextId++, page: p.index, type: "image", x: 0.5 - w / 2, y: 0.5 - hh / 2, w, h: hh, data: dataUrl };
    state.objects.push(o);
    setMode("select");
    redrawAll();
    select(o.id);
    setStatus(status, "Drag the picture into place. Use the round handle to resize it.");
  }
  function visiblePage() {
    const mid = window.innerHeight / 2;
    let best = state.pages[0], dist = Infinity;
    for (const p of state.pages) {
      const r = p.el.getBoundingClientRect();
      const d = Math.abs((r.top + r.bottom) / 2 - mid);
      if (d < dist) { dist = d; best = p; }
    }
    return best;
  }

  imageInput.addEventListener("change", async () => {
    const f = imageInput.files[0];
    imageInput.value = "";
    if (!f) return;
    try { const { url, w, hh } = await shrinkImage(f, 2000, "image/jpeg"); addImage(url, w, hh); }
    catch { setStatus(status, "That picture could not be opened. Use a JPG or PNG.", true); }
  });

  function setMode(m) {
    if (m === "image") { imageInput.click(); return; }
    if (m === "sign") { openSignature(); return; }
    state.mode = m;
    editor.dataset.mode = m;
    modeButtons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
    const tips = { select: "Click something to select it, drag to move it. Double-click text to change it.", text: "Click where the text should start.",
      highlight: "Drag over the part you want to highlight.", whiteout: "Drag over anything you want to hide. Then add new text on top if needed.",
      rect: "Drag to draw a box.", draw: "Draw with your mouse, finger or pen." };
    if (state.doc) setStatus(status, tips[m] || "");
  }

  // ---------- signature
  function openSignature() {
    const pad = h("canvas", { class: "sigpad", "aria-label": "Signature pad" });
    const upload = h("input", { type: "file", accept: "image/png,image/jpeg", class: "hidden" });
    const dlg = h("dialog", {}, h("h2", {}, "Your signature"),
      h("p", { class: "muted" }, "Sign with your mouse, finger or stylus. Or upload a photo of your signature on white paper."),
      h("div", { style: "margin-top:.8rem" }, pad),
      h("div", { class: "dialog-actions" },
        h("button", { class: "btn quiet small", type: "button", onclick: () => clear() }, "Clear"),
        h("button", { class: "btn quiet small", type: "button", onclick: () => upload.click() }, "Upload picture"),
        h("button", { class: "btn quiet small", type: "button", onclick: () => dlg.close() }, "Cancel"),
        h("button", { class: "btn small", type: "button", onclick: () => use() }, "Place signature")), upload);
    document.body.append(dlg);
    dlg.addEventListener("close", () => dlg.remove());
    dlg.showModal();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    pad.width = pad.clientWidth * dpr; pad.height = pad.clientHeight * dpr;
    const ctx = pad.getContext("2d");
    ctx.scale(dpr, dpr); ctx.lineWidth = 3.4; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = state.color === "#1d2b3a" ? "#16247a" : state.color;
    let drawing = false, any = false;
    const pt = (e) => { const r = pad.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    pad.addEventListener("pointerdown", (e) => { drawing = true; any = true; pad.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pt(e)); });
    pad.addEventListener("pointermove", (e) => { if (!drawing) return; ctx.lineTo(...pt(e)); ctx.stroke(); });
    pad.addEventListener("pointerup", () => { drawing = false; });
    const clear = () => { ctx.clearRect(0, 0, pad.width, pad.height); any = false; };
    const use = () => {
      if (!any) return;
      const out = trim(pad);
      dlg.close();
      if (out) addImage(out.url, out.w, out.h, 0.28);
    };
    upload.addEventListener("change", async () => {
      const f = upload.files[0];
      if (!f) return;
      try {
        const { url, w, hh } = await shrinkImage(f, 1200, "image/png", true);
        dlg.close();
        addImage(url, w, hh, 0.28);
      } catch { /* ignore unreadable file */ }
    });
  }

  // ---------- save
  save.addEventListener("click", async () => {
    document.activeElement?.blur?.();
    if (!state.objects.length) return setStatus(status, "Add something to the page first.", true);
    const ops = state.objects.map((o) => {
      const { id: _id, ...rest } = o;
      return o.type === "image" ? { ...rest, page: o.page } : rest;
    });
    const form = new FormData();
    form.append("file", state.file);
    form.append("options", JSON.stringify({ ops }));
    await submit({ url: "/api/pdf/edit", form, button: save, status, result, doneTitle: id === "sign" ? "Signed" : "Saved" });
  });

  document.addEventListener("keydown", (e) => {
    if (!document.body.contains(editor) || editor.classList.contains("hidden")) return;
    if (document.activeElement?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
    if ((e.key === "Delete" || e.key === "Backspace") && state.selected) { e.preventDefault(); removeSelected(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
  });

  view.replaceChildren(toolHead(tool.title, tool.blurb), sheet, sheetStatus, editor, imageInput);
}

// Downscale a picture and return it as a data URL (keeps uploads small).
function shrinkImage(file, maxSide, type, whiteToClear = false) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
      const w = Math.round(img.naturalWidth * k), hh = Math.round(img.naturalHeight * k);
      const c = document.createElement("canvas");
      c.width = w; c.height = hh;
      const ctx = c.getContext("2d");
      if (type === "image/jpeg") { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, hh); }
      ctx.drawImage(img, 0, 0, w, hh);
      if (whiteToClear) {          // photo of a signature: make the paper transparent
        const d = ctx.getImageData(0, 0, w, hh);
        for (let i = 0; i < d.data.length; i += 4) {
          const lum = 0.3 * d.data[i] + 0.59 * d.data[i + 1] + 0.11 * d.data[i + 2];
          if (lum > 190) d.data[i + 3] = 0;
        }
        ctx.putImageData(d, 0, 0);
      }
      URL.revokeObjectURL(url);
      resolve({ url: c.toDataURL(type, 0.9), w, hh });
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("bad image")); };
    img.src = url;
  });
}

// Crop a signature drawing to the strokes.
function trim(canvas) {
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  const d = ctx.getImageData(0, 0, width, height).data;
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (d[(y * width + x) * 4 + 3] > 10) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  }
  if (x1 < 0) return null;
  const pad = 6;
  x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(width - 1, x1 + pad); y1 = Math.min(height - 1, y1 + pad);
  const out = document.createElement("canvas");
  out.width = x1 - x0 + 1; out.height = y1 - y0 + 1;
  out.getContext("2d").drawImage(canvas, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
  return { url: out.toDataURL("image/png"), w: out.width, h: out.height };
}
