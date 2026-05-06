from fastapi import FastAPI, Request, HTTPException
import requests, uuid, os

app = FastAPI()

AZURE_URL = "https://orca-resource.openai.azure.com/openai/v1/chat/completions"
API_KEY = os.getenv("AZURE_API_KEY")


def clean_messages(messages):
    cleaned = []
    for msg in messages:
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "\n".join(text_parts)

        cleaned.append({
            "role": msg["role"],
            "content": content
        })
    return cleaned


# =========================
# ANTHROPIC / CLAUDE ROUTE
# =========================
@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.json()

    # 🔥 IMPORTANT: Claude Code often sends stream=true
    if body.get("stream"):
        return {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Streaming is not supported by this proxy yet."
                }
            ],
            "stop_reason": "end_turn"
        }

    try:
        payload = {
            "model": "FW-MiniMax-M2.5-saurabh",
            "messages": clean_messages(body.get("messages", [])),
            "max_completion_tokens": body.get("max_tokens", 1024)
        }

        response = requests.post(
            AZURE_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload
        )

        data = response.json()

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=data)

        content = data["choices"][0]["message"]["content"]

        return {
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": content
                }
            ],
            "model": body.get("model", "MiniMax-M2.5"),
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": data.get("usage", {}).get("completion_tokens", 0)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# OPENAI COMPATIBILITY LAYER (IMPORTANT FOR CLI TOOLS)
# =========================
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()

    try:
        messages = body.get("messages", [])

        payload = {
            "model": "FW-MiniMax-M2.5-saurabh",
            "messages": clean_messages(messages),
            "max_completion_tokens": body.get("max_tokens", 1024)
        }

        response = requests.post(
            AZURE_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload
        )

        data = response.json()

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=data)

        content = data["choices"][0]["message"]["content"]

        return {
            "id": f"chatcmpl_{uuid.uuid4().hex}",
            "object": "chat.completion",
            "model": body.get("model", "MiniMax-M2.5"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": data.get("usage", {}).get("total_tokens", 0)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# HEALTH CHECK (helps routers)
# =========================
@app.get("/")
def health():
    return {"status": "ok"}
