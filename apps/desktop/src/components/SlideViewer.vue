<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, shallowRef } from "vue";
import * as pdfjsLib from "pdfjs-dist";

// 解决 pdfjs-dist v4 在旧版 Electron 中报 URL.parse 错误的问题
if (typeof (URL as any).parse === "undefined") {
  (URL as any).parse = (url: string, base?: string) => {
    try { return new URL(url, base); } catch { return null; }
  };
}

// Configure worker
pdfjsLib.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

const canvasRef = ref<HTMLCanvasElement | null>(null);
const stageShellRef = ref<HTMLDivElement | null>(null);
const pdfDoc = shallowRef<pdfjsLib.PDFDocumentProxy | null>(null);

const currentPage = ref(1);
const totalPages = ref(0);
const loading = ref(false);
const errorMsg = ref("");

/** 16:9 舞台尺寸（CSS px） */
const stageW = ref(0);
const stageH = ref(0);

/** 缩放倍率 */
const zoom = ref(1.0);

// Render queue / race control
let requestSeq = 0;
let pendingPage: number | null = null;
const rendering = ref(false);
let renderTask: any | null = null;

// Offscreen canvas
let offscreen: HTMLCanvasElement | null = null;

const computeStageSize = () => {
  const shell = stageShellRef.value;
  if (!shell) return;

  const w = shell.clientWidth;
  const h = shell.clientHeight;

  if (w <= 0 || h <= 0) return;

  const targetRatio = 16 / 9;

  let sW = w;
  let sH = Math.floor(w / targetRatio);

  if (sH > h) {
    sH = h;
    sW = Math.floor(h * targetRatio);
  }

  stageW.value = Math.max(0, sW);
  stageH.value = Math.max(0, sH);
};

// ---- Load PDF ----
const loadPdf = async (url: string) => {
  loading.value = true;
  errorMsg.value = "";
  try {
    await cleanup();

    const loadingTask = pdfjsLib.getDocument(url);
    pdfDoc.value = await loadingTask.promise;

    totalPages.value = pdfDoc.value.numPages;
    currentPage.value = 1;

    computeStageSize();
    requestRender(1);
  } catch (err: any) {
    console.error("PDF Load Error:", err);
    errorMsg.value = "Failed to load PDF. Check public/test.pdf";
  } finally {
    loading.value = false;
  }
};

const requestRender = (num: number) => {
  if (!pdfDoc.value) return;
  if (!canvasRef.value) return;
  if (stageW.value <= 0 || stageH.value <= 0) return;

  pendingPage = num;
  requestSeq++; 

  if (rendering.value) {
    try { renderTask?.cancel?.(); } catch {}
    return;
  }

  void renderLoop();
};

const renderLoop = async () => {
  if (!pdfDoc.value || !canvasRef.value) return;

  rendering.value = true;
  try {
    while (pendingPage !== null) {
      const pageNum = pendingPage;
      pendingPage = null;

      const mySeq = requestSeq;
      await renderPageInternal(pageNum, mySeq);
    }
  } finally {
    rendering.value = false;
  }
};

const renderPageInternal = async (num: number, mySeq: number) => {
  if (!pdfDoc.value || !canvasRef.value) return;
  if (stageW.value <= 0 || stageH.value <= 0) return;

  const page = await pdfDoc.value.getPage(num);
  if (mySeq !== requestSeq) return;

  const canvas = canvasRef.value;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const sW = stageW.value;
  const sH = stageH.value;

  canvas.style.width = `${sW}px`;
  canvas.style.height = `${sH}px`;
  canvas.width = Math.floor(sW * dpr);
  canvas.height = Math.floor(sH * dpr);

  const base = page.getViewport({ scale: 1 });
  const fitScale = Math.min(sW / base.width, sH / base.height) * zoom.value;
  const vp = page.getViewport({ scale: fitScale });

  const renderW = Math.floor(vp.width); 
  const renderH = Math.floor(vp.height);

  if (!offscreen) offscreen = document.createElement("canvas");
  const offCtx = offscreen.getContext("2d");
  if (!offCtx) return;

  offscreen.width = Math.floor(renderW * dpr);
  offscreen.height = Math.floor(renderH * dpr);
  offCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  offCtx.clearRect(0, 0, renderW, renderH);

  try { renderTask?.cancel?.(); } catch {}
  renderTask = page.render({ canvasContext: offCtx, viewport: vp } as any);

  try {
    await renderTask.promise;
  } catch (err: any) {
    const name = String(err?.name || "");
    const msg = String(err?.message || err || "");
    if (name.includes("RenderingCancelled") || msg.includes("RenderingCancelled")) return;
    console.error("Render Error:", err);
    return;
  } finally {
    renderTask = null;
  }

  if (mySeq !== requestSeq) return;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const destW = Math.floor(renderW * dpr);
  const destH = Math.floor(renderH * dpr);
  const destX = Math.floor(((sW - renderW) / 2) * dpr);
  const destY = Math.floor(((sH - renderH) / 2) * dpr);

  ctx.drawImage(
    offscreen,
    0, 0, offscreen.width, offscreen.height,
    destX, destY, destW, destH
  );
};

const cleanup = async () => {
  requestSeq++;
  pendingPage = null;
  try { renderTask?.cancel?.(); } catch {}
  renderTask = null;
  if (pdfDoc.value) {
    try { await pdfDoc.value.destroy(); } catch {}
    pdfDoc.value = null;
  }
};

const prevPage = () => {
  if (currentPage.value > 1) {
    currentPage.value--;
    requestRender(currentPage.value);
  }
};

const nextPage = () => {
  if (currentPage.value < totalPages.value) {
    currentPage.value++;
    requestRender(currentPage.value);
  }
};

let ro: ResizeObserver | null = null;

onMounted(() => {
  loadPdf("/test.pdf");
  ro = new ResizeObserver(() => {
    const prevW = stageW.value;
    const prevH = stageH.value;
    computeStageSize();
    if (stageW.value !== prevW || stageH.value !== prevH) {
      requestRender(currentPage.value);
    }
  });
  if (stageShellRef.value) ro.observe(stageShellRef.value);
});

onBeforeUnmount(() => {
  ro?.disconnect();
  ro = null;
  void cleanup();
});

// ✅ 暴露 API 供 MainLayout 使用
defineExpose({
  prevPage,
  nextPage,
  currentPage, 
  totalPages,
  rendering
});
</script>

<template>
  <div class="slide-viewer-container">
    <div v-if="loading" class="loading">Loading PDF...</div>
    <div v-if="errorMsg" class="error">{{ errorMsg }}</div>

    <div class="stage-shell" ref="stageShellRef" v-show="!loading && !errorMsg">
      <div class="stage" :style="{ width: stageW + 'px', height: stageH + 'px' }">
        <canvas ref="canvasRef"></canvas>
      </div>
    </div>
    
  </div>
</template>

<style scoped>
.slide-viewer-container {
  width: 100%;
  height: 100%;
  background: #333;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stage-shell {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 8px;
}

.stage {
  background: #111;
  border-radius: 10px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.35);
  overflow: hidden;
  position: relative;
}

canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.loading, .error {
  color: white;
  text-align: center;
  padding: 20px;
}
.error { color: #ff6b6b; }
</style>