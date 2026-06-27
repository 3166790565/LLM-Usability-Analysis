import asyncio
import time
import json as _json
import httpx
from typing import AsyncGenerator, Optional, Dict, Any, List


class ProviderClient:
    def __init__(self, base_url: str, api_key: str, timeout: Optional[int] = None, service_type: str = "openai"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.service_type = service_type
        self.headers = {"Content-Type": "application/json"}

        if service_type in ("openai", "openai_responses"):
            self.headers["Authorization"] = f"Bearer {api_key}"
        elif service_type in ("anthropic", "deepseek"):
            self.headers["x-api-key"] = api_key
            self.headers["anthropic-version"] = "2023-06-01"
        # Gemini 使用 query param auth，无需额外 header

    # ========== 构建请求参数 ==========

    def _build_test_payload(self, model: str, prompt: str = "say hello in world") -> tuple[str, dict, dict]:
        """根据 service_type 返回 (请求路径, 请求头(额外), 请求体)"""
        extra_headers = {}

        if self.service_type == "openai":
            path = f"{self.base_url}/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "stream": False
            }
        elif self.service_type == "openai_responses":
            path = f"{self.base_url}/responses"
            payload = {
                "model": model,
                "input": prompt,
                "max_output_tokens": 10
            }
        elif self.service_type in ("anthropic", "deepseek"):
            path = f"{self.base_url}/messages"
            payload = {
                "model": model,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": prompt}]
            }
        elif self.service_type == "gemini":
            base = self.base_url.replace("/v1", "")
            path = f"{base}/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
        else:
            path = f"{self.base_url}/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "stream": False
            }

        return path, extra_headers, payload

    def _build_chat_payload(self, model: str, messages: list, stream: bool = False, **kwargs) -> tuple[str, dict, dict]:
        """构建对话请求"""
        extra_headers = {}
        safe_kwargs = {k: v for k, v in kwargs.items() if v is not None}

        if self.service_type == "openai":
            path = f"{self.base_url}/chat/completions"
            payload = {"model": model, "messages": messages, "stream": stream, **safe_kwargs}
        elif self.service_type == "openai_responses":
            path = f"{self.base_url}/responses"
            payload = {"model": model, "input": messages[-1]["content"] if messages else "", **safe_kwargs}
        elif self.service_type in ("anthropic", "deepseek"):
            path = f"{self.base_url}/messages"
            payload = {"model": model, "max_tokens": safe_kwargs.pop("max_tokens", 1024),
                        "messages": messages, **safe_kwargs}
        elif self.service_type == "gemini":
            base = self.base_url.replace("/v1", "")
            path = f"{base}/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload = {"contents": [{"parts": [{"text": m["content"]}]} for m in messages]}
        else:
            path = f"{self.base_url}/chat/completions"
            payload = {"model": model, "messages": messages, "stream": stream, **safe_kwargs}

        return path, extra_headers, payload

    # ========== 对话接口 ==========

    async def chat_completion(self, messages: list, model: str, **kwargs) -> Dict[str, Any]:
        path, extra_headers, payload = self._build_chat_payload(model, messages, stream=False, **kwargs)
        all_headers = {**self.headers, **extra_headers}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await asyncio.wait_for(
                client.post(path, headers=all_headers, json=payload),
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()

    async def chat_completion_stream(self, messages: list, model: str, **kwargs) -> AsyncGenerator[bytes, None]:
        path, extra_headers, payload = self._build_chat_payload(model, messages, stream=True, **kwargs)
        all_headers = {**self.headers, **extra_headers}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", path, headers=all_headers, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = _json.dumps({
                "error": {"message": f"上游请求失败: {str(e)}", "type": "upstream_error"}
            }, ensure_ascii=False)
            yield f"data: {error_msg}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

    # ========== 测试接口 ==========

    async def test_model(self, model: str, prompt: str = "say hello in world") -> tuple[float, Optional[str], str, str]:
        path, extra_headers, payload = self._build_test_payload(model, prompt)
        all_headers = {**self.headers, **extra_headers}
        request_body = _json.dumps(payload, ensure_ascii=False, indent=2)
        start = time.time()
        resp = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await asyncio.wait_for(
                    client.post(path, headers=all_headers, json=payload),
                    timeout=self.timeout
                )
                resp.raise_for_status()
                elapsed = (time.time() - start) * 1000
                response_body = _json.dumps(resp.json(), ensure_ascii=False, indent=2)
                return round(elapsed, 2), None, request_body, response_body
        except asyncio.TimeoutError:
            elapsed = (time.time() - start) * 1000
            return round(elapsed, 2), f"请求超时 ({self.timeout}s)", request_body, "{}"
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            try:
                response_body = _json.dumps(resp.json(), ensure_ascii=False, indent=2) if resp is not None else str(e)
            except Exception:
                response_body = str(e)
            return round(elapsed, 2), str(e), request_body, response_body

    # ========== 模型列表 ==========

    async def list_models(self) -> List[Dict[str, Any]]:
        """获取上游模型列表（仅 OpenAI 兼容格式支持）"""
        if self.service_type in ("anthropic", "deepseek"):
            # Anthropic 没有标准 /models 接口，返回空
            return []
        auth_headers = {**self.headers}
        # Gemini 的模型列表也使用不同路径
        if self.service_type == "gemini":
            base = self.base_url.replace("/v1", "")
            url = f"{base}/v1beta/models?key={self.api_key}"
        else:
            url = f"{self.base_url}/models"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await asyncio.wait_for(
                client.get(url, headers=auth_headers),
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if "models" in data:
                # Gemini 格式
                return [{"id": m["name"].split("/")[-1]} for m in data.get("models", [])]
            return data.get("data", [])
