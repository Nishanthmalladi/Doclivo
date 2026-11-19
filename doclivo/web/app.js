// Doclivo front end: router, home page, and the shared tool flow.
import { h, fmtSize, send, showResult, setStatus } from "./ui.js";

let caps = null;
const view = document.getElementById("view");

// Format families shown in the conversion table. kind = server-side group.
export const FAMILIES = {
  word: { label: "Word", code: "DOC", tile: "word", kind: "document", accept: ["doc", "docx", "odt", "rtf", "txt", "html", "htm"] },
  powerpoint: { label: "PowerPoint", code: "PPT", tile: "ppt", kind: "presentation", accept: ["ppt", "pptx", "odp", "pps", "ppsx"] },
  excel: { label: "Excel", code: "XLS", tile: "xls", kind: "spreadsheet", accept: ["xls", "xlsx", "ods", "csv"] },
  pdf: { label: "PDF", code: "PDF", tile: "pdf", kind: "pdf", accept: ["pdf"] },
  image: { label: "Image", code: "IMG", tile: "img", kind: "image", accept: ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif"] },
};
const COLUMNS = [
  { label: "PDF", target: () => "pdf" },
  { label: "Word", target: () => "docx", family: "word" },
  { label: "PowerPoint", target: () => "pptx", family: "powerpoint" },
  { label: "Excel", target: () => "xlsx", family: "excel" },
  { label: "JPG", target: () => "jpg" },
  { label: "PNG", target: () => "png" },
  { label: "Text", target: () => "txt" },
  { label: "OpenDocument", target: (k) => ({ document: "odt", presentation: "odp", spreadsheet: "ods", pdf: "odt" })[k] },
];
const TILE_FOR_TARGET = { pdf: "pdf", docx: "word", doc: "word", odt: "odf", rtf: "word", txt: "txt", html: "txt",
  pptx: "ppt", ppt: "ppt", odp: "odf", xlsx: "xls", xls: "xls", ods: "odf", csv: "xls", jpg: "img", png: "img", webp: "img" };
const SHORT = { pdf: "PDF", docx: "Word", doc: "Word 97", odt: "ODT", rtf: "RTF", txt: "Text", html: "HTML", pptx: "PowerPoint",
  ppt: "PPT 97", odp: "ODP", xlsx: "Excel", xls: "XLS 97", ods: "ODS", csv: "CSV", jpg: "JPG", png: "PNG", webp: "WebP" };

export const TOOLS = {
  merge: { group: "Arrange pages", title: "Merge PDFs", blurb: "Combine several PDFs into one, in the order you choose.",
    multiple: true, min: 2, action: "Merge PDFs", endpoint: "/api/pdf/merge", field: "files" },
  split: { group: "Arrange pages", title: "Split PDF", blurb: "Cut a PDF into separate files by page range, or pull out the pages you need.",
    action: "Split PDF", endpoint: "/api/pdf/split", options: [
      { name: "mode", type: "choice", label: "How to split", value: "ranges", choices: [["ranges", "By ranges"], ["every", "Every page"], ["extract", "Extract pages into one file"]] },
      { name: "ranges", type: "text", label: "Pages", value: "1-2", help: "For example 1-3, 5, 8- (8- means page 8 to the end).", showIf: (v) => v.mode !== "every" }] },
  organize: { group: "Arrange pages", title: "Organize pages", blurb: "Reorder, rotate, duplicate or delete pages, then save.", custom: "organize" },
  rotate: { group: "Arrange pages", title: "Rotate PDF", blurb: "Turn every page, or only the ones that are sideways.", custom: "rotate" },
  edit: { group: "Mark up", title: "Edit PDF", blurb: "Add text, pictures, highlights, white-out, shapes and drawings anywhere on the page.", custom: "edit" },
  sign: { group: "Mark up", title: "Sign PDF", blurb: "Draw or upload your signature and place it on the page.", custom: "sign" },
  watermark: { group: "Mark up", title: "Add watermark", blurb: "Stamp text such as CONFIDENTIAL or DRAFT across every page.",
    action: "Add watermark", endpoint: "/api/pdf/watermark", options: [
      { name: "text", type: "text", label: "Watermark text", value: "CONFIDENTIAL" },
      { name: "layout", type: "choice", label: "Layout", value: "center", choices: [["center", "Once, in the middle"], ["tiled", "Repeated across the page"]] },
      { name: "size", type: "range", label: "Size", value: 54, min: 12, max: 140 },
      { name: "opacity", type: "range", label: "Opacity", value: 0.25, min: 0.05, max: 1, step: 0.05 },
      { name: "angle", type: "choice", label: "Angle", value: "45", choices: [["0", "Flat"], ["45", "Diagonal"], ["90", "Upright"]] },
      { name: "color", type: "color", label: "Colour", value: "#b3261e" }] },
  "remove-watermark": { group: "Mark up", title: "Remove watermark", blurb: "Take watermarks such as DRAFT or CONFIDENTIAL off a PDF or Word file. Use it on documents you own or have permission to change.",
    action: "Remove watermark", endpoint: "/api/remove-watermark", accept: ["pdf", "docx", "doc"], options: [
      { name: "text", type: "text", label: "Watermark text (optional)", value: "", help: "We find most watermarks on our own. If one is missed, type its exact words, e.g. DRAFT." }] },
  "page-numbers": { group: "Mark up", title: "Add page numbers", blurb: "Number every page, in the position and style you want.",
    action: "Add page numbers", endpoint: "/api/pdf/page-numbers", options: [
      { name: "position", type: "select", label: "Position", value: "bottom-center", choices: [["bottom-center", "Bottom centre"], ["bottom-right", "Bottom right"], ["bottom-left", "Bottom left"], ["top-center", "Top centre"], ["top-right", "Top right"], ["top-left", "Top left"]] },
      { name: "format", type: "select", label: "Style", value: "n", choices: [["n", "1"], ["page-n", "Page 1"], ["n-of-total", "1 / 10"], ["page-n-of-total", "Page 1 of 10"]] },
      { name: "start", type: "number", label: "First number", value: 1, min: 0, max: 100000 },
      { name: "size", type: "number", label: "Text size", value: 11, min: 6, max: 48 },
      { name: "skip_first", type: "check", label: "Leave the first page (cover) unnumbered", value: false }] },
  compress: { group: "Shrink and secure", title: "Compress PDF", blurb: "Make a PDF smaller for email and upload limits.",
    action: "Compress PDF", endpoint: "/api/pdf/compress", options: [
      { name: "level", type: "choice", label: "How much", value: "medium", choices: [["low", "A little (best quality)"], ["medium", "Recommended"], ["high", "As small as possible"]] }] },
  protect: { group: "Shrink and secure", title: "Protect PDF", blurb: "Lock a PDF with a password so only people who know it can open it.",
    action: "Protect PDF", endpoint: "/api/pdf/protect", options: [
      { name: "password", type: "password", label: "Password", value: "" },
      { name: "confirm", type: "password", label: "Type it again", value: "", local: true }],
    validate: (v) => v.password.length < 4 ? "Use at least 4 characters." : v.password !== v.confirm ? "The two passwords are different." : null },
  unlock: { group: "Shrink and secure", title: "Unlock PDF", blurb: "Remove the password from a PDF you are allowed to open.",
    action: "Unlock PDF", endpoint: "/api/pdf/unlock", options: [{ name: "password", type: "password", label: "Current password", value: "" }] },
  ocr: { group: "Shrink and secure", title: "Make scanned PDF searchable", blurb: "Recognise the text in a scanned PDF so you can search, select and copy it.",
    action: "Recognise text", endpoint: "/api/pdf/ocr", needs: "ocr", options: [{ name: "lang", type: "lang", label: "Language of the document", value: "eng" }] },
};
const OCR_NAMES = { eng: "English", hin: "Hindi", tel: "Telugu", tam: "Tamil", kan: "Kannada", mal: "Malayalam", mar: "Marathi",
  ben: "Bengali", guj: "Gujarati", pan: "Punjabi", urd: "Urdu", ara: "Arabic", chi_sim: "Chinese (simplified)",
  chi_tra: "Chinese (traditional)", deu: "German", fra: "French", spa: "Spanish", ita: "Italian", jpn: "Japanese",
  kor: "Korean", por: "Portuguese", rus: "Russian", nld: "Dutch", tur: "Turkish", vie: "Vietnamese", tha: "Thai" };

// ---------------------------------------------------------------- router
async function route() {
  if (!caps) {
    try { caps = await (await fetch("/api/capabilities")).json(); }
    catch { view.replaceChildren(h("p", { class: "status error" }, "Could not reach the server. Check your connection and reload.")); return; }
    if (caps.source_url) { const a = document.getElementById("source-link"); a.href = caps.source_url; a.classList.remove("hidden"); }
  }
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(query || "");
  const parts = path.split("/").filter(Boolean);
  document.querySelectorAll("header.site nav a").forEach((a) => a.removeAttribute("aria-current"));
  const nav = (n) => document.querySelector(`[data-nav="${n}"]`)?.setAttribute("aria-current", "page");
  window.scrollTo(0, 0);
  if (!parts.length) { nav("home"); renderHome(); }
  else if (parts[0] === "convert") { nav("convert"); renderConvert(params.get("from"), params.get("to")); }
  else if (parts[0] === "tool" && TOOLS[parts[1]]) { if (parts[1] === "edit") nav("edit"); renderTool(parts[1]); }
  else if (parts[0] === "privacy") renderPrivacy();
  else renderHome();
  view.focus({ preventScroll: true });
}
window.addEventListener("hashchange", route);
route();

// ---------------------------------------------------------------- home
function dropSheet({ big, hint, accept, multiple, onFiles, compact }) {
  const input = h("input", { type: "file", accept: accept ? accept.map((e) => "." + e).join(",") : "", multiple: !!multiple, "aria-label": big });
  const sheet = h("label", { class: "sheet" + (compact ? " compact" : "") }, input,
    h("span", { class: "big" }, big), h("span", { class: "btn" }, multiple ? "Choose files" : "Choose file"),
    h("span", { class: "hint" }, hint));
  input.addEventListener("change", () => { if (input.files.length) onFiles([...input.files]); input.value = ""; });
  for (const ev of ["dragenter", "dragover"]) sheet.addEventListener(ev, (e) => { e.preventDefault(); sheet.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) sheet.addEventListener(ev, () => sheet.classList.remove("over"));
  sheet.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); });
  return sheet;
}

