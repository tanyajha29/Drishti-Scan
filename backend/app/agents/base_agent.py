from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import requests

from app.agents.schemas import AgentResult

logger = logging.getLogger(__name__)
_HTTP_SESSION = requests.Session()

DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "openrouter/auto"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_TEMPERATURE = 0
DEFAULT_BEDROCK_REGION = "us-east-1"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

STRICT_JSON_SYSTEM_PROMPT = (
    "You are a security analysis assistant for DristiScan. "
    "Return ONLY valid JSON. "
    "Do NOT include markdown. "
    "Do NOT include code blocks or backticks. "
    "Do NOT include explanations or prose outside the JSON. "
    "Do NOT include any text before { or after }. "
    "If unsure about a field, return an empty string for that field."
)


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name, "")
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _resolve_model() -> str:
    return (_env_str("LLM_MODEL") or _env_str("OLLAMA_MODEL") or DEFAULT_MODEL).strip()


def _resolve_timeout() -> float:
    for key in ("LLM_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS"):
        val = _env_str(key)
        if val:
            try:
                return float(val)
            except ValueError:
                pass
    return float(DEFAULT_TIMEOUT_SECONDS)


def _resolve_temperature() -> float:
    try:
        return float(_env_str("LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE)))
    except ValueError:
        return float(DEFAULT_TEMPERATURE)


def _resolve_max_tokens() -> Optional[int]:
    val = _env_str("LLM_MAX_TOKENS")
    if not val:
        return None
    try:
        parsed = int(val)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


class BaseAgent:
    """
    LLM caller that routes to Bedrock, OpenRouter, or Ollama.
    When LLM_PROVIDER=bedrock, Bedrock is tried first and OpenRouter is used
    automatically as a production-safe fallback on any Bedrock failure.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        system_instructions: Optional[str] = None,
        model: Optional[str] = None,
        url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self.name = name or "Base Agent"
        self.system_instructions = (system_instructions or "").strip()
        self.model = (model or _resolve_model()).strip()
        self.timeout = timeout_seconds or _resolve_timeout()
        self.temperature = _resolve_temperature() if temperature is None else float(temperature)
        self.max_tokens = _resolve_max_tokens() if max_tokens is None else max_tokens
        self._debug = _env_bool("RAG_DEBUG", False)

        self._provider = _env_str("LLM_PROVIDER", DEFAULT_PROVIDER).lower() or DEFAULT_PROVIDER

        self._api_key = _env_str("OPENROUTER_API_KEY")
        self._openrouter_base_url = _env_str("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/") or OPENROUTER_BASE_URL
        self._openrouter_endpoint = f"{self._openrouter_base_url}/chat/completions"
        self._site_url = _env_str("OPENROUTER_SITE_URL", "http://localhost:5173")
        self._site_name = _env_str("OPENROUTER_SITE_NAME", "DristiScan")

        self._bedrock_model_id = _env_str("BEDROCK_MODEL_ID")
        self._bedrock_region = (
            _env_str("BEDROCK_REGION")
            or _env_str("AWS_REGION")
            or _env_str("AWS_DEFAULT_REGION")
            or DEFAULT_BEDROCK_REGION
        )
        self._bedrock_fallback_to_openrouter = _env_bool("BEDROCK_FALLBACK_TO_OPENROUTER", True)
        self._bedrock_access_key_id = _env_str("BEDROCK_AWS_ACCESS_KEY_ID")
        self._bedrock_secret_access_key = _env_str("BEDROCK_AWS_SECRET_ACCESS_KEY")
        self._bedrock_session_token = _env_str("BEDROCK_AWS_SESSION_TOKEN")

        raw_ollama = url or _env_str("OLLAMA_URL", "http://localhost:11434")
        self._ollama_url = self._normalize_ollama_url(raw_ollama)

        logger.info(
            "[%s] Initialized - provider=%s openrouter_model=%s bedrock_model=%s timeout=%ss max_tokens=%s",
            self.name,
            self._provider,
            self.model,
            self._bedrock_model_id or "(unset)",
            self.timeout,
            self.max_tokens,
        )

    def send_prompt(self, prompt: str) -> str:
        if self._provider == "ollama":
            return self._send_ollama(prompt)
        if self._provider == "bedrock":
            result = self._send_bedrock(prompt)
            if result:
                return result
            if self._bedrock_fallback_to_openrouter:
                logger.warning("[%s] Bedrock failed; falling back to OpenRouter", self.name)
                return self._send_openrouter(prompt)
            return ""
        return self._send_openrouter(prompt)

    def _build_system_content(self) -> str:
        if self.system_instructions:
            return f"{STRICT_JSON_SYSTEM_PROMPT}\n\n{self.system_instructions}"
        return STRICT_JSON_SYSTEM_PROMPT

    def _send_bedrock(self, prompt: str) -> str:
        if not self._bedrock_model_id:
            logger.error("[%s] BEDROCK_MODEL_ID is not set", self.name)
            return ""

        client_kwargs: dict[str, Any] = {"service_name": "bedrock-runtime", "region_name": self._bedrock_region}
        if self._bedrock_access_key_id and self._bedrock_secret_access_key:
            client_kwargs["aws_access_key_id"] = self._bedrock_access_key_id
            client_kwargs["aws_secret_access_key"] = self._bedrock_secret_access_key
            if self._bedrock_session_token:
                client_kwargs["aws_session_token"] = self._bedrock_session_token

        if self._debug:
            logger.debug(
                "[%s] Bedrock request model=%s region=%s prompt_len=%d",
                self.name,
                self._bedrock_model_id,
                self._bedrock_region,
                len(prompt),
            )
        else:
            logger.info(
                "[%s] Calling Bedrock model=%s region=%s timeout=%ss",
                self.name,
                self._bedrock_model_id,
                self._bedrock_region,
                self.timeout,
            )

        try:
            import boto3  # type: ignore

            client = boto3.client(**client_kwargs)
            inference_config: dict[str, Any] = {"temperature": self.temperature}
            if self.max_tokens is not None:
                inference_config["maxTokens"] = int(self.max_tokens)

            response = client.converse(
                modelId=self._bedrock_model_id,
                system=[{"text": self._build_system_content()}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig=inference_config,
            )
        except Exception as exc:
            logger.error("[%s] Bedrock request failed: %s", self.name, exc)
            return ""

        try:
            blocks = response["output"]["message"]["content"]
            content = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ).strip()
        except Exception as exc:
            logger.warning("[%s] Unexpected Bedrock response shape: %s", self.name, exc)
            return ""

        if not content:
            logger.warning("[%s] Bedrock returned empty content", self.name)
            return ""

        if self._debug:
            logger.debug("[%s] Bedrock response_len=%d", self.name, len(content))
        else:
            logger.info("[%s] Bedrock responded (%d chars)", self.name, len(content))
        return content

    def _send_openrouter(self, prompt: str) -> str:
        if not self._api_key:
            logger.error(
                "[%s] OPENROUTER_API_KEY is not set. Set it in .env or docker-compose environment.",
                self.name,
            )
            return ""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._build_system_content()},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._site_url,
            "X-Title": self._site_name,
        }

        if self._debug:
            logger.debug(
                "[%s] OpenRouter request model=%s url=%s prompt_len=%d",
                self.name,
                self.model,
                self._openrouter_endpoint,
                len(prompt),
            )
        else:
            logger.info("[%s] Calling OpenRouter model=%s timeout=%ss", self.name, self.model, self.timeout)

        try:
            resp = _HTTP_SESSION.post(
                self._openrouter_endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.Timeout:
            logger.error("[%s] OpenRouter timed out after %ss", self.name, self.timeout)
            return ""
        except requests.ConnectionError as exc:
            logger.error("[%s] OpenRouter connection error: %s", self.name, exc)
            return ""
        except requests.HTTPError as exc:
            logger.error(
                "[%s] OpenRouter HTTP %s: %s",
                self.name,
                exc.response.status_code if exc.response else "?",
                exc.response.text[:300] if exc.response else str(exc),
            )
            return ""
        except requests.RequestException as exc:
            logger.error("[%s] OpenRouter request failed: %s", self.name, exc)
            return ""

        try:
            data = resp.json()
        except ValueError:
            logger.warning("[%s] OpenRouter response not JSON-decodable", self.name)
            return ""

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("[%s] Unexpected OpenRouter response shape: %s", self.name, str(data)[:200])
            return ""

        if not isinstance(content, str):
            logger.warning("[%s] OpenRouter content is not a string: %r", self.name, content)
            return ""

        result = content.strip()
        if self._debug:
            logger.debug("[%s] OpenRouter response_len=%d", self.name, len(result))
        else:
            logger.info("[%s] OpenRouter responded (%d chars)", self.name, len(result))
        return result

    def _send_ollama(self, prompt: str) -> str:
        if self._debug:
            logger.debug(
                "[%s] Ollama request model=%s url=%s prompt_len=%d",
                self.name,
                self.model,
                self._ollama_url,
                len(prompt),
            )
        else:
            logger.info("[%s] Calling Ollama model=%s timeout=%ss", self.name, self.model, self.timeout)

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
        }
        if self.max_tokens is not None:
            payload["options"]["num_predict"] = self.max_tokens

        try:
            resp = _HTTP_SESSION.post(self._ollama_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.Timeout:
            logger.error("[%s] Ollama timed out after %ss (url=%s)", self.name, self.timeout, self._ollama_url)
            return ""
        except requests.ConnectionError as exc:
            logger.error("[%s] Ollama connection refused (is Ollama running at %s?): %s", self.name, self._ollama_url, exc)
            return ""
        except requests.RequestException as exc:
            logger.error("[%s] Ollama request failed: %s", self.name, exc)
            return ""

        try:
            data = resp.json()
        except ValueError:
            logger.warning("[%s] Ollama response not JSON-decodable", self.name)
            return ""

        text = data.get("response") or data.get("output") or ""
        if not isinstance(text, str):
            logger.warning("[%s] Unexpected Ollama payload shape", self.name)
            return ""

        result = text.strip()
        if self._debug:
            logger.debug("[%s] Ollama response_len=%d", self.name, len(result))
        else:
            logger.info("[%s] Ollama responded (%d chars)", self.name, len(result))
        return result

    @staticmethod
    def safe_json_loads(text: str) -> Any:
        if not text:
            logger.debug("safe_json_loads: empty input")
            return None

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text, re.IGNORECASE)
        if fence:
            candidate = fence.group(1).strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                text = candidate

        inline = re.search(r"`(\{[\s\S]*?\})`", text)
        if inline:
            try:
                return json.loads(inline.group(1))
            except json.JSONDecodeError:
                pass

        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end > obj_start:
            candidate = text[obj_start : obj_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if arr_start != -1 and arr_end > arr_start:
            candidate = text[arr_start : arr_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

        logger.warning(
            "safe_json_loads: all 6 recovery stages failed (len=%d, preview=%r)",
            len(text),
            text[:150],
        )
        return None

    @staticmethod
    def ensure_list_of_dicts(payload: Any) -> list[dict[str, Any]]:
        if not payload:
            return []
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _normalize_ollama_url(url: str) -> str:
        cleaned = (url or "").rstrip("/")
        if cleaned.endswith("/api/generate"):
            return cleaned
        if cleaned.endswith("/api"):
            return f"{cleaned}/generate"
        return f"{cleaned}/api/generate" if cleaned else "http://localhost:11434/api/generate"

    def build_prompt(self, code_snippet: str, task: str, instructions: Optional[str] = None) -> str:
        parts = []
        if self.system_instructions:
            parts.append(self.system_instructions)
        if instructions:
            parts.append(instructions.strip())
        if task:
            parts.append(task.strip())
        parts.append("Return ONLY valid JSON. No markdown or code fences.")
        parts.append(f"Input:\n{code_snippet}")
        return "\n\n".join(parts)

    def run(self, code_snippet: str, task: str, instructions: Optional[str] = None) -> AgentResult:
        prompt = self.build_prompt(code_snippet, task, instructions)
        raw = self.send_prompt(prompt)
        parsed = self.safe_json_loads(raw)
        if parsed is None:
            return AgentResult(agent=self.name, findings=[], logs=[f"[{self.name}] Invalid or empty response."])
        try:
            result = AgentResult.model_validate(parsed)
        except Exception as exc:
            logger.warning("Agent %s returned invalid payload: %s", self.name, exc)
            return AgentResult(
                agent=self.name,
                findings=[],
                logs=[f"[{self.name}] Invalid response ignored: {exc}"],
            )
        if not result.agent:
            result.agent = self.name
        return result


class TestEchoAgent(BaseAgent):
    def analyze(self, text: str) -> list[dict[str, Any]]:
        raw = self.send_prompt(f"Echo back an empty JSON array. Input length: {len(text)}")
        parsed = self.safe_json_loads(raw)
        return self.ensure_list_of_dicts(parsed)
