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
const pdfDoc = shallowRef<pdfjsLib.PDFDocumentProxy | null>(null);

const currentPage = ref(1);
const totalPages = ref(0);
const scale = ref(1.0);
const loading = ref(false);
const errorMsg = ref("");

let requestSeq = 0;        // 每次用户请求渲染就 ++（使旧请求过期）
let pendingPage: number | null = null;
const rendering = ref(false); 
let renderTask: any | null = null;

// ---- Load PDF ----
const loadPdf = async (url: string) => {
  loading.value = true;
  errorMsg.value = "";
  try {
    // 清理旧 doc
    await cleanup();

    const loadingTask = pdfjsLib.getDocument(url);
    pdfDoc.value = await loadingTask.promise;

    totalPages.value = pdfDoc.value.numPages;
    currentPage.value = 1;

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

  pendingPage = num;
  requestSeq++;                 // ✅ 关键：新请求立刻让旧任务过期

  if (rendering.value) {
    // 只能取消 render 阶段；getPage 取消不了，但 seq 会让它回来后自杀
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

      const mySeq = requestSeq;        // 捕获“启动这一轮渲染时”的最新 seq
      await renderPageInternal(pageNum, mySeq);
    }
  } finally {
    rendering.value = false;
  }
};

const renderPageInternal = async (num: number, mySeq: number) => {
  if (!pdfDoc.value || !canvasRef.value) return;

  // 阶段 1：getPage（不可取消，但可“回来后自杀”）
  const page = await pdfDoc.value.getPage(num);

  // 如果期间有新请求，直接退出，不画旧页
  if (mySeq !== requestSeq) return;

  const canvas = canvasRef.value;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  // 计算 viewport
  const viewport = page.getViewport({ scale: scale.value });

  // ✅ 关键：设置 Canvas 尺寸（CSS 尺寸 + 实际像素尺寸），避免默认 300x150 & 模糊
  const dpr = window.devicePixelRatio || 1;

  // Canvas 在页面上的“显示尺寸”（CSS 像素）
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;

  // Canvas 的“真实像素尺寸”（设备像素）
  canvas.width = Math.floor(viewport.width * dpr);
  canvas.height = Math.floor(viewport.height * dpr);

  // 让绘制坐标系回到 CSS 像素单位（配合上面的 width/height）
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, Math.floor(viewport.width), Math.floor(viewport.height));

  // 阶段 2：render（可取消）
  try {
    renderTask?.cancel?.();
  } catch {}

  // 注意：这里传给 pdf.js 的 viewport 仍然用 CSS 像素的 viewport（我们用 ctx.setTransform 做了 dpr 缩放）
  renderTask = page.render({ canvasContext: ctx, viewport } as any);

  try {
    await renderTask.promise;
  } catch (err: any) {
    // pdf.js 取消渲染会抛异常：RenderingCancelledException / RenderingCancelled
    const name = String(err?.name || "");
    const msg = String(err?.message || err || "");
    if (name.includes("RenderingCancelled") || msg.includes("RenderingCancelled")) return;
    console.error("Render Error:", err);
    return;
  } finally {
    renderTask = null;
  }

  // 再检查一次：render 完了但期间又有新请求 → 不要让旧页成为最终结果
  if (mySeq !== requestSeq) return;
};

// ---- Cleanup ----
const cleanup = async () => {
  // 让所有 render 失效
  requestSeq++;
  pendingPage = null;

  try { renderTask?.cancel?.(); } catch {}
  renderTask = null;

  if (pdfDoc.value) {
    try { await pdfDoc.value.destroy(); } catch {}
    pdfDoc.value = null;
  }
};

// ---- Navigation ----
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

onMounted(() => {
  loadPdf("/test.pdf");
});

onBeforeUnmount(() => {
  void cleanup();
});
</script>

<template>
  <div class="slide-viewer-container">
    <div v-if="loading" class="loading">Loading PDF...</div>
    <div v-if="errorMsg" class="error">{{ errorMsg }}</div>

    <div class="canvas-wrapper" v-show="!loading && !errorMsg">
      <canvas ref="canvasRef"></canvas>
    </div>

    <div class="controls" v-if="totalPages > 0">
      <button @click="prevPage" :disabled="currentPage <= 1">Prev</button>
      <span class="page-info">
        {{ currentPage }} / {{ totalPages }}
        <span v-if="rendering" style="opacity:0.7"> (rendering...)</span>
      </span>
      <button @click="nextPage" :disabled="currentPage >= totalPages">Next</button>
    </div>
  </div>
</template>

<style scoped>
.slide-viewer-container { width: 100%; height: 100%; position: relative; background: #333; display: flex; flex-direction: column; overflow: hidden; }
.canvas-wrapper { flex: 1; display: flex; justify-content: center; align-items: center; overflow: auto; padding: 20px; }
canvas { max-width: 100%; max-height: 100%; object-fit:contain;box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
.controls { height: 40px; background: #222; display: flex; align-items: center; justify-content: center; gap: 16px; color: white; }
.controls button { padding: 4px 12px; cursor: pointer; }
.controls button:disabled { opacity: 0.5; cursor: not-allowed; }
.loading, .error { color: white; text-align: center; padding: 20px; }
.error { color: #ff6b6b; }
</style>
