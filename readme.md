# 一、项目架构（当前选型：Electron + Vue + WebSocket / FastAPI / Live2D）

## 1) 逻辑模块划分

### 前端（Electron + Vue）
- **Slide Viewer（课件层）**
    - 导入 PPT（建议 v0.1 先用：PPT→PDF/图片序列）
    - 翻页、缩放、全屏
- **Avatar Renderer（数字人层）**
    - Live2D 模型加载与渲染（Canvas/WebGL）
    - 嘴型驱动（v0.1 先用音频能量驱动）
    - 状态切换（idle/speaking…）
- **Audio I/O（音频层）**
    - 播放 TTS 音频（流式或分片）
    - 录音（麦克风采集，v0.1 可选先做 push-to-talk）
    - 打断（停止播放+嘴型归零）
- **Realtime Client（通信层）**
    - 与后端 WebSocket 保持连接
    - 发送：用户输入（先文本/后音频）
    - 接收：LLM 文本、TTS 音频、状态事件

### 后端（FastAPI）
- **WebSocket Gateway**
    - 维护 session、收发消息
    - 心跳、断线重连（v0.1 可先不做复杂恢复）
- **Orchestrator（编排器）**
    - 串联 ASR → LLM → TTS（v0.1 可先文本 → LLM → TTS）
    - 负责中断：interrupt 时取消/停止推送
- **Providers（可插拔适配器）**
    - ASR Provider（v0.1 可不做）
    - LLM Provider（先选一个能流式输出的）
    - TTS Provider（先选一个能快速返回音频的，流式可推迟到 v0.2）
---

## 2) 运行时数据流（v0.1 的最小闭环）

### A. 最小闭环（先不做语音输入，先做文本输入）
1. 前端：用户输入文本（或点“讲解当前页”）
2. 前端 → 后端：`user_text`
3. 后端：LLM 生成回复（可一次性/可流式）
4. 后端：TTS 合成音频
5. 后端 → 前端：`assistant_text` + `tts_audio`（一次性返回也行）
6. 前端：播放音频，同时用 WebAudio 能量驱动 Live2D 嘴巴
7. 用户点“打断”：
    - 前端立刻停止播放、嘴型归零
    - 前端 → 后端：`interrupt`（后端停止生成/停止发送）
> 这条链路跑通，你就已经具备“实时对话助教的骨架”，后面再把语音输入、流式 token、流式 TTS 逐步加上去。

### B. v0.2 才建议做的（更真实的实时）
- 麦克风音频分片上行
- ASR partial
- LLM token stream
- TTS audio chunk stream
- VAD barge-in 自动打断
---

## 3) WebSocket 消息协议（v0.1 版，最小但可扩展）
建议统一都带：`session_id`、`seq`、`generation_id`（generation 用于中断后丢弃旧消息）。

### 前端 → 后端
- `hello`：建立连接/新会话
- `user_text`：用户文本输入
- `interrupt`：打断当前生成
- `slide_state`（可选）：当前页码（为未来“讲当前页”铺路）

### 后端 → 前端
- `state_update`：idle/thinking/speaking
- `assistant_text`：一次性回复（或 `assistant_text_delta`）
- `tts_audio`：音频（v0.1 允许一次性返回 base64 / url）
- `error`
> v0.1 重点是把 `interrupt` 做成“硬中断”：前端先停播，后端收到后就切换 generation_id、停止推送。
---

## 4) 工程目录建议（便于你后续扩展）
```
project/
  apps/
    desktop/                 # Electron + Vue
      src/
        renderer/
          modules/
            slides/          # PDF/图片序列渲染
            avatar/          # Live2D renderer + driver
            audio/           # 播放/录音/能量提取
            realtime/        # WS client + message router
            ui/              # 控制面板、字幕、输入框
        main/                # Electron main process
        preload/             # 安全桥接
  services/
    backend/                 # FastAPI
      app/
        api/ws.py            # websocket gateway
        core/session.py      # session & generation管理
        orchestrator/        # ASR/LLM/TTS pipeline
        providers/
          llm.py
          tts.py
          asr.py             # v0.1可为空

```
---

# 二、v0.1 版本应该先做什么（按优先级 + 可验收输出）

## v0.1 的目标定义
**一个同屏 PPT 播放器 + 角落 Live2D 助教 + 可对话（先文本）+ 会说话（TTS）+ 可打断。**
> 你现在的创新点先不在“数字人表现”，所以 v0.1 只要做到“说话时动嘴 + 打断立刻停”，就足够支撑后续研究与迭代。
---

## 1) v0.1 必做任务清单（按顺序）

### (1) 前端基础框架与布局（半天～1天）
- Electron + Vue 跑起来
- 页面布局三块：
    - 左/中：Slide Viewer（先放占位图也行）
    - 右下角：Live2D Canvas
    - 下方：输入框 + 发送按钮 + 打断按钮 + 状态指示（idle/thinking/speaking）
✅ 验收：应用可启动、UI 框架稳定
---

### (2) Slide Viewer：先用 PDF/图片序列（1天）
- 先别在 v0.1 直接解析 pptx
- 建议：PPT 预处理导出 PDF（手动也行），前端用 pdf.js 渲染
- 支持：翻页、显示当前页码
✅ 验收：能稳定展示你的学术 PPT（至少 1 份）
---

### (3) Live2D 集成：能显示角色（1天～2天）
- 加载 1 个 Live2D 模型（固定位置、缩放）
- 先实现 idle 动作（或静止也行）
✅ 验收：启动后角色稳定显示，不闪退不卡死
---

### (4) 音频播放 + 嘴型能量驱动（核心！）（1天）
- 前端能播放一段音频（先本地 wav/mp3 也行）
- 用 WebAudio `AnalyserNode` 算能量 → 映射到 Live2D mouth 参数
- 简单调参：说话动嘴、停了闭嘴
✅ 验收：播放音频时嘴动，停止即闭嘴（为后续 TTS 链路打基础）
---

### (5) WebSocket：打通前后端最小对话（1天）
后端 FastAPI：
- WS endpoint：接 `user_text`
- 调 LLM 生成一句回复（先非流式）
- 调 TTS 合成音频（先一次性返回 URL 或 base64）
- 返回给前端：`assistant_text` + `tts_audio`
前端：
- 发送 `user_text`
- 收到音频就播放，同时触发嘴型能量驱动
✅ 验收：输入一句话 → 数字人说出来并动嘴
---

### (6) interrupt：实现“硬打断”（半天）
- 前端：点击打断按钮 → 立刻 stop 播放 + 嘴型归零 + 发 `interrupt`
- 后端：收到 `interrupt` → 停止当前生成（或至少停止继续发送音频）
✅ 验收：说到一半点打断，0.2s 内停声+停嘴（体感非常关键）
---

## 2) v0.1 可以暂缓的内容（别提前背复杂度）
- 语音输入（ASR）与 VAD 自动打断（放到 v0.2）
- LLM token 流式字幕（v0.2）
- TTS 流式音频分片（v0.2）
- 复杂表情、viseme 精准口型（v0.3+）
- PPT 理解/RAG/ROI 对齐（你已经计划第二步再做，很对）
---

## 3) v0.1 最终交付物（你用来写阶段总结/开会展示）
1. 一个 Electron 应用（可运行）
2. 可打开一份 PDF 课件并翻页
3. 右下角 Live2D 助教
4. 输入文本 → 助教语音回答（TTS）→ 说话动嘴
5. 打断按钮可立即停止
