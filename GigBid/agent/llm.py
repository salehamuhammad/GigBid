"""Model access. Every node's model comes from agent/config.yaml (never from code); prompts come
from agent/prompts/<name>.md. Three behaviours:

  * openai_compatible  -- Groq / OpenRouter / Together / Ollama / vLLM / OpenAI via ChatOpenAI
  * fallback           -- on error the profile's `fallback_model` is tried once, then the
                          node's deterministic heuristic (so a thread degrades instead of dying)
  * offline            -- no network at all: the heuristic is the answer; tokens are estimated

Each call returns a Usage record so every trace shows tokens and cost per node (E3).
"""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from agent.settings import get_settings

T = TypeVar("T", bound=BaseModel)
PROMPTS = get_settings().root / "agent" / "prompts"


@lru_cache
def load_prompt(name: str) -> dict:
    raw = (PROMPTS / f"{name}.md").read_text()
    version = (re.search(r"^version:\s*(\S+)", raw, re.M) or [None, "1"])[1]
    system = re.search(r"## SYSTEM\n(.*?)(?=\n## USER|\Z)", raw, re.S)
    user = re.search(r"## USER\n(.*)\Z", raw, re.S)
    return {"version": version, "system": (system.group(1) if system else "").strip(), "user": (user.group(1) if user else "").strip()}


def render(template: str, variables: dict[str, Any]) -> str:
    def sub(m):
        v = variables.get(m.group(1), "")
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def extract_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m: raise
        return json.loads(m.group(0))


class LLM:
    def __init__(self, profile_name: str | None = None):
        s = get_settings()
        self.profile_name = profile_name or s.profile_name
        self.profile = s.cfg["models"]["profiles"][self.profile_name]
        self.offline = self.profile.get("provider") == "offline"
        self.temperature = s.get("models", "temperature", default=0.2)
        self.timeout = s.get("models", "request_timeout_s", default=60)
        self._clients: dict[str, Any] = {}
        if not self.offline:
            key = self.profile.get("api_key") or os.getenv(self.profile.get("api_key_env", ""), "")
            if not key:
                raise RuntimeError(f"Model profile '{self.profile_name}' needs {self.profile.get('api_key_env')} in the environment "
                                   f"(or set MODEL_PROFILE=offline).")
            self.api_key = key
            self.base_url = self.profile.get("base_url") or (os.getenv(self.profile.get("base_url_env", ""), "http://localhost:11434") + self.profile.get("base_url_suffix", ""))

    def model_for(self, node: str) -> str:
        if self.offline: return "offline-heuristic"
        return self.profile["nodes"].get(node) or self.profile.get("fallback_model")

    def chat_model(self, node: str, model: str | None = None):
        """A LangChain chat model for `node` (also used by the ReAct / supervisor baselines)."""
        from langchain_openai import ChatOpenAI
        name = model or self.model_for(node)
        if name not in self._clients:
            self._clients[name] = ChatOpenAI(model=name, base_url=self.base_url, api_key=self.api_key, temperature=self.temperature,
                                              timeout=self.timeout, max_retries=1)
        return self._clients[name]

    def cost(self, model: str, tin: int, tout: int) -> float:
        pin, pout = (self.profile.get("price_per_mtok", {}) or {}).get(model, [0, 0])
        return round((tin * pin + tout * pout) / 1e6, 6)

    async def complete(self, node: str, system: str, user: str, model: str | None = None) -> tuple[str, dict]:
        from langchain_core.messages import HumanMessage, SystemMessage
        name = model or self.model_for(node)
        t0 = time.perf_counter()
        msg = await self.chat_model(node, name).ainvoke([SystemMessage(system), HumanMessage(user)], config={"metadata": {"node": node}, "run_name": f"llm:{node}"})
        um = getattr(msg, "usage_metadata", None) or {}
        tin, tout = um.get("input_tokens") or est_tokens(system + user), um.get("output_tokens") or est_tokens(str(msg.content))
        usage = {"node": node, "model": name, "input_tokens": tin, "output_tokens": tout, "cost_usd": self.cost(name, tin, tout),
                 "latency_ms": int((time.perf_counter() - t0) * 1000), "estimated": not um, "fallback": False}
        return str(msg.content), usage

    async def structured(self, node: str, prompt: str, variables: dict, schema: type[T], fallback: Callable[[], T]) -> tuple[T, dict]:
        """Ask `node`'s model for an object of `schema`. Order: model -> fallback model -> heuristic."""
        p = load_prompt(prompt)
        system = p["system"] + "\n\nReturn ONLY one JSON object matching this JSON Schema:\n" + json.dumps(schema.model_json_schema())
        user = render(p["user"], variables)
        t0 = time.perf_counter()
        if self.offline:
            obj = fallback()
            return obj, {"node": node, "model": "offline-heuristic", "input_tokens": est_tokens(system + user), "output_tokens": est_tokens(obj.model_dump_json()),
                         "cost_usd": 0.0, "latency_ms": int((time.perf_counter() - t0) * 1000), "estimated": True, "fallback": False, "prompt_version": p["version"]}
        errors, total = [], {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        for model in dict.fromkeys([self.model_for(node), self.profile.get("fallback_model")]):
            if not model: continue
            try:
                text, usage = await self.complete(node, system, user, model)
                for k in total: total[k] += usage[k]
                obj = schema.model_validate(extract_json(text))
                return obj, {**usage, **total, "fallback": model != self.model_for(node), "prompt_version": p["version"]}
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                errors.append(f"{model}: invalid output ({type(e).__name__})")
            except Exception as e:  # network, rate limit, auth
                errors.append(f"{model}: {type(e).__name__}: {str(e)[:120]}")
        obj = fallback()
        return obj, {"node": node, "model": "heuristic-fallback", **total, "latency_ms": int((time.perf_counter() - t0) * 1000),
                     "estimated": True, "fallback": True, "errors": errors, "prompt_version": p["version"]}


@lru_cache
def get_llm(profile_name: str | None = None) -> LLM:
    return LLM(profile_name)