let pendingFiles = null;      // files dropped on the home page, handed to the converter

function renderHome() {
  document.title = "Doclivo — convert and edit PDF, Word, PowerPoint and Excel files for free";
  const L = caps.limits;
  const hero = h("section", { class: "hero" },
    h("div", {},
      h("h1", {}, "Drop a file. Get the format you need."),
      h("p", { class: "lede" }, "Word, PowerPoint, Excel, PDF and images, converted in any direction. Then merge, split, sign or edit the PDF. Free, no account."),
      h("div", { class: "formats-line", "aria-hidden": "true" },
        ...["word:DOCX", "ppt:PPTX", "xls:XLSX", "pdf:PDF", "img:JPG", "img:PNG", "odf:ODT", "txt:TXT"].map((s) => { const [c, t] = s.split(":"); return h("span", { class: "ft " + c }, t); }))),
    dropSheet({ big: "Drop any file here", hint: `Up to ${L.max_file_mb} MB. We work out what it can become.`, multiple: true,
      onFiles: (files) => { pendingFiles = files; location.hash = "#/convert"; } }));

  // conversion table
  const thead = h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "From ↓  To →"), ...COLUMNS.map((c) => h("th", { scope: "col" }, c.label))));
  const tbody = h("tbody");
  const list = h("div", { class: "matrix-list" });
  for (const [fid, fam] of Object.entries(FAMILIES)) {
    const row = h("tr", {}, h("th", { scope: "row" }, h("span", { class: "ft " + fam.tile }, fam.code), fam.label));
    const links = h("div", { class: "links" });
    for (const col of COLUMNS) {
      const target = col.target(fam.kind);
      const ok = target && caps.targets[fam.kind].includes(target) && col.family !== fid;
      if (ok) {
        const href = `#/convert?from=${fid}&to=${target}`;
        const label = `${fam.label} to ${col.label}`;
        row.append(h("td", {}, h("a", { href, "aria-label": label }, SHORT[target])));
        links.append(h("a", { href }, `to ${col.label}`));
      } else row.append(h("td", { class: "na" }));
    }
    tbody.append(row);
    list.append(h("div", { class: "row" }, h("h3", {}, h("span", { class: "ft " + fam.tile }, fam.code), fam.label), links));
  }
  const convert = h("section", { class: "block", id: "convert" },
    h("h2", {}, "Convert"),
    h("p", { class: "sub" }, "Pick where your file is coming from and where it needs to go. Need something less common, like .doc to .docx or Excel to CSV? Use ", h("a", { href: "#/convert" }, "the converter"), " and it lists every option for your file."),
    h("div", { class: "matrix-wrap" }, h("table", { class: "matrix" }, thead, tbody)), list);

  const groups = {};
  for (const [id, t] of Object.entries(TOOLS)) {
    if (t.needs === "ocr" && !caps.ocr) continue;
    (groups[t.group] ||= []).push(h("li", {}, h("a", { href: `#/tool/${id}` }, h("strong", {}, t.title), h("span", {}, t.blurb))));
  }
  const tools = h("section", { class: "block" }, h("h2", {}, "PDF tools"),
    h("p", { class: "sub" }, "Everything you would otherwise do at a print shop counter."),
    h("div", { class: "toolgroups" }, ...Object.entries(groups).map(([g, items]) => h("div", { class: "toolgroup" }, h("h3", {}, g), h("ul", {}, ...items)))));
  view.replaceChildren(hero, convert, tools);
}

