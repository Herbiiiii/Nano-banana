"""Локальные проверки без реальных вызовов API."""
import unittest

from app.services.generation_prompt import enhance_prompt_for_image_generation
from app.services.image_api_provider import infer_image_api_provider
from app.services.bananalab_response import detail_from_response_body, find_image_in_json, humanize_api_error, is_content_policy_error


class TestProvider(unittest.TestCase):
    def test_nb_prefix(self):
        self.assertEqual(infer_image_api_provider("nb_abc"), "bananalab")

    def test_openrouter_prefix(self):
        self.assertEqual(infer_image_api_provider("sk-or-v1-abc"), "openrouter")

    def test_replicate_default(self):
        self.assertEqual(infer_image_api_provider("r8_xx"), "replicate")
        self.assertEqual(infer_image_api_provider(""), "replicate")


class TestImageModels(unittest.TestCase):
    def test_gpt_model_requires_openrouter(self):
        from app.services.image_models import get_provider_for_model, select_api_key_for_model

        keys = {"replicate": "r8_x", "bananalab": "nb_x", "openrouter": ""}
        self.assertIsNone(get_provider_for_model("gpt-5-image", keys))

        keys["openrouter"] = "sk-or-v1-test"
        self.assertEqual(get_provider_for_model("gpt-5-image", keys), "openrouter")
        self.assertEqual(
            select_api_key_for_model("gpt-5-image", keys, None),
            "sk-or-v1-test",
        )

    def test_nano_models_use_single_provider(self):
        from app.services.image_models import get_provider_for_model

        keys = {"replicate": "r8_x", "bananalab": "nb_x", "openrouter": "sk-or_x"}
        self.assertEqual(get_provider_for_model("nano-banana-pro", keys), "bananalab")
        self.assertEqual(get_provider_for_model("nano-banana-pro-r8", keys), "replicate")
        self.assertIsNone(get_provider_for_model("nano-banana-pro", {"replicate": "r8_x", "bananalab": "", "openrouter": ""}))
        self.assertIsNone(get_provider_for_model("nano-banana-pro-r8", {"replicate": "", "bananalab": "nb_x", "openrouter": ""}))


class TestPrompt(unittest.TestCase):
    def test_text_to_image_prefix(self):
        p = enhance_prompt_for_image_generation("red apple", None, 0)
        self.assertIn("Generate an image", p)

    def test_ref_single(self):
        p = enhance_prompt_for_image_generation("add hat", ["x"], 1)
        self.assertIn("STRICT INSTRUCTIONS", p)


class TestSecurityHelpers(unittest.TestCase):
    def test_generate_storage_object_name(self):
        from app.security_helpers import generate_storage_object_name

        name = generate_storage_object_name("results", "jpg")
        self.assertTrue(name.startswith("images/results/"))
        self.assertTrue(name.endswith(".jpg"))
        self.assertEqual(len(name.split("/")[-1].split(".")[0]), 32)

    def test_allowed_reference_url(self):
        from app.config import Settings
        from app.security_helpers import is_allowed_reference_url

        s = Settings(
            SECRET_KEY="x" * 64,
            MINIO_PUBLIC_URL="https://storage.example.com",
            MINIO_BUCKET="nano-banana-images",
            API_URL="https://app.example.com",
        )
        ok = "https://storage.example.com/nano-banana-images/images/references/abc.jpg"
        legacy = "https://storage.example.com/nano-banana-images/images/references/ref_20260101_120000_abcd.jpg"
        bad = "https://evil.com/nano-banana-images/images/references/abc.jpg"
        self.assertTrue(is_allowed_reference_url(ok, s))
        self.assertTrue(is_allowed_reference_url(legacy, s))
        self.assertFalse(is_allowed_reference_url(bad, s))

    def test_localhost_reference_alias(self):
        from app.config import Settings
        from app.security_helpers import is_allowed_reference_url

        s = Settings(
            SECRET_KEY="x" * 64,
            MINIO_PUBLIC_URL="http://localhost:9000",
            MINIO_BUCKET="nano-banana-images",
        )
        url = "http://127.0.0.1:9000/nano-banana-images/images/results/deadbeef.jpg"
        self.assertTrue(is_allowed_reference_url(url, s))


class TestResultStorage(unittest.TestCase):
    def test_persist_prefers_image_data(self):
        from unittest.mock import MagicMock
        from app.services.result_storage import persist_generation_result

        minio = MagicMock()
        minio.upload_image.return_value = {
            "url": "http://localhost:9000/bucket/images/results/abc.jpg",
            "path": "images/results/abc.jpg",
        }
        out = persist_generation_result(minio, {"image_data": b"x" * 600, "image_url": "https://evil.com/x.jpg"})
        self.assertIsNotNone(out)
        minio.upload_image.assert_called_once()


