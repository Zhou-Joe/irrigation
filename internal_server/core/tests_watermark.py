"""Personalized watermark rendering and non-script fallback boundaries."""
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class WatermarkRenderingTests(SimpleTestCase):
    def render(self, **overrides):
        context = {
            'user': SimpleNamespace(is_authenticated=True, pk=37),
            'watermark_text': '测试用户 · 13800138000 · 园艺',
            'watermark_warning': '仅限内部沟通，严禁外传',
        }
        context.update(overrides)
        return render_to_string('core/_watermark.html', context)

    def test_anonymous_pages_never_render_personal_watermarks(self):
        html = self.render(user=SimpleNamespace(is_authenticated=False))
        self.assertNotIn('data-site-watermark', html)
        self.assertNotIn('13800138000', html)

    def test_empty_identity_does_not_create_an_empty_overlay(self):
        self.assertNotIn('data-site-watermark', self.render(watermark_text=''))

    def test_identity_cannot_escape_its_attribute_or_create_active_markup(self):
        html = self.render(watermark_text='"><script>alert(1)</script>&')
        self.assertNotIn('<script>', html)
        self.assertIn('&quot;&gt;&lt;script&gt;', html)
        self.assertIn('&amp;', html)

    def test_vector_fallback_keeps_traceable_user_id_and_warning_without_javascript(self):
        html = self.render()
        self.assertIn('用户 37', html)
        self.assertIn('仅限内部沟通，严禁外传', html)
        self.assertIn('aria-hidden="true" inert', html)
        self.assertIn('patternUnits="userSpaceOnUse"', html)