// ---------------------------------------------------------------- shared tool scaffolding
function toolHead(title, blurb, tiles) {
  return h("div", { class: "tool-head" }, h("a", { class: "back", href: "#/" }, "All tools"),
    h("h1", {}, ...(tiles || []), title), h("p", {}, blurb));
}

export function extOf(name) { return (name.split(".").pop() || "").toLowerCase(); }
export function kindOf(ext) {
  for (const fam of Object.values(FAMILIES)) if (fam.accept.includes(ext)) return fam.kind;
  return null;
}

function fileList(files, { reorder, onChange }) {
  const ul = h("ul", { class: "filelist" });
  const draw = () => {
    ul.replaceChildren(...files.map((f, i) => {
      const acts = h("div", { class: "acts" });
      if (reorder) {
        acts.append(h("button", { class: "iconbtn", type: "button", title: "Move up", "aria-label": `Move ${f.name} up`, disabled: i === 0, onclick: () => { [files[i - 1], files[i]] = [files[i], files[i - 1]]; draw(); onChange(); } }, "↑"),
          h("button", { class: "iconbtn", type: "button", title: "Move down", "aria-label": `Move ${f.name} down`, disabled: i === files.length - 1, onclick: () => { [files[i + 1], files[i]] = [files[i], files[i + 1]]; draw(); onChange(); } }, "↓"));
      }
      acts.append(h("button", { class: "iconbtn", type: "button", title: "Remove", "aria-label": `Remove ${f.name}`, onclick: () => { files.splice(i, 1); draw(); onChange(); } }, "✕"));
      const ext = extOf(f.name);
      const tile = h("span", { class: "ft " + (TILE_FOR_TARGET[ext === "jpeg" ? "jpg" : ext] || ({ heic: "img", heif: "img", gif: "img", bmp: "img", tif: "img", tiff: "img", pps: "ppt", ppsx: "ppt", htm: "txt" })[ext] || "txt") }, ext.toUpperCase().slice(0, 4));
      return h("li", {}, tile, h("div", {}, h("div", { class: "name" }, f.name), h("div", { class: "size" }, fmtSize(f.size))), acts);
    }));
  };
  draw();
  return ul;
}

