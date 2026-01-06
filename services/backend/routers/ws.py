import asyncio, base64, json, uuid
from dataclasses import dataclass
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.tts.edge import EdgeTTS
# from services.tts.dummy import DummyTTS
from services.llm.dummy import DummyLLM
from services.llm.local import LocalLLM
from services.llm.hf_local import HFLocalLLM


router = APIRouter()

SERVER_INSTANCE_ID = uuid.uuid4().hex
tts = EdgeTTS()
# llm = LocalLLM() # Switch to this when local server is ready
# llm = DummyLLM()
llm = HFLocalLLM(model_dir="models/selfrag_llama2_7b")

@dataclass
class SessionState:
    turn_id: int = 0
    workflow_task: asyncio.Task | None = None
    session_id: str = ""

async def send_json(ws: WebSocket, lock: asyncio.Lock, payload: dict):
    # Ensure turn_id is always present if context allows, but caller usually handles strict payloads
    async with lock:
        await ws.send_json(payload)

async def run_turn_workflow(ws: WebSocket, lock: asyncio.Lock, state: SessionState, turn_id: int, user_text: str):
    """
    Orchestration:
    1. Thinking (LLM Gen)
    2. Speaking (TTS Stream)
    """
    try:
        # --- Step 1: LLM Generation ---
        await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "thinking"})
        
        # Call LLM (non-streaming for v0.1 as per requirements, but could be streaming later)
        # Note: In a real app, you might want to run this in a thread if it's CPU bound, 
        # but network-bound HTTP calls are fine in async.
        
        # Check cancellation before starting expensive op
        if turn_id != state.turn_id: return

        assistant_text = await llm.generate(user_text)
        
        if turn_id != state.turn_id: return

        # Send Reply Text
        await send_json(ws, lock, {
            "type": "assistant_reply", 
            "turn_id": turn_id, 
            "text": assistant_text
        })

        # --- Step 2: TTS Generation ---
        # Start TTS task only if turn is valid
        # We run this as a sub-routine here or separate task?
        # User requirement: "user_text -> cancel old -> start LLM -> get text -> start TTS"
        # Since LLM is complete, we can just proceed linearly in this same task for v0.1
        
        await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "speaking"})
        await send_json(ws, lock, {"type": "audio_begin", "turn_id": turn_id, "mime": tts.mime_type})

        seq = 0
        async for chunk in tts.stream(assistant_text):
            if turn_id != state.turn_id: return
            b64 = base64.b64encode(chunk).decode("ascii")
            await send_json(ws, lock, {"type": "audio_chunk", "turn_id": turn_id, "seq": seq, "data": b64})
            seq += 1

        if turn_id == state.turn_id:
            await send_json(ws, lock, {"type": "audio_end", "turn_id": turn_id})
            await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "idle"})

    except asyncio.CancelledError:
        # Expected on interrupt
        return
    except Exception as e:
        await send_json(ws, lock, {"type": "error", "turn_id": turn_id, "msg": f"Workflow failed: {e}"})
        if turn_id == state.turn_id:
            await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "idle"})


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    send_lock = asyncio.Lock()
    session_id = uuid.uuid4().hex
    state = SessionState(turn_id=0, workflow_task=None, session_id=session_id)

    await send_json(ws, send_lock, {
        "type": "hello",
        "msg": "connected",
        "session_id": session_id,
        "server_instance_id": SERVER_INSTANCE_ID,
        "turn_id_reset": 0,
    })

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "user_text":
                # 1. Cancel Old
                state.turn_id += 1
                turn_id = state.turn_id
                
                if state.workflow_task:
                    state.workflow_task.cancel()
                    state.workflow_task = None

                # 2. Start New Workflow
                # We use a single task for the whole "Think + Speak" pipeline
                # If we wanted pipeline parallel (LLM streaming + TTS streaming), we'd need more complex sync.
                # v0.1: Linear is fine.
                state.workflow_task = asyncio.create_task(
                    run_turn_workflow(ws, send_lock, state, turn_id, msg.get("text", ""))
                )
                # Note: We reuse llm_task slot for the whole workflow for simplicity or rename it
                

            elif mtype == "interrupt":
                # Hard Stop
                state.turn_id += 1
                if state.workflow_task:
                    state.workflow_task.cancel()
                    state.workflow_task = None
                
                await send_json(ws, send_lock, {
                    "type": "state_update", 
                    "turn_id": state.turn_id, 
                    "state": "idle"
                })

            else:
                await send_json(ws, send_lock, {
                    "type": "error",
                    "turn_id": state.turn_id,
                    "msg": f"unknown type: {mtype}"
                })

    except WebSocketDisconnect:
        if state.workflow_task:
            state.workflow_task.cancel()
