// Organize pages and Rotate PDF: page thumbnails you can reorder, rotate, copy and delete.
import { h, setStatus } from "./ui.js";
import { openPdf, renderInto } from "./pdfview.js";

export function mount(view, { tool, id, caps, toolHead, dropSheet, submit }) {
  const rotateOnly = id === "rotate";
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  const result = h("div");
  const grid = h("div", { class: "pages", role: "list" });
  const bar = h("div", { class: "toolbar-row" });
  const save = h("button", { class: "btn", type: "button" }, rotateOnly ? "Save rotated PDF" : "Save PDF");
  const work = h("div", { class: "hidden" }, bar, grid, h("div", { class: "toolbar-row", style: "margin-top:1.2rem" }, save), status, result);
  let file = null, pages = [], thumbs = [];

  const sheet = dropSheet({ big: "Drop your PDF here", hint: `.pdf · up to ${caps.limits.max_file_mb} MB`, accept: ["pdf"], compact: true,
    onFiles: async (files) => {
      const f = files[0];
      if (!f.name.toLowerCase().endsWith(".pdf")) return setStatus(status, "Choose a PDF file.", true);
      setStatus(status, "Opening…");
      work.classList.remove("hidden");
      try {
        const doc = await openPdf(f);
        if (doc.numPages > caps.limits.max_pages) throw new Error(`This PDF has ${doc.numPages} pages; the limit is ${caps.limits.max_pages}.`);
        file = f;
        thumbs = [];
        for (let i = 1; i <= doc.numPages; i++) {
          const c = document.createElement("canvas");
          await renderInto(c, await doc.getPage(i), 130);
          thumbs.push(c);
        }
        pages = thumbs.map((_, i) => ({ src: i, rotate: 0 }));
        sheet.classList.add("hidden");
        setStatus(status, rotateOnly ? "Rotate pages one by one, or all at once." : "Drag pages to reorder them, or use the arrow buttons.");
        result.replaceChildren();
        draw();
      } catch (e) {
        work.classList.add("hidden");
        setStatus(sheetStatus, e.message, true);
      }
    } });
  const sheetStatus = h("div", { class: "status", role: "status" });

  const rotateAll = (d) => { pages.forEach((p) => (p.rotate = (p.rotate + d + 360) % 360)); draw(); };
  const tb = (label, fn) => h("button", { class: "btn quiet small", type: "button", onclick: fn }, label);
  bar.append(tb("Rotate all left", () => rotateAll(-90)), tb("Rotate all right", () => rotateAll(90)));
  if (!rotateOnly) bar.append(tb("Reverse order", () => { pages.reverse(); draw(); }));
  bar.append(tb("Undo all changes", () => { pages = thumbs.map((_, i) => ({ src: i, rotate: 0 })); draw(); }),
    tb("Choose another PDF", () => { work.classList.add("hidden"); sheet.classList.remove("hidden"); grid.replaceChildren(); }));

  let dragFrom = null;
  function draw() {
    grid.replaceChildren(...pages.map((p, i) => {
      const c = document.createElement("canvas");
      const src = thumbs[p.src];
      c.width = src.width; c.height = src.height;
      c.getContext("2d").drawImage(src, 0, 0);
      const w = parseFloat(src.style.width), hh = parseFloat(src.style.height);
      c.style.width = src.style.width; c.style.height = src.style.height;
      const k = p.rotate % 180 ? Math.min(w / hh, hh / w) * 0.96 : 1;
      c.style.transform = `rotate(${p.rotate}deg) scale(${k})`;
      const btn = (label, title, fn, disabled) => h("button", { class: "iconbtn", type: "button", title, "aria-label": `${title}, page ${i + 1}`, disabled, onclick: () => { fn(); draw(); } }, label);
      const acts = h("div", { class: "acts" },
        btn("↺", "Rotate left", () => (p.rotate = (p.rotate + 270) % 360)),
        btn("↻", "Rotate right", () => (p.rotate = (p.rotate + 90) % 360)));
      if (!rotateOnly) acts.append(
        btn("←", "Move earlier", () => { [pages[i - 1], pages[i]] = [pages[i], pages[i - 1]]; }, i === 0),
        btn("→", "Move later", () => { [pages[i + 1], pages[i]] = [pages[i], pages[i + 1]]; }, i === pages.length - 1),
        btn("⧉", "Duplicate", () => pages.splice(i + 1, 0, { ...p })),
        btn("✕", "Delete", () => pages.splice(i, 1), pages.length === 1));
      const card = h("div", { class: "pagecard", role: "listitem", draggable: rotateOnly ? "false" : "true" },
        h("div", { class: "thumb" }, c), h("span", { class: "num" }, `${i + 1}${p.src !== i ? ` (was ${p.src + 1})` : ""}`), acts);
      if (!rotateOnly) {
        card.addEventListener("dragstart", (e) => { dragFrom = i; card.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; });
        card.addEventListener("dragend", () => card.classList.remove("dragging"));
        card.addEventListener("dragover", (e) => { e.preventDefault(); card.classList.add("drop-before"); });
        card.addEventListener("dragleave", () => card.classList.remove("drop-before"));
        card.addEventListener("drop", (e) => {
          e.preventDefault();
          if (dragFrom === null || dragFrom === i) return draw();
          const [moved] = pages.splice(dragFrom, 1);
          pages.splice(dragFrom < i ? i - 1 : i, 0, moved);
          dragFrom = null;
          draw();
        });
      }
      return card;
    }));
  }

  save.addEventListener("click", async () => {
    const form = new FormData();
    form.append("file", file);
    form.append("options", JSON.stringify({ pages: pages.map((p) => ({ page: p.src, rotate: p.rotate })) }));
    await submit({ url: "/api/pdf/organize", form, button: save, status, result, doneTitle: "Saved" });
  });

  view.replaceChildren(toolHead(tool.title, tool.blurb), h("div", {}, sheet, sheetStatus), work);
}
