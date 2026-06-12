"""LLMClient — httpx SSE streaming client for OpenAI-compatible servers.

M9: each request resolves config.active_provider() at call time — base URL,
models and the API key reference all come from the provider entry, so a
provider switch in Settings applies to the very next request. Keys are
resolved through keychain.resolve_key (Keychain / env), and every error
message names the provider that failed.

Threading model: the client is synchronous. The caller (M2: a worker thread per
hotkey press) iterates `stream_chat(...)` and marshals each chunk to the main
thread via `AppHelper.callAfter(...)`. Cancellation may come from any thread
through `StreamHandle.cancel()` — it closes the underlying response, which also
unblocks a read that is waiting on the server.
"""

import json
import socket
import threading

import httpx

import keychain


class LLMError(Exception):
    """User-facing error with a clean one-line message. Never carries a traceback
    to the UI/console — the message itself is the whole story."""


class StreamHandle:
    """Cancellation handle for one in-flight request (thread-safe).

    cancel() must NOT call response.close() cross-thread: closing the fd does
    not interrupt a recv() blocked on another thread (verified hang on macOS).
    socket.shutdown() does — the blocked read returns EOF, the reader thread
    unwinds and closes the connection itself.
    """

    def __init__(self):
        self._cancelled = threading.Event()
        self._network_stream = None
        self._lock = threading.Lock()

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    def cancel(self):
        self._cancelled.set()
        self._shutdown_socket()

    def _attach(self, response):
        with self._lock:
            self._network_stream = response.extensions.get("network_stream")
        # cancel() may have raced us before the stream existed
        if self._cancelled.is_set():
            self._shutdown_socket()

    def _shutdown_socket(self):
        with self._lock:
            stream = self._network_stream
        if stream is None:
            return
        try:
            sock = stream.get_extra_info("socket")
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass  # already closed / not a real socket — event flag still set


