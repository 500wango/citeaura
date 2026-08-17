import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import bootstrap as B
import generate as GEN
import geolib as G
import sample as S


class WorkDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = G.WORK
        G.WORK = Path(self._tmp.name)
        self.slug = "boottest"
        self.pdir = G.project_dir(self.slug)
        (self.pdir / "evidence").mkdir(parents=True)

    def tearDown(self):
        G.WORK = self._orig
        self._tmp.cleanup()

    def write_config(self, cfg):
        self.pdir.mkdir(parents=True, exist_ok=True)
        (self.pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")


BASE_CFG = {
    "brand": {"name": "测试品牌", "aliases": [], "site": "https://t.example.com"},
    "competitors": [
        {"name": "竞品A", "aliases": [], "market": "cn", "confirmed": False},
        {"name": "竞品B", "aliases": [], "market": "cn", "confirmed": False},
        {"name": "老牌竞品", "aliases": [], "market": "cn"},  # 旧数据无字段，视为已确认
    ],
    "market": "cn",
    "questions": [{"id": "q001", "group": "recommendation", "market": "cn", "text": "有什么好用的工具？"}],
}


class TestHomepageFirst(WorkDirCase):
    def test_root_is_first_page_not_highest_scored(self):
        home = "https://t.example.com/"
        deep = "https://t.example.com/blog/hot-article"
        G.write_jsonl(self.pdir / "evidence" / "pages.jsonl", [
            {"url": home, "title": "首页", "text": "首页正文 " * 50, "word_count": 100},
            {"url": deep, "title": "高分页", "text": "高分页正文 " * 50, "word_count": 100},
        ])
        G.write_json(self.pdir / "audit.json", {"pages": [
            {"url": home, "score": 1},
            {"url": deep, "score": 99},
        ]})
        digest = B._site_digest(self.slug)
        blocks = [b for b in digest.split("## Page:") if b.strip()]
        self.assertTrue(blocks, "digest 不应为空")
        self.assertIn(home, blocks[0], "摘要首块必须是首页（pages.jsonl 第一条），而不是高分页")
        self.assertNotIn(deep, blocks[0])

    def test_unscored_pages_sort_after_measured_pages(self):
        home = "https://t.example.com/"
        deep = "https://t.example.com/features"
        contact = "https://t.example.com/contact"
        G.write_jsonl(self.pdir / "evidence" / "pages.jsonl", [
            {"url": home, "title": "Home", "text": "Home body", "word_count": 2},
            {"url": contact, "title": "Contact", "text": "Contact body", "word_count": 2},
            {"url": deep, "title": "Features", "text": "Feature body", "word_count": 2},
        ])
        G.write_json(self.pdir / "audit.json", {"pages": [
            {"url": home, "score": 10},
            {"url": contact, "score": None},
            {"url": deep, "score": 90},
        ]})
        digest = B._site_digest(self.slug)
        self.assertLess(digest.index(home), digest.index(deep))
        self.assertLess(digest.index(deep), digest.index(contact))


class TestCompetitorConfirmation(WorkDirCase):
    def _manual_file(self, answer):
        f = Path(self._tmp.name) / "manual.md"
        f.write_text(
            "# 采样表\n\n## platform: deepseek\n> 国内\n\n"
            f"### q001 · 有什么好用的工具？\n\n```answer\n{answer}\n```\n",
            "utf-8")
        return str(f)

    def test_single_mention_does_not_confirm_competitor(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        S.sample_import(self.slug, self._manual_file("我推荐竞品A，它挺好用的。"))
        cfg = G.load_config(self.slug)
        by_name = {c["name"]: c for c in cfg["competitors"]}
        self.assertFalse(by_name["竞品A"].get("confirmed"), "单次提及不足以确认竞品")
        self.assertFalse(by_name["竞品B"].get("confirmed"), "未被提到的竞品保持未确认")
        sample_path = next((self.pdir / "samples").glob("sample-*.jsonl"))
        imported = G.read_jsonl(sample_path)[0]
        self.assertIsNone(imported["search_enabled"])
        self.assertEqual(imported["sampling_label"], "manual_product_interface")
        self.assertTrue(imported["run_id"].startswith("sample-"))

    def test_sample_import_rejects_oversized_file(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        path = Path(self._tmp.name) / "oversized.md"
        path.write_text("x" * 32, "utf-8")
        with mock.patch.object(S, "MAX_IMPORT_BYTES", 16):
            with self.assertRaises(SystemExit):
                S.sample_import(self.slug, str(path))

    def test_sample_import_rejects_duplicate_platform_sections(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        path = Path(self._tmp.name) / "duplicate.md"
        path.write_text(
            "## platform: deepseek\n\n### q001 · 有什么好用的工具？\n\n```answer\n答案\n```\n"
            "## platform: deepseek\n\n### q001 · 有什么好用的工具？\n\n```answer\n答案\n```\n",
            "utf-8")
        with self.assertRaises(SystemExit):
            S.sample_import(self.slug, str(path))

    def test_single_mentions_do_not_rewrite_config(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        S.sample_import(self.slug, self._manual_file("我推荐竞品A。"))
        bak = self.pdir / ".geo.bak"
        n1 = len(list(bak.glob("geo-*.json"))) if bak.exists() else 0
        self.assertEqual(n1, 0)
        S.sample_import(self.slug, self._manual_file("我推荐竞品A。"))
        n2 = len(list(bak.glob("geo-*.json")))
        self.assertEqual(n2, 0, "证据不足时不应写 geo.json")

    def test_repeated_unprompted_evidence_confirms_competitor(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        cfg = G.load_config(self.slug)
        rows = []
        for qid in ("q001", "q002"):
            answer = "我推荐竞品A，它适合这个场景。"
            rows.append({"ok": True, "question_id": qid, "question": "工具怎么选？",
                         "platform": "deepseek", "brand_in_question": False,
                         "analysis": S.analyze_answer(answer, cfg), "needs_review": False})
        S.confirm_competitors(self.slug, rows)
        self.assertTrue(next(c for c in G.load_config(self.slug)["competitors"]
                             if c["name"] == "竞品A")["confirmed"])

    def test_unconfirmed_marked_in_facts_md(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        md = B.render_facts(self.slug, {"name": "测试品牌"})
        self.assertIn("unconfirmed_candidate", md)
        unconfirmed_line = next(line for line in md.splitlines() if "竞品A" in line)
        self.assertIn("unconfirmed_candidate", unconfirmed_line)
        confirmed_line = next(line for line in md.splitlines() if "老牌竞品" in line)
        self.assertNotIn("unconfirmed_candidate", confirmed_line)


class TestDraftPromptCompetitors(WorkDirCase):
    def test_unconfirmed_competitors_excluded_from_prompt(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        outline = {
            "market": "cn", "target_question": "有什么好用的工具？", "type": "对比",
            "facts_to_use": [], "sections": ["开头", "对比"],
            "requirements": {"min_words": 800, "min_h2": 3},
        }
        captured = {}

        def fake_ask(plat, prompt, timeout=300, **_kwargs):
            captured["prompt"] = prompt
            return {"ok": True, "answer": "# 初稿"}

        with mock.patch.object(S, "available", return_value=True), \
             mock.patch.object(S, "ask", side_effect=fake_ask):
            GEN.draft(self.slug, outline, provider="deepseek")
        prompt = captured.get("prompt", "")
        self.assertNotIn("竞品A", prompt, "confirmed:false 的竞品不得进初稿 prompt")
        self.assertNotIn("竞品B", prompt)
        self.assertIn("老牌竞品", prompt, "无 confirmed 字段的旧数据视为已确认")


class TestGeneratedAssetSafety(WorkDirCase):
    def test_untrusted_question_id_cannot_escape_asset_directory(self):
        cfg = json.loads(json.dumps(BASE_CFG, ensure_ascii=False))
        cfg["questions"] = [{"id": "../../escaped", "group": "recommendation", "market": "cn", "text": "如何选择工具？"}]
        self.write_config(cfg)
        result = GEN.run(self.slug, which=["outlines"])
        self.assertTrue((self.pdir / "assets" / "outlines" / "q001.md").is_file())
        self.assertFalse((self.pdir / "escaped.md").exists())
        self.assertFalse((Path(self._tmp.name) / "escaped.md").exists())
        self.assertIn("assets/outlines/q001.md", result["drafts"])

    def test_jsonld_omits_placeholders_and_unsupported_types(self):
        cfg = json.loads(json.dumps(BASE_CFG, ensure_ascii=False))
        self.write_config(cfg)
        schemas = GEN.gen_jsonld(self.slug)
        self.assertEqual(set(schemas), {"organization"})
        self.assertNotIn("<填", json.dumps(schemas, ensure_ascii=False))
        self.assertNotIn("FAQPage", json.dumps(schemas))

    def test_global_assets_do_not_reuse_chinese_or_empty_faq(self):
        cfg = json.loads(json.dumps(BASE_CFG, ensure_ascii=False))
        cfg["market"] = "global"
        cfg["brand"]["industry"] = "金融科技"
        cfg["questions"] = [{"id": "q101", "market": "global", "group": "recommendation",
                             "text": "What are reliable transfer apps?"}]
        self.write_config(cfg)
        (self.pdir / "content").mkdir(parents=True)
        (self.pdir / "content" / "facts.md").write_text(
            "# Facts\n\n## 一句话定义\n\n> 测试品牌是一款跨境支付工具。\n", "utf-8")
        llms = GEN.gen_llms_txt(self.slug, "en")
        self.assertNotRegex(llms, r"[一-鿿]")
        self.assertEqual(GEN.gen_faq_block(self.slug, "en"), "")


if __name__ == "__main__":
    unittest.main()