function buildOptions(specs, values, onChange) {
  const box = h("div");
  const draw = () => {
    box.replaceChildren();
    for (const o of specs) {
      if (o.showIf && !o.showIf(values)) continue;
      const id = "opt-" + o.name;
      let control;
      const set = (v) => { values[o.name] = v; onChange?.(o); };
      if (o.type === "choice") {
        control = h("div", { class: "choice", role: "radiogroup", "aria-label": o.label }, ...o.choices.map(([v, label]) => {
          const input = h("input", { type: "radio", name: id, value: v, checked: String(values[o.name]) === v });
          input.addEventListener("change", () => { set(v); draw(); });
          return h("label", {}, input, h("span", {}, label));
        }));
        box.append(h("div", { class: "field" }, h("span", { class: "label" }, o.label), control));
        continue;
      }
      if (o.type === "select" || o.type === "lang") {
        const choices = o.type === "lang" ? caps.ocr_langs.map((l) => [l, OCR_NAMES[l] || l]).sort((a, b) => a[1].localeCompare(b[1])) : o.choices;
        control = h("select", { id }, ...choices.map(([v, label]) => h("option", { value: v, selected: String(values[o.name]) === v }, label)));
        control.addEventListener("change", () => set(control.value));
      } else if (o.type === "check") {
        control = h("input", { id, type: "checkbox", checked: !!values[o.name] });
        control.addEventListener("change", () => set(control.checked));
        box.append(h("div", { class: "field check" }, control, h("label", { for: id }, o.label)));
        continue;
      } else if (o.type === "range") {
        const out = h("span", { class: "help" }, String(values[o.name]));
        control = h("input", { id, type: "range", min: o.min, max: o.max, step: o.step || 1, value: values[o.name] });
        control.addEventListener("input", () => { out.textContent = control.value; set(Number(control.value)); });
        box.append(h("div", { class: "field" }, h("label", { for: id }, o.label), control, out));
        continue;
      } else {
        const type = { number: "number", password: "password", color: "color" }[o.type] || "text";
        control = h("input", { id, type, value: values[o.name], min: o.min, max: o.max, autocomplete: o.type === "password" ? "new-password" : "off" });
        control.addEventListener("input", () => set(type === "number" ? Number(control.value) : control.value));
      }
      box.append(h("div", { class: "field" }, h("label", { for: id }, o.label), control, o.help ? h("span", { class: "help" }, o.help) : null));
    }
  };
  draw();
  return box;
}

