import tempfile, unittest
from dataclasses import replace
from pathlib import Path
from PIL import Image
from astrbot_plugin_sharemarket.config import Config
from astrbot_plugin_sharemarket.render.help import render_help, help_text, HELP_STYLE

class HelpArtworkTests(unittest.TestCase):
    def test_help_renders_without_private_artwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = render_help(Path(tmp) / "help.png", Config())
            with Image.open(p) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.width, 1200)
                self.assertGreater(image.height, 1000)
                image.verify()
        self.assertEqual(HELP_STYLE, "public-rules-card-v1")
        self.assertIn("纯虚拟", help_text(Config()))
        self.assertNotIn("/fx 任务", help_text(Config()))
        self.assertNotIn("/fx 赛季", help_text(Config()))

    def test_rules_follow_config(self):
        text = help_text(replace(Config(), lot_size=200, initial_cash=123456))
        self.assertIn("200 股", text)
        self.assertIn("123,456", text)