class LLMClient:
    def __init__(self, config):
        self.config = config

    def stream_chat(self, messages, handle=None, on_reasoning=None, model=None,
                    max_tokens=None):
        """POST /v1/chat/completions with stream=true; yield content chunks.

        Thinking models stream chain-of-thought as delta.reasoning (or
        delta.reasoning_content) before any content; those chunks are passed
        to on_reasoning instead of being yielded, so callers can show
        progress without rendering the CoT.

        Reads every tunable from config at call time so a model/server change
        in Settings applies to the next request without restart (M4).
        """
        if handle is None:
            handle = StreamHandle()
        provider = self.config.active_provider()
        pname = str(provider["name"])
        base_url = str(provider["base_url"]).rstrip("/")
        payload = {
            "model": model or provider["explain_model"],
            "stream": True,
            "max_tokens": max_tokens or self.config.get("max_tokens"),
            "temperature": self.config.get("temperature"),
            "messages": messages,
        }
        template_kwargs = self.config.get("chat_template_kwargs")
        if template_kwargs and provider["is_local"]:
            # mlx-lm extension — external providers would reject the field
            payload["chat_template_kwargs"] = template_kwargs
        headers = {}
        try:
            api_key = keychain.resolve_key(provider["api_key_env_or_value"])
        except keychain.KeychainError as err:
            raise LLMError(f"{pname}: {err}") from None
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout = httpx.Timeout(
            connect=self.config.get("request_connect_timeout"),
            read=self.config.get("request_read_timeout"),
            write=10.0,
            pool=5.0,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST", f"{base_url}/v1/chat/completions", json=payload,
                    headers=headers,
                ) as response:
                    handle._attach(response)
                    if response.status_code >= 400:
                        response.read()
                        raise self._http_error(response, pname)
                    yield from self._iter_sse(response, handle, on_reasoning)
        except LLMError:
            raise
        except httpx.ConnectError:
            raise LLMError(
                f"{pname} 연결 실패 ({base_url}) — 서버/네트워크를 확인하세요."
            ) from None
        except httpx.TimeoutException:
            raise LLMError(
                f"{pname} 응답 시간 초과 ({base_url}) — 서버 상태를 확인하세요."
            ) from None
        except httpx.HTTPError as exc:
            if handle.cancelled:
                return
            raise LLMError(
                f"{pname} 통신 오류: {exc.__class__.__name__}"
            ) from None
        except Exception:
            # response.close() from another thread surfaces as various stream
            # errors mid-iteration; a cancelled request must end silently.
            if handle.cancelled:
                return
            raise

    def _http_error(self, response, pname):
        """Map an HTTP error response to a user-facing LLMError. The local
        proxy answers 503 {"error": {"code": "model_loading"}} while a backend
        is still loading its model (M5) — that gets its own message so the
        user knows to just wait. External providers (OpenAI/OpenRouter…)
        return a useful error.message — surface it instead of guessing."""
        code, detail = None, None
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                code = error.get("code")
                detail = error.get("message")
        except ValueError:
            pass
        if response.status_code == 503 and code == "model_loading":
            return LLMError(f"{pname}: 모델 로딩 중입니다 — 잠시 후 다시 시도하세요.")
        if response.status_code in (401, 403):
            return LLMError(
                f"{pname} 인증 실패 (HTTP {response.status_code}) — "
                "API 키를 확인하세요."
            )
        message = f"{pname} 오류 (HTTP {response.status_code})"
        if detail:
            message += f": {str(detail)[:120]}"
        return LLMError(message)

    def _iter_sse(self, response, handle, on_reasoning=None):
        for line in response.iter_lines():
            if handle.cancelled:
                return
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                raise LLMError("LLM 서버가 잘못된 SSE 형식을 보냈습니다.") from None
            delta = event["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                yield content
            elif on_reasoning is not None:
                reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                if reasoning:
                    on_reasoning(reasoning)


def _main():
    import argparse
    import sys

    from config import ConfigStore

    parser = argparse.ArgumentParser(description="M1 console smoke test")
    parser.add_argument("--base-url", help="override server URL (server-down test)")
    parser.add_argument(
        "--provider", help="use this provider by name (in-memory, not saved)"
    )
    parser.add_argument(
        "--prompt",
        default="대한민국의 수도와 그 도시의 특징을 간단히 설명해줘.",
        help="user prompt (default: hardcoded M1 test prompt)",
    )
    parser.add_argument(
        "--cancel-after", type=float, metavar="SEC",
        help="cancel the in-flight request after SEC seconds (cancel-path demo)",
    )
    args = parser.parse_args()

    config = ConfigStore()
    if args.provider:
        config.set("active_provider", args.provider)  # in-memory only, not saved
    if args.base_url:
        # in-memory only: patch the active provider's URL (server-down test)
        providers = [dict(p) for p in config.get("providers")]
        active = config.active_provider()["name"]
        for entry in providers:
            if entry.get("name") == active:
                entry["base_url"] = args.base_url
        config.set("providers", providers)

    client = LLMClient(config)
    handle = StreamHandle()
    if args.cancel_after is not None:
        timer = threading.Timer(args.cancel_after, handle.cancel)
        timer.daemon = True
        timer.start()

    messages = [
        {"role": "system", "content": config.get("system_prompt_text")},
        {"role": "user", "content": args.prompt},
    ]
    reasoning_total = [0]

    def on_reasoning(text):
        if reasoning_total[0] == 0:
            print("[thinking…] ", end="", flush=True)
        reasoning_total[0] += len(text)

    got_content = False
    try:
        for chunk in client.stream_chat(messages, handle, on_reasoning=on_reasoning):
            if not got_content and reasoning_total[0]:
                print(f"({reasoning_total[0]} chars)", flush=True)
            got_content = True
            print(chunk, end="", flush=True)
    except LLMError as err:
        print(f"오류: {err}", file=sys.stderr)
        sys.exit(1)
    print()
    if not got_content and not handle.cancelled:
        print(
            f"(내용 없음 — thinking {reasoning_total[0]}자만 출력하고 종료)",
            flush=True,
        )
    if handle.cancelled:
        print("(요청이 취소되었습니다)", flush=True)


if __name__ == "__main__":
    _main()