// ---------------------------------------------------------------- converter
function renderConvert(from, to) {
  const fam = FAMILIES[from];
  const title = fam && to ? `${fam.label} to ${SHORT[to] || to.toUpperCase()}` : "Convert a file";
  document.title = `${title} — Doclivo`;
  const tiles = fam && to ? [h("span", { class: "ft " + fam.tile }, fam.code), h("span", { "aria-hidden": "true" }, "→"), h("span", { class: "ft " + TILE_FOR_TARGET[to] }, (SHORT[to] || to).slice(0, 4).toUpperCase())] : [];
  const blurb = fam && to ? blurbFor(fam.kind, to) : "Add a Word, PowerPoint, Excel, PDF or image file and choose what it should become.";
  const files = pendingFiles || [];
  pendingFiles = null;
  const values = { target: to || "", ppt_word: "layout", page_size: "fit", orientation: "auto", margin: 0, dpi: 150, lang: "eng", remove_watermark: false, watermark_text: "" };
  const accept = fam ? fam.accept : Object.values(FAMILIES).flatMap((f) => f.accept);

  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  const optionsBox = h("div");
  const go = h("button", { class: "btn", type: "button" }, "Convert");
  const result = h("div");
  const listHolder = h("div");
  const panel = h("aside", { class: "panel" }, h("h2", {}, "Convert to"), optionsBox, go, status);

  const refresh = () => {
    listHolder.replaceChildren(files.length ? fileList(files, { reorder: true, onChange: refresh }) : "");
    const kinds = [...new Set(files.map((f) => kindOf(extOf(f.name))))];
    optionsBox.replaceChildren();
    if (!files.length) { optionsBox.append(h("p", { class: "muted" }, "Add a file to see what it can become.")); go.disabled = true; return; }
    if (kinds.includes(null)) { optionsBox.append(h("p", { class: "status error" }, "One of these files is a type we cannot convert. Remove it to continue.")); go.disabled = true; return; }
    // Offer every format that at least one of the files can become; files that
    // can't are passed through (same format) or listed as skipped.
    const canBe = (f, t) => { const e = extOf(f.name).replace("jpeg", "jpg"); return e === t || caps.targets[kindOf(e)].includes(t); };
    const all = [...new Set(kinds.flatMap((k) => caps.targets[k]))];
    let targets = all.filter((t) => files.some((f) => canBe(f, t) && extOf(f.name).replace("jpeg", "jpg") !== t));
    if (!targets.length) { optionsBox.append(h("p", { class: "status error" }, "These files are already in every format they can be converted to.")); go.disabled = true; return; }
    if (!targets.includes(values.target)) values.target = targets.includes("pdf") ? "pdf" : targets[0];
    const skipped = files.filter((f) => !canBe(f, values.target));
    const unchanged = files.filter((f) => extOf(f.name).replace("jpeg", "jpg") === values.target);
    const select = h("select", { id: "target" }, ...targets.map((t) => h("option", { value: t, selected: t === values.target }, caps.labels[t] || t)));
    select.addEventListener("change", () => { values.target = select.value; refresh(); });
    optionsBox.append(h("div", { class: "field" }, h("label", { for: "target" }, "Format"), select));
    if (files.length > 1) {
      const will = files.length - skipped.length;
      optionsBox.append(h("p", { class: "help muted" }, `${will} of ${files.length} files will be converted and returned together in one zip file.`));
      if (unchanged.length) optionsBox.append(h("p", { class: "help muted" }, `Already ${SHORT[values.target] || values.target.toUpperCase()}, included as they are: ${unchanged.map((f) => f.name).join(", ")}.`));
      if (skipped.length) optionsBox.append(h("p", { class: "help", style: "color:var(--bad)" }, `Can't become ${SHORT[values.target] || values.target.toUpperCase()}, will be skipped: ${skipped.map((f) => f.name).join(", ")}.`));
    }
    const extra = [];
    if (kinds.every((k) => k === "image") && values.target === "pdf") {
      extra.push({ name: "page_size", type: "select", label: "Page size", choices: [["fit", "Same as the image"], ["a4", "A4"], ["letter", "US Letter"]] },
        { name: "orientation", type: "select", label: "Orientation", choices: [["auto", "Automatic"], ["portrait", "Portrait"], ["landscape", "Landscape"]], showIf: (v) => v.page_size !== "fit" },
        { name: "margin", type: "select", label: "Margin", choices: [["0", "None"], ["18", "Small"], ["36", "Large"]] });
      if (files.length > 1) optionsBox.append(h("p", { class: "help muted" }, "All images go into one PDF, one page each, in the order shown. To get one PDF per image, convert them separately."));
    }
    if (["jpg", "png"].includes(values.target) && kinds.some((k) => k !== "image"))
      extra.push({ name: "dpi", type: "select", label: "Image quality", choices: [["100", "Normal (100 dpi)"], ["150", "Good (150 dpi)"], ["300", "Print (300 dpi)"]] });
    if (values.target === "txt" && kinds.includes("pdf") && caps.ocr)
      extra.push({ name: "lang", type: "lang", label: "Language, if the PDF is scanned" });
    if (kinds.includes("pdf") && ["docx", "odt"].includes(values.target)) {
      optionsBox.append(h("p", { class: "help muted" }, `Text, tables and pictures are rebuilt as editable Word content. Up to ${caps.limits.max_pages_docx} pages.`));
      extra.push({ name: "remove_watermark", type: "check", label: "Remove the watermark first" },
        { name: "watermark_text", type: "text", label: "Watermark text (optional)", help: "Only needed if a watermark is left behind.", showIf: (v) => v.remove_watermark });
    }
    if (kinds.includes("presentation") && values.target === "docx") {
      extra.push({ name: "ppt_word", type: "choice", label: "What the Word file should look like", choices: [
        ["layout", "Like the slides (one slide per page)"], ["outline", "A clean document (titles, points, tables, pictures, notes)"]] });
    }
    if (kinds.includes("pdf") && values.target === "pptx")
      optionsBox.append(h("p", { class: "help muted" }, "Each page becomes one slide as a picture, with the page's text in the speaker notes."));
    for (const o of extra) if (o.type !== "check") values[o.name] = String(values[o.name] ?? "");
    // typing in a text box must not redraw the form (that would lose the cursor)
    optionsBox.append(buildOptions(extra, values, (o) => { if (o && o.type !== "text" && extra.some((x) => x.showIf)) refresh(); }));
    go.textContent = files.length > 1 ? `Convert ${files.length - skipped.length} files to ${SHORT[values.target] || values.target.toUpperCase()}` : `Convert to ${SHORT[values.target] || values.target.toUpperCase()}`;
    go.disabled = false;
  };

  const add = (newFiles) => { files.push(...newFiles); result.replaceChildren(); refresh(); };
  go.addEventListener("click", async () => {
    const opts = { combine: true };
    for (const k of ["page_size", "orientation", "margin", "dpi", "lang", "remove_watermark", "watermark_text", "ppt_word"]) opts[k] = values[k];
    opts.margin = Number(opts.margin); opts.dpi = Number(opts.dpi);
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("target", values.target);
    form.append("options", JSON.stringify(opts));
    await submit({ url: "/api/convert", form, button: go, status, result, doneTitle: "Converted",
      describe: (xhr) => {
        const n = Number(xhr.getResponseHeader("X-Converted")), failed = Number(xhr.getResponseHeader("X-Failed"));
        if (!n) return null;
        return failed ? `${n} files converted. ${failed} could not be and are listed in NOT-CONVERTED.txt inside the zip.` : `${n} files converted, all in one zip.`;
      } });
  });

  view.replaceChildren(toolHead(title, blurb, tiles),
    h("div", { class: "workspace" },
      h("div", {}, dropSheet({ big: files.length ? "Add more files" : "Drop your file here", hint: hintFor(accept), accept, multiple: true, onFiles: add, compact: true }), listHolder, result),
      panel));
  refresh();
}

