from fastapi import APIRouter, WebSocket
import asyncio
import json
import uuid
import base64

from core.session import SessionState
from utils.audio_stub import synthesize_wav_stub

router = APIRouter()
SERVER_INSTANCE_ID = uuid.uuid4().hex  # 后端每次启动都变

async def safe_send_json(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
    except Exception:
        pass

@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    state = SessionState()

    # 握手：告诉前端“这是哪个后端实例 + 当前 session_id + turn_id 从 0 开始”
    await safe_send_json(ws, {
        "type": "hello",
        "server_instance_id": SERVER_INSTANCE_ID,
        "session_id": state.session_id,
        "turn_id_reset": 0,
        "msg": "connected"
    })

    async def run_turn(turn_id: int, user_text: str):
        # thinking
        await safe_send_json(ws, {"type": "state_update", "session_id": state.session_id, "turn_id": turn_id, "state": "thinking"})

        # v0.1：这里先用规则/回显当 LLM（以后替换成真实 LLM）
        assistant_text = f"收到：{user_text}"

        # speaking
        await safe_send_json(ws, {"type": "state_update", "session_id": state.session_id, "turn_id": turn_id, "state": "speaking"})
        await safe_send_json(ws, {"type": "assistant_reply", "session_id": state.session_id, "turn_id": turn_id, "text": assistant_text})

        # v0.1：生成音频 bytes（以后替换成真实 TTS）
        wav_bytes = synthesize_wav_stub(assistant_text, seconds=1.0)
        
        # Base64 Encode
        b64_data = base64.b64encode(wav_bytes).decode("utf-8")

        # Send audio_chunk (Protocol v0.1.1)
        await safe_send_json(ws, {
            "type": "audio_chunk",
            "session_id": state.session_id,
            "turn_id": turn_id,
            "chunk_seq": 0,
            "format": "wav",
            "sample_rate": 16000,
            "data": b64_data
        })

        await safe_send_json(ws, {"type": "state_update", "session_id": state.session_id, "turn_id": turn_id, "state": "idle"})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "user_text":
                # 收到新输入：默认认为会打断上一轮（体验更像“对话”）
                state.cancel_current()

                turn_id = state.next_turn()
                user_text = msg.get("text", "")

                # 开一个 task 跑本轮（可被 interrupt cancel）
                state.current_task = asyncio.create_task(run_turn(turn_id, user_text))

            elif mtype == "interrupt":
                # 硬中断：取消当前 task + turn_id++，使旧消息全部失效
                state.cancel_current()
                turn_id = state.next_turn()
                await safe_send_json(ws, {"type": "state_update", "session_id": state.session_id, "turn_id": turn_id, "state": "idle"})

            else:
                await safe_send_json(ws, {"type": "error", "msg": f"unknown type: {mtype}"})

    except Exception:
        # 断开连接
        state.cancel_current()
        return
