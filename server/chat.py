#!/usr/bin/env python3
"""
Simple interactive terminal chat against the local LLM server (:8000).
Same streaming path the Macsist app uses.

Usage:
    python3 chat.py                 # the served model (Qwen3.8-27B, multimodal)
    python3 chat.py --model <hf-id> # override the model id
    python3 chat.py --image foo.png # send an image (vision), then chat about it

Commands inside the chat:
    /reset   clear conversation
    /quit    exit
"""
import sys, json, base64, urllib.request

BASE = "http://127.0.0.1:8000/v1/chat/completions"
# Single multimodal backend since Qwen3.8 (native VLM — text + vision in one
# model, served vlm-only on :8001). Override with --model for A/B runs.
DEFAULT_MODEL = "mlx-community/Qwen3.8-27B-bf16"

args = sys.argv[1:]
model = args[args.index("--model") + 1] if "--model" in args else DEFAULT_MODEL
image_path = None
if "--image" in args:
    image_path = args[args.index("--image") + 1]

messages = []

def stream(messages):
    body = json.dumps({
        "model": model, "stream": True, "max_tokens": 1024,
        "messages": messages,
    }).encode()
    req = urllib.request.Request(BASE, data=body,
                                 headers={"Content-Type": "application/json"})
    full = ""
    with urllib.request.urlopen(req) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"]
            except Exception:
                continue
            # 35B streams `content`; 27B (thinking) may stream `reasoning` first
            piece = delta.get("content") or ""
            think = delta.get("reasoning") or ""
            if think and not piece:
                print(f"\033[90m{think}\033[0m", end="", flush=True)  # dim grey
            if piece:
                print(piece, end="", flush=True)
                full += piece
    print()
    return full

print(f"Model: {model}")
print("Type your message. /reset to clear, /quit to exit.\n")

# Optional image as the first user turn
if image_path:
    b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    q = input("이미지에 대한 질문 (엔터=기본 설명): ").strip() or "이 이미지를 한국어로 간결하게 설명해줘."
    messages.append({"role": "user", "content": [
        {"type": "text", "text": q},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]})
    print("\nAI: ", end="", flush=True)
    reply = stream(messages)
    messages.append({"role": "assistant", "content": reply})

while True:
    try:
        user = input("\nYou: ").strip()
    except (EOFError, KeyboardInterrupt):
        print(); break
    if not user:
        continue
    if user == "/quit":
        break
    if user == "/reset":
        messages = []
        print("(conversation cleared)")
        continue
    messages.append({"role": "user", "content": user})
    print("AI: ", end="", flush=True)
    reply = stream(messages)
    messages.append({"role": "assistant", "content": reply})