function hintFor(accept) {
  return `${accept.filter((e) => !["htm", "jpeg", "tif", "heif", "pps"].includes(e)).map((e) => "." + e).join(" ")} · up to ${caps.limits.max_file_mb} MB each`;
}

function blurbFor(kind, to) {
  const k = { document: "document", presentation: "presentation", spreadsheet: "spreadsheet", pdf: "PDF", image: "image" }[kind];
  if (kind === "pdf" && to === "docx") return "Turn a PDF back into an editable Word document, with its text, tables and pictures.";
  if (kind === "presentation" && to === "docx") return "Turn a presentation into a Word document: either pages that look like the slides, or a clean document you can edit.";
  if (kind === "image" && to === "pdf") return "Put one or more photos or scans into a PDF, one page each.";
  if (to === "pdf") return `Make a PDF from your ${k} that looks the same on every phone and computer.`;
  if (["jpg", "png"].includes(to)) return `Save every page of your ${k} as a picture.`;
  return `Convert your ${k} to ${SHORT[to] || to}.`;
}

// ---------------------------------------------------------------- PDF tools
function renderTool(id) {
  const tool = TOOLS[id];
  document.title = `${tool.title} — Doclivo`;
  if (tool.custom) {
    view.replaceChildren(toolHead(tool.title, tool.blurb), h("p", { class: "muted" }, "Loading…"));
    const mod = tool.custom === "edit" || tool.custom === "sign" ? import("./editor.js") : import("./organize.js");
    mod.then((m) => m.mount(view, { tool, id, caps, toolHead, dropSheet, submit, hintFor }))
      .catch(() => setStatus(view.lastChild, "This tool could not load. Reload the page.", true));
    return;
  }
  const files = [];
  const values = Object.fromEntries((tool.options || []).map((o) => [o.name, o.value]));
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  const go = h("button", { class: "btn", type: "button", disabled: true }, tool.action);
  const result = h("div");
  const listHolder = h("div");
  const refresh = () => {
    listHolder.replaceChildren(files.length ? fileList(files, { reorder: !!tool.multiple, onChange: refresh }) : "");
    go.disabled = files.length < (tool.min || 1);
    if (tool.multiple && files.length === 1) setStatus(status, "Add at least one more PDF.");
    else if (status.textContent.startsWith("Add at least")) setStatus(status, "");
  };
  const accept = tool.accept || ["pdf"];
  const kindsText = accept.length === 1 ? "PDF" : "PDF or Word";
  const add = (newFiles) => {
    const bad = newFiles.filter((f) => !accept.includes(extOf(f.name)));
    if (bad.length) setStatus(status, `${bad.map((f) => f.name).join(", ")}: this tool only works with ${kindsText} files.`, true);
    else setStatus(status, "");
    const good = newFiles.filter((f) => accept.includes(extOf(f.name)));
    if (!tool.multiple) files.splice(0, files.length, ...good.slice(0, 1)); else files.push(...good);
    result.replaceChildren();
    refresh();
  };
  go.addEventListener("click", async () => {
    const problem = tool.validate?.(values);
    if (problem) return setStatus(status, problem, true);
    const form = new FormData();
    if (tool.multiple) files.forEach((f) => form.append("files", f)); else form.append("file", files[0]);
    const opts = Object.fromEntries(Object.entries(values).filter(([k]) => !(tool.options || []).find((o) => o.name === k)?.local));
    if ("angle" in opts) opts.angle = Number(opts.angle);
    form.append("options", JSON.stringify(opts));
    await submit({ url: tool.endpoint, form, button: go, status, result, doneTitle: "Done",
      describe: id === "compress" ? (xhr) => {
        const b = Number(xhr.getResponseHeader("X-Before")), a = Number(xhr.getResponseHeader("X-After"));
        if (!b) return null;
        return a < b ? `${fmtSize(b)} → ${fmtSize(a)}, ${Math.round((1 - a / b) * 100)}% smaller.` : "This PDF is already as small as we can make it, so it is unchanged.";
      } : id === "remove-watermark" ? (xhr) => {
        const n = Number(xhr.getResponseHeader("X-Removed"));
        return n ? `Removed ${n} watermark ${n === 1 ? "item" : "items"}. Check the file: anything that was part of a scanned picture stays.` : null;
      } : null });
  });
  const panel = h("aside", { class: "panel" }, h("h2", {}, "Options"), tool.options ? buildOptions(tool.options, values) : h("p", { class: "muted" }, "Put the files in the order you want, then merge."), go, status);
  view.replaceChildren(toolHead(tool.title, tool.blurb),
    h("div", { class: "workspace" },
      h("div", {}, dropSheet({ big: tool.multiple ? "Drop your PDFs here" : `Drop your ${kindsText} file here`, hint: `${accept.map((e) => "." + e).join(" ")} · up to ${caps.limits.max_file_mb} MB`, accept, multiple: !!tool.multiple, onFiles: add, compact: true }), listHolder, result),
      panel));
}

