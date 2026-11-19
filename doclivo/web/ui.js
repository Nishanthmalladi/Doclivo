// Small DOM and network helpers shared by every page.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;      // CSSOM, allowed by the Content-Security-Policy
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

export function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function setStatus(el, text, isError = false) {
  if (!el) return;
  el.replaceChildren(text);
  el.classList.toggle("error", isError);
}

// POST a form with upload progress; resolves with the returned file.
export function send(url, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "blob";
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.upload.onload = () => onProgress?.(1);
    xhr.onerror = () => reject(new Error("The connection was lost. Check your internet and try again."));
    xhr.ontimeout = () => reject(new Error("The server took too long to answer. Try again."));
    xhr.onload = async () => {
      if (xhr.status === 200) {
        resolve({ blob: xhr.response, filename: filenameFrom(xhr.getResponseHeader("Content-Disposition")) || "download", xhr });
        return;
      }
      let message = `Something went wrong (error ${xhr.status}).`;
      try { message = JSON.parse(await xhr.response.text()).error || message; } catch { /* not JSON */ }
      if (xhr.status === 413 && message.startsWith("Something")) message = "These files are too large.";
      reject(new Error(message));
    };
    xhr.timeout = 10 * 60 * 1000;
    xhr.send(form);
  });
}

function filenameFrom(header) {
  if (!header) return null;
  const star = header.match(/filename\*=(?:UTF-8|utf-8)''([^;]+)/);
  if (star) { try { return decodeURIComponent(star[1]); } catch { /* fall through */ } }
  const plain = header.match(/filename="?([^";]+)"?/);
  return plain ? plain[1] : null;
}

export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function showResult(holder, { blob, filename, title, note }) {
  const btn = h("button", { class: "btn", type: "button" }, "Download");
  btn.addEventListener("click", () => download(blob, filename));
  const box = h("div", { class: "result", role: "status" },
    h("span", { class: "stampmark", "aria-hidden": "true" }, "READY"),
    h("h2", {}, title || "Done"),
    h("div", {}, h("div", { class: "file" }, filename), h("div", { class: "muted" }, fmtSize(blob.size))),
    note ? h("p", {}, note) : null,
    h("div", { class: "row" }, btn, h("a", { class: "btn quiet", href: "#/" }, "Use another tool")));
  holder.replaceChildren(box);
  download(blob, filename);          // start the download straight away; the button repeats it
  btn.focus({ preventScroll: true });
  box.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
}
