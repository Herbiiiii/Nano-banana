"""Локальные проверки без реальных вызовов API."""
import unittest

from app.services.generation_prompt import enhance_prompt_for_image_generation
from app.services.image_api_provider import infer_image_api_provider
from app.services.bananalab_response import detail_from_response_body, find_image_in_json


class TestProvider(unittest.TestCase):
    def test_nb_prefix(self):
        self.assertEqual(infer_image_api_provider("nb_abc"), "bananalab")

    def test_replicate_default(self):
        self.assertEqual(infer_image_api_provider("r8_xx"), "replicate")
        self.assertEqual(infer_image_api_provider(""), "replicate")


class TestPrompt(unittest.TestCase):
    def test_text_to_image_prefix(self):
        p = enhance_prompt_for_image_generation("red apple", None, 0)
        self.assertIn("Generate an image", p)

    def test_ref_single(self):
        p = enhance_prompt_for_image_generation("add hat", ["x"], 1)
        self.assertIn("STRICT INSTRUCTIONS", p)


class TestBanalabJobUrl(unittest.TestCase):
    def test_absolute_status_url_from_path(self):
        from app.services.bananalab_response import absolute_job_status_url

        u = absolute_job_status_url(
            "https://api.bananalab.pw",
            {"status_url": "/v1/jobs/923f3213-cda5-4e13-8e47-2ea73383aefb", "status": "queued"},
        )
        self.assertEqual(u, "https://api.bananalab.pw/v1/jobs/923f3213-cda5-4e13-8e47-2ea73383aefb")

    def test_absolute_status_url_from_job_id(self):
        from app.services.bananalab_response import absolute_job_status_url

        u = absolute_job_status_url("https://api.example.com", {"job_id": "abc-123", "status": "queued"})
        self.assertEqual(u, "https://api.example.com/v1/jobs/abc-123")


class TestBananalabParse(unittest.TestCase):
    def test_detail_string(self):
        self.assertEqual(
            detail_from_response_body({"detail": "bad"}),
            "bad",
        )

    def test_find_url(self):
        b, u = find_image_in_json({"result": {"url": "https://example.com/a.png"}})
        self.assertIsNone(b)
        self.assertEqual(u, "https://example.com/a.png")

    def test_find_bananalab_job_done_shape(self):
        """Как в ответе GET /v1/jobs после завершения."""
        sample = {
            "job_id": "923f3213-cda5-4e13-8e47-2ea73383aefb",
            "status": "done",
            "result": {
                "image_url": "https://api.bananalab.pw/nanobanana-results/results/923f3213.png?x=1"
            },
            "error": None,
        }
        b, u = find_image_in_json(sample)
        self.assertIsNone(b)
        self.assertTrue(u.startswith("https://api.bananalab.pw/"))


if __name__ == "__main__":
    unittest.main()