export async function submit({ url, form, button, status, result, doneTitle, describe }) {
  button.disabled = true;
  result.replaceChildren();
  const bar = h("div", { class: "progress" }, h("i"));
  status.replaceChildren(h("span", {}, "Uploading…"), bar);
  status.classList.remove("error");
  try {
    const { blob, filename, xhr } = await send(url, form, (p) => {
      if (p < 1) { bar.firstChild.style.width = Math.round(p * 100) + "%"; status.firstChild.textContent = `Uploading… ${Math.round(p * 100)}%`; }
      else { bar.classList.add("busy"); status.firstChild.textContent = "Working on it. Large files can take a minute."; }
    });
    status.replaceChildren();
    showResult(result, { blob, filename, title: doneTitle, note: describe?.(xhr) });
  } catch (e) {
    setStatus(status, e.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderPrivacy() {
  document.title = "Privacy — Doclivo";
  view.replaceChildren(h("div", { class: "prose" },
    h("h1", {}, "Privacy"),
    h("p", {}, "Doclivo needs your file on its server only for as long as it takes to convert or change it."),
    h("h2", {}, "What happens to your files"),
    h("p", {}, "Each upload goes into its own temporary folder. As soon as the result has been sent back to you, the folder and everything in it is deleted. If something goes wrong part-way, a clean-up job deletes leftovers within 30 minutes."),
    h("p", {}, "Previews in Organize pages, Rotate, Edit and Sign are drawn in your own browser. The file is only uploaded when you press Save."),
    h("h2", {}, "What we do not do"),
    h("p", {}, "There are no accounts, no tracking cookies and no advertising. Files are never looked at, kept, or shared."),
    h("h2", {}, "Limits"),
    h("p", {}, `Files can be up to ${caps.limits.max_file_mb} MB each. To keep the service free and fair for everyone, each network can make a limited number of requests per minute.`)));
}