class TestBanalabJobUrl(unittest.TestCase):
    def test_absolute_status_url_from_path(self):
        from app.services.bananalab_response import absolute_job_status_url

        u = absolute_job_status_url(
            "https://api.bananalab.pw",
            {"status_url": "/v1/jobs/923f3213-cda5-4e13-8e47-2ea73383aefb", "status": "queued"},
        )
        self.assertEqual(u, "https://api.bananalab.pw/v1/jobs/923f3213-cda5-4e13-8e47-2ea73383aefb")

    def test_bananahub_status_url_with_api_prefix(self):
        from app.services.bananalab_response import absolute_job_status_url

        u = absolute_job_status_url(
            "https://bananahub.app/api",
            {
                "status_url": "/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
                "status": "queued",
            },
        )
        self.assertEqual(
            u,
            "https://bananahub.app/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
        )

    def test_bananahub_legacy_io_host_still_supported(self):
        from app.services.bananalab_response import absolute_job_status_url

        u = absolute_job_status_url(
            "https://bananahub.io/api",
            {
                "status_url": "/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
                "status": "queued",
            },
        )
        self.assertEqual(
            u,
            "https://bananahub.io/api/v1/jobs/019eb30e-1769-70ff-b648-e207a06b58d0",
        )

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


class TestHumanizeApiError(unittest.TestCase):
    _CF_521_HTML = """<!DOCTYPE html>
<html><head><title>bananahub.io | 521: Web server is down</title></head>
<body><div class="cf-error-details"><h1>Web server is down</h1>
<p>Error code 521</p></div></body></html>"""

    def test_cloudflare_521_html(self):
        msg = humanize_api_error(self._CF_521_HTML, 521)
        self.assertIn("521", msg)
        self.assertNotIn("<!DOCTYPE", msg)
        self.assertNotIn("cf-error-details", msg)

    def test_json_detail_unchanged(self):
        msg = humanize_api_error({"detail": "Invalid API key"})
        self.assertEqual(msg, "Invalid API key")

    def test_model_paused_humanized(self):
        msg = humanize_api_error({"detail": "Model is paused due to high load"})
        self.assertIn("на паузе", msg.lower())
        self.assertNotIn("перегружен", msg.lower())

    def test_project_paused_503_not_overloaded(self):
        msg = humanize_api_error({"detail": "Project is paused."}, 503)
        self.assertIn("на паузе", msg.lower())
        self.assertNotIn("перегружен", msg.lower())

    def test_content_policy_error_hint(self):
        raw = "Request blocked by safety moderation filter"
        self.assertTrue(is_content_policy_error(raw))
        msg = humanize_api_error(raw)
        self.assertIn("фильтр безопасности", msg.lower())
        self.assertIn("переформулируйте", msg.lower())

    def test_nested_detail_message(self):
        msg = humanize_api_error(
            {"detail": {"message": "Project is paused.", "field": None, "details": None}},
            503,
        )
        self.assertIn("на паузе", msg.lower())

    def test_is_bananalab_paused_message(self):
        from app.services.bananalab_response import is_bananalab_paused_message

        self.assertTrue(is_bananalab_paused_message("Project is paused."))
        self.assertTrue(is_bananalab_paused_message("Проект Banana Lab на паузе."))
        self.assertFalse(is_bananalab_paused_message("rate limit exceeded"))

    def test_is_bananalab_unavailable_message(self):
        from app.services.bananalab_response import (
            BANANALAB_PROVIDER_UNAVAILABLE_MESSAGE,
            is_bananalab_unavailable_message,
        )

        self.assertTrue(
            is_bananalab_unavailable_message(
                "HTTPSConnectionPool(host='bananahub.io', port=443): "
                "Failed to establish a new connection: [Errno 111] Connection refused"
            )
        )
        self.assertTrue(
            is_bananalab_unavailable_message(
                "Failed to resolve 'bananahub.io' ([Errno -2] Name or service not known)"
            )
        )
        self.assertFalse(is_bananalab_unavailable_message("Project is paused."))

        msg = humanize_api_error(
            "Failed to connect to bananahub.io port 443: Connection refused"
        )
        self.assertEqual(msg, BANANALAB_PROVIDER_UNAVAILABLE_MESSAGE)

    def test_is_bananalab_upstream_no_image_message(self):
        from app.services.bananalab_response import (
            is_bananalab_upstream_no_image_message,
            humanize_api_error,
        )

        self.assertTrue(is_bananalab_upstream_no_image_message("Upstream returned no image"))
        self.assertTrue(
            is_bananalab_upstream_no_image_message("Исходный поток не вернул изображение.")
        )
        self.assertFalse(is_bananalab_upstream_no_image_message("Project is paused."))

        msg = humanize_api_error("Upstream returned no image")
        self.assertIn("повторяем автоматически", msg.lower())

    def test_upstream_no_image_retry_delay(self):
        from app.services.bananalab_response import upstream_no_image_retry_delay_seconds

        self.assertEqual(upstream_no_image_retry_delay_seconds(0, 3), 3.0)
        self.assertEqual(upstream_no_image_retry_delay_seconds(1, 3), 5.0)
        self.assertEqual(upstream_no_image_retry_delay_seconds(4, 3), 11.0)
        self.assertEqual(upstream_no_image_retry_delay_seconds(10, 3), 15.0)

    def test_http_status_without_body(self):
        msg = humanize_api_error("", 503)
        self.assertIn("503", msg)

    def test_long_plain_text_truncated(self):
        msg = humanize_api_error("x" * 1000)
        self.assertLessEqual(len(msg), 520)
        self.assertTrue(msg.endswith("…"))


if __name__ == "__main__":
    unittest.main()
