"""LiteLLM compatibility patches for Google Gemini and Vertex AI."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PATCHED = False


def _split_fn_response_parts(contents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split tool responses containing multimodal parts into separate turns.

    In the Google Gemini / Vertex AI API, a function response turn following a
    model function call must contain ONLY function responses. When a tool
    (such as `get_image`) returns an image or file along with a function
    response, LiteLLM combines them into a single `role="user"` turn containing
    both `function_response` and `inline_data`. Vertex AI rejects this mixed
    turn with:
        HTTP 400: "Requests ending with a model turn are not supported."
    because the invalid function response turn is discarded by the API parser,
    leaving the preceding model function call turn as the trailing turn.

    By separating function response parts into their own turn and subsequent
    multimodal parts (e.g. `inline_data`) into a following `user` turn, Gemini
    correctly parses both the tool response and the attached media.
    Additionally, if a message list ends in a `model` turn, a blank user turn is
    appended to satisfy the strict turn-alternation requirement.
    """
    new_contents: list[dict[str, Any]] = []
    for c in contents:
        parts = c.get("parts", [])
        has_fn_response = any(
            "function_response" in p or "functionResponse" in p for p in parts
        )
        has_other = any(
            "function_response" not in p and "functionResponse" not in p for p in parts
        )

        if has_fn_response and has_other:
            fn_parts = [
                p for p in parts if "function_response" in p or "functionResponse" in p
            ]
            other_parts = [p for p in parts if p not in fn_parts]

            new_contents.append({"role": c.get("role", "user"), "parts": fn_parts})
            new_contents.append({"role": "user", "parts": other_parts})
        else:
            new_contents.append(c)

    if new_contents and new_contents[-1].get("role") == "model":
        new_contents.append({"role": "user", "parts": [{"text": " "}]})

    return new_contents


def apply_litellm_patches() -> None:
    """Apply LiteLLM compatibility patches for Gemini and Vertex AI."""
    global _PATCHED
    if _PATCHED:
        return

    try:
        import litellm
    except ImportError:
        return

    # Patch Vertex AI and Google AI Studio config transformers
    for config_cls in (
        getattr(litellm, "VertexGeminiConfig", None),
        getattr(litellm, "GoogleAIStudioGeminiConfig", None),
    ):
        if config_cls is None:
            continue
        orig_transform = getattr(config_cls, "_transform_messages", None)
        if orig_transform is not None and not getattr(
            orig_transform, "_openkb_patched", False
        ):

            def _make_patched_transform(original_fn):
                def _patched_transform_messages(
                    self, messages, model=None, litellm_params=None
                ):
                    contents = original_fn(
                        self,
                        messages=messages,
                        model=model,
                        litellm_params=litellm_params,
                    )
                    return _split_fn_response_parts(contents)

                _patched_transform_messages._openkb_patched = True
                return _patched_transform_messages

            setattr(
                config_cls,
                "_transform_messages",
                _make_patched_transform(orig_transform),
            )

    # Also patch direct module functions if present
    try:
        from litellm.llms.vertex_ai.gemini import transformation as vertex_trans

        orig_convert = getattr(
            vertex_trans, "_gemini_convert_messages_with_history", None
        )
        if orig_convert is not None and not getattr(
            orig_convert, "_openkb_patched", False
        ):

            def _make_patched_convert(original_fn):
                def _patched_convert(
                    messages,
                    model=None,
                    litellm_params=None,
                    custom_llm_provider=None,
                ):
                    contents = original_fn(
                        messages,
                        model=model,
                        litellm_params=litellm_params,
                        custom_llm_provider=custom_llm_provider,
                    )
                    return _split_fn_response_parts(contents)

                _patched_convert._openkb_patched = True
                return _patched_convert

            patched_fn = _make_patched_convert(orig_convert)
            vertex_trans._gemini_convert_messages_with_history = patched_fn

            try:
                from litellm.llms.vertex_ai.gemini import (
                    vertex_and_google_ai_studio_gemini as v_and_g,
                )

                v_and_g._gemini_convert_messages_with_history = patched_fn
            except Exception:
                pass

            try:
                from litellm.llms.gemini.chat import (
                    transformation as chat_transformation,
                )

                chat_transformation._gemini_convert_messages_with_history = patched_fn
            except Exception:
                pass
    except Exception as exc:
        logger.debug("Could not patch litellm vertex transformation: %s", exc)

    # Patch PageIndex premature API key validation for cloud auth / ADC / IAM providers
    try:
        import pageindex.client

        orig_validate = getattr(
            pageindex.client.PageIndexClient, "_validate_llm_provider", None
        )
        if orig_validate is not None and not getattr(
            orig_validate, "_openkb_patched", False
        ):
            CLOUD_AUTH_PROVIDERS = {
                "vertex_ai",
                "vertex_ai_beta",
                "bedrock",
                "sagemaker",
                "watsonx",
                "chatgpt",
                "github_copilot",
            }

            def _patched_validate_llm_provider(model: str) -> None:
                try:
                    import litellm

                    _, provider, _, _ = litellm.get_llm_provider(model=model)
                    if provider in CLOUD_AUTH_PROVIDERS:
                        return
                except Exception:
                    pass
                return orig_validate(model)

            _patched_validate_llm_provider._openkb_patched = True
            pageindex.client.PageIndexClient._validate_llm_provider = staticmethod(
                _patched_validate_llm_provider
            )
    except Exception as exc:
        logger.debug("Could not patch pageindex: %s", exc)

    _PATCHED = True
