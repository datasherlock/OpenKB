"""Tests for LiteLLM Gemini and Vertex AI compatibility patches."""

import unittest
from openkb.litellm_patch import _split_fn_response_parts, apply_litellm_patches


class TestLiteLLMPatch(unittest.TestCase):
    def test_split_fn_response_parts_preserves_normal_turns(self):
        contents = [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Hi there!"}]},
            {"role": "user", "parts": [{"text": "How are you?"}]},
        ]
        result = _split_fn_response_parts(contents)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[1]["role"], "model")
        self.assertEqual(result[2]["role"], "user")

    def test_split_fn_response_parts_preserves_pure_function_response(self):
        contents = [
            {"role": "user", "parts": [{"text": "Read index"}]},
            {"role": "model", "parts": [{"function_call": {"name": "read_file", "args": {"path": "index.md"}}}]},
            {"role": "user", "parts": [{"function_response": {"name": "read_file", "response": {"content": "index content"}}}]},
        ]
        result = _split_fn_response_parts(contents)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[2]["parts"]), 1)
        self.assertIn("function_response", result[2]["parts"][0])

    def test_split_fn_response_parts_splits_multimodal_turn(self):
        fn_part = {"function_response": {"name": "get_image", "response": {"content": ""}}}
        img_part = {"inline_data": {"mime_type": "image/png", "data": "base64data"}}
        contents = [
            {"role": "user", "parts": [{"text": "Show diagram"}]},
            {"role": "model", "parts": [{"function_call": {"name": "get_image", "args": {"image_path": "diagram.png"}}}]},
            {"role": "user", "parts": [fn_part, img_part]},
        ]
        result = _split_fn_response_parts(contents)
        self.assertEqual(len(result), 4)
        # Turn 2: only function_response
        self.assertEqual(result[2]["role"], "user")
        self.assertEqual(len(result[2]["parts"]), 1)
        self.assertEqual(result[2]["parts"][0], fn_part)
        # Turn 3: only inline_data
        self.assertEqual(result[3]["role"], "user")
        self.assertEqual(len(result[3]["parts"]), 1)
        self.assertEqual(result[3]["parts"][0], img_part)

    def test_split_fn_response_parts_supports_camelcase(self):
        fn_part = {"functionResponse": {"name": "get_image", "response": {"content": ""}}}
        img_part = {"inlineData": {"mimeType": "image/png", "data": "base64data"}}
        contents = [
            {"role": "user", "parts": [{"text": "Show diagram"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "get_image", "args": {}}}]},
            {"role": "user", "parts": [fn_part, img_part]},
        ]
        result = _split_fn_response_parts(contents)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[2]["parts"][0], fn_part)
        self.assertEqual(result[3]["parts"][0], img_part)

    def test_split_fn_response_parts_safeguards_trailing_model_turn(self):
        contents = [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Thinking..."}]},
        ]
        result = _split_fn_response_parts(contents)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1]["role"], "user")

    def test_apply_litellm_patches_idempotent(self):
        import litellm
        apply_litellm_patches()
        apply_litellm_patches()
        self.assertTrue(getattr(litellm.VertexGeminiConfig._transform_messages, "_openkb_patched", False))
        self.assertTrue(getattr(litellm.GoogleAIStudioGeminiConfig._transform_messages, "_openkb_patched", False))

    def test_pageindex_client_allows_adc_providers(self):
        from pageindex import PageIndexClient
        import tempfile
        apply_litellm_patches()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Should not raise PageIndexError for vertex_ai models without VERTEX_AI_API_KEY
            client = PageIndexClient(model="vertex_ai/gemini-3.8-flash", storage_path=tmpdir)
            self.assertIsNotNone(client)


if __name__ == "__main__":
    unittest.main()
