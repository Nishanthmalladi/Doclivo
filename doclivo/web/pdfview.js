// Opens PDFs in the browser with pdf.js, for previews only (nothing is uploaded).
let pdfjs = null;

export async function openPdf(file) {
  if (!pdfjs) {
    pdfjs = await import("/vendor/pdf.min.mjs");
    pdfjs.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.mjs";
  }
  const data = new Uint8Array(await file.arrayBuffer());
  try {
    return await pdfjs.getDocument({ data, isEvalSupported: false, enableXfa: false }).promise;
  } catch (e) {
    if (e?.name === "PasswordException") throw new Error("This PDF is password-protected. Use Unlock PDF first, then come back.");
    throw new Error("This file could not be opened as a PDF.");
  }
}

// Draw a page into a canvas that is cssWidth pixels wide on screen.
export async function renderInto(canvas, page, cssWidth) {
  const base = page.getViewport({ scale: 1 });
  const scale = cssWidth / base.width;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const vp = page.getViewport({ scale: scale * dpr });
  canvas.width = Math.round(vp.width);
  canvas.height = Math.round(vp.height);
  canvas.style.width = `${cssWidth}px`;
  canvas.style.height = `${Math.round(base.height * scale)}px`;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
  return { scale, width: base.width, height: base.height };
}
