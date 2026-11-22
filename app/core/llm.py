import json
import hashlib
import time
import logging
from typing import Any, Dict, Optional, Type, Union
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models.entities import LLMCache

logger = logging.getLogger("signal_stack.llm")


class LLMMetrics:
    def __init__(self):
        self.total_calls: int = 0
        self.cache_hits: int = 0
        self.gemini_calls: int = 0
        self.groq_calls: int = 0
        self.fallback_triggers: int = 0
        self.estimated_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "cache_hits": self.cache_hits,
            "gemini_calls": self.gemini_calls,
            "groq_calls": self.groq_calls,
            "fallback_triggers": self.fallback_triggers,
            "estimated_tokens": self.estimated_tokens,
        }

    def reset(self):
        self.total_calls = 0
        self.cache_hits = 0
        self.gemini_calls = 0
        self.groq_calls = 0
        self.fallback_triggers = 0
        self.estimated_tokens = 0


metrics = LLMMetrics()


def get_llm_metrics() -> Dict[str, Any]:
    return metrics.to_dict()


def reset_llm_metrics():
    metrics.reset()


def compute_prompt_hash(
    provider: str,
    model: str,
    schema_str: str,
    system_prompt: Optional[str],
    prompt: str,
) -> str:
    raw = f"{provider}:{model}:{schema_str}:{system_prompt or ''}:{prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(self):
        self.last_gemini_call: float = 0.0
        # 15 RPM = 1 request every 4.0 seconds minimum
        self.min_gemini_interval: float = 4.0

    def _rate_limit_sleep(self):
        """Enforce rate limiting to stay well within free tier RPM."""
        if settings.APP_ENV == "test":
            return

        elapsed = time.time() - self.last_gemini_call
        if elapsed < self.min_gemini_interval:
            sleep_time = self.min_gemini_interval - elapsed
            logger.debug(f"Rate limiter sleeping for {sleep_time:.2f}s...")
            time.sleep(sleep_time)
        self.last_gemini_call = time.time()

    def _get_backoff_delay(self, attempt: int) -> float:
        if settings.APP_ENV == "test":
            return 0.01
        return 2.0 * (2 ** attempt)

    def _get_schema_details(self, schema: Union[Type[BaseModel], dict]) -> tuple[dict, str]:
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema_dict = schema.model_json_schema()
            schema_str = json.dumps(schema_dict, sort_keys=True)
            return schema_dict, schema_str
        elif isinstance(schema, dict):
            return schema, json.dumps(schema, sort_keys=True)
        else:
            raise ValueError("Schema must be a Pydantic model class or a JSON schema dictionary.")

    def _query_cache(self, prompt_hash: str) -> Optional[dict]:
        if not settings.LLM_CACHE_ENABLED:
            return None
        try:
            with Session(engine) as session:
                statement = select(LLMCache).where(LLMCache.prompt_hash == prompt_hash)
                cached = session.exec(statement).first()
                if cached:
                    return json.loads(cached.response_json)
        except Exception as e:
            logger.warning(f"Error reading LLM cache: {e}")
        return None

    def _save_cache(self, prompt_hash: str, provider: str, model: str, response_dict: dict):
        if not settings.LLM_CACHE_ENABLED:
            return
        try:
            with Session(engine) as session:
                entry = LLMCache(
                    prompt_hash=prompt_hash,
                    provider=provider,
                    model=model,
                    response_json=json.dumps(response_dict),
                )
                session.add(entry)
                session.commit()
        except Exception as e:
            logger.warning(f"Error saving to LLM cache: {e}")

    def _call_gemini(
        self,
        prompt: str,
        schema: Union[Type[BaseModel], dict],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        from google import genai
        from google.genai import types

        model_name = model or settings.GEMINI_MODEL
        client = genai.Client(api_key=api_key)

        self._rate_limit_sleep()

        config_kwargs: Dict[str, Any] = {
            "response_mime_type": "application/json",
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        if isinstance(schema, type) and issubclass(schema, BaseModel):
            config_kwargs["response_schema"] = schema
        else:
            config_kwargs["response_schema"] = schema

        config = types.GenerateContentConfig(**config_kwargs)

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )

        metrics.gemini_calls += 1
        raw_text = response.text or "{}"
        metrics.estimated_tokens += (len(prompt) + len(raw_text)) // 4

        return json.loads(raw_text)

    def _call_groq(
        self,
        prompt: str,
        schema: Union[Type[BaseModel], dict],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict:
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        from groq import Groq

        model_name = model or settings.GROQ_MODEL
        client = Groq(api_key=api_key)

        schema_dict, _ = self._get_schema_details(schema)

        instructions = (
            f"{system_prompt or 'You are an analytical intelligence engine.'}\n"
            f"You MUST return ONLY valid JSON matching this exact JSON Schema:\n"
            f"{json.dumps(schema_dict, indent=2)}\n"
            "Do not output markdown codeblocks, just raw parseable JSON."
        )

        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ]

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
        )

        metrics.groq_calls += 1
        raw_text = response.choices[0].message.content or "{}"
        metrics.estimated_tokens += (len(prompt) + len(raw_text)) // 4

        return json.loads(raw_text)

    def generate_json(
        self,
        prompt: str,
        schema: Union[Type[BaseModel], dict],
        system_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        Generate structured JSON matching the provided schema.
        Handles Gemini primary, Groq fallback, persistent SQLite caching,
        rate-limiting sleep, and exponential backoff retry.
        """
        metrics.total_calls += 1
        _, schema_str = self._get_schema_details(schema)

        chosen_provider = provider or settings.DEFAULT_LLM_PROVIDER
        chosen_model = model or (
            settings.GEMINI_MODEL if chosen_provider == "gemini" else settings.GROQ_MODEL
        )

        # 1. Check SQLite Persistent Cache
        prompt_hash = compute_prompt_hash(
            provider=chosen_provider,
            model=chosen_model,
            schema_str=schema_str,
            system_prompt=system_prompt,
            prompt=prompt,
        )

        if not force_refresh:
            cached_result = self._query_cache(prompt_hash)
            if cached_result is not None:
                metrics.cache_hits += 1
                logger.info(f"LLM cache hit: {prompt_hash[:12]}")
                return cached_result

        # 2. Attempt Primary Provider
        max_retries = 3
        primary_error = None

        if chosen_provider == "gemini":
            for attempt in range(max_retries):
                try:
                    logger.info(f"Dispatching to Gemini (attempt {attempt + 1})...")
                    result = self._call_gemini(
                        prompt=prompt,
                        schema=schema,
                        system_prompt=system_prompt,
                        model=chosen_model,
                    )
                    self._save_cache(prompt_hash, "gemini", chosen_model, result)
                    return result
                except Exception as e:
                    primary_error = e
                    logger.warning(f"Gemini error on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(self._get_backoff_delay(attempt))

        elif chosen_provider == "groq":
            for attempt in range(max_retries):
                try:
                    logger.info(f"Dispatching to Groq (attempt {attempt + 1})...")
                    result = self._call_groq(
                        prompt=prompt,
                        schema=schema,
                        system_prompt=system_prompt,
                        model=chosen_model,
                    )
                    self._save_cache(prompt_hash, "groq", chosen_model, result)
                    return result
                except Exception as e:
                    primary_error = e
                    logger.warning(f"Groq error on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(self._get_backoff_delay(attempt))

        # 3. Fallback Provider
        fallback_provider = (
            "groq" if chosen_provider == "gemini" else "gemini"
        )
        fallback_model = (
            settings.GROQ_MODEL if fallback_provider == "groq" else settings.GEMINI_MODEL
        )

        metrics.fallback_triggers += 1
        logger.info(
            f"Failing over to {fallback_provider} fallback (Primary error: {primary_error})..."
        )

        for attempt in range(max_retries):
            try:
                if fallback_provider == "groq":
                    result = self._call_groq(
                        prompt=prompt,
                        schema=schema,
                        system_prompt=system_prompt,
                        model=fallback_model,
                    )
                else:
                    result = self._call_gemini(
                        prompt=prompt,
                        schema=schema,
                        system_prompt=system_prompt,
                        model=fallback_model,
                    )

                self._save_cache(prompt_hash, fallback_provider, fallback_model, result)
                return result
            except Exception as e:
                logger.warning(f"{fallback_provider} fallback error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self._get_backoff_delay(attempt))
                else:
                    raise RuntimeError(
                        f"Both primary ({chosen_provider}) and fallback ({fallback_provider}) failed. "
                        f"Primary error: {primary_error}, Fallback error: {e}"
                    ) from e


llm_client = LLMClient()


def generate_json(
    prompt: str,
    schema: Union[Type[BaseModel], dict],
    system_prompt: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    force_refresh: bool = False,
) -> dict:
    """Convenience functional wrapper for llm_client.generate_json."""
    return llm_client.generate_json(
        prompt=prompt,
        schema=schema,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        force_refresh=force_refresh,
    )
