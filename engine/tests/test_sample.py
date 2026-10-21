import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import sample as S
import geolib as G

CFG = {
    "brand": {"name": "AIGCLINK定制家", "aliases": ["定制家"], "site": "https://aigclink.example.com"},
    "competitors": [{"name": "竞品X", "aliases": []}],
    "market": "cn",
    "questions": [],
}


def make_row(platform="deepseek", qid="Q1", rnd=1, mode="api",
             question="有什么好用的工具？", mentioned=True, probe=False):
    return {
        "platform": platform, "question_id": qid, "round": rnd, "sample_mode": mode,
        "question": question, "market": "cn", "ok": True,
        "brand_in_question": probe,
        "analysis": {
            "brand_mentioned": mentioned,
            "brand_rank": 1 if mentioned else 0,
            "candidates": [], "competitors_mentioned": [], "cited_domains": [],
            "own_domain_cited": False, "answer_chars": 10,
        },
    }


class TestAliasBoundary(unittest.TestCase):
    def test_cjk_alias_substring_still_matches(self):
        # 纯 CJK 别名保持子串匹配：中文无空格分词，右侧 CJK 延续不代表是另一个词
        r = S.analyze_answer("这个定制家很好用，推荐试试", CFG)
        self.assertTrue(r["brand_mentioned"])
        self.assertFalse(r["needs_review"])

    def test_normal_hit_not_over_excluded(self):
        r = S.analyze_answer("AIGCLINK定制家很好用", CFG)
        self.assertTrue(r["brand_mentioned"])
        self.assertFalse(r["needs_review"])

    def test_negated_hit_not_counted_and_flagged(self):
        r = S.analyze_answer("这不是全屋定制家居类工具", CFG)
        self.assertFalse(r["brand_mentioned"])
        self.assertTrue(r["needs_review"])

    def test_latin_alias_requires_boundary(self):
        cfg = {"brand": {"name": "灵眸", "aliases": ["AIGC"], "site": "https://x.example.com"},
               "competitors": [], "questions": []}
        # "AIGC" 是 "AIGCLINK" 的子串：右侧紧跟拉丁字符 → 不算命中
        self.assertFalse(S.analyze_answer("AIGCLINK很好用", cfg)["brand_mentioned"])
        # 双侧都是边界 → 正常命中
        self.assertTrue(S.analyze_answer("AIGC 很好用", cfg)["brand_mentioned"])
        self.assertTrue(S.analyze_answer("推荐AIGC，挺好", cfg)["brand_mentioned"])


class TestDedup(unittest.TestCase):
    def test_same_day_rerun_keeps_last(self):
        first = make_row(mentioned=True)
        last = make_row(mentioned=False)  # 重跑结果：未提及
        rows = S.dedup_rows([first, last])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["analysis"]["brand_mentioned"])
        agg = S.aggregate(S.dedup_rows([first, last]), CFG)
        self.assertEqual(agg["deepseek"]["samples"], 1)
        self.assertEqual(agg["deepseek"]["mention_rate"], 0.0)

    def test_dedup_key_distinguishes_round_and_mode(self):
        rows = [make_row(rnd=1), make_row(rnd=2), make_row(mode="manual")]
        self.assertEqual(len(S.dedup_rows(rows)), 3)

    def test_separate_runs_are_immutable_cohorts(self):
        first = {**make_row(), "run_id": "run-a"}
        second = {**make_row(), "run_id": "run-b"}
        self.assertEqual(len(S.dedup_rows([first, second])), 2)


class TestRankingAndCitationSemantics(unittest.TestCase):
    def test_prose_first_mention_is_not_recommendation_rank(self):
        result = S.analyze_answer("先说明竞品X的背景。AIGCLINK定制家也提供类似能力。", CFG)
        self.assertEqual(result["first_mention_order"], 2)
        self.assertEqual(result["brand_rank"], 0)
        self.assertIsNone(result["rank_basis"])

    def test_numbered_list_sets_actual_rank(self):
        result = S.analyze_answer("1. 竞品X\n3. AIGCLINK定制家", CFG)
        self.assertEqual(result["brand_rank"], 3)
        self.assertEqual(result["rank_basis"], "explicit_list")

    def test_domain_observation_does_not_prove_brand_presence(self):
        result = S.analyze_answer(
            "AIGCLINK定制家可以考虑。",
            CFG,
            [{"url": "https://wikipedia.org/wiki/Unrelated", "title": "Unrelated topic"}],
        )
        self.assertIn("wikipedia.org", result["cited_domains"])
        self.assertNotIn("wikipedia.org", result["brand_cited_domains"])

    def test_citation_title_can_prove_brand_specific_source(self):
        result = S.analyze_answer(
            "AIGCLINK定制家可以考虑。",
            CFG,
            [{"url": "https://wikipedia.org/wiki/AIGCLINK", "title": "AIGCLINK定制家"}],
        )
        self.assertIn("wikipedia.org", result["brand_cited_domains"])

    def test_citation_hosts_normalize_ports_and_www(self):
        result = S.analyze_answer(
            "AIGCLINK定制家可以考虑。",
            CFG,
            [{"url": "https://WWW.AIGCLINK.EXAMPLE.COM:443/docs", "title": "AIGCLINK定制家"}],
        )
        self.assertIn("aigclink.example.com", result["cited_domains"])
        self.assertTrue(result["own_domain_cited"])


class TestProbeNoFallback(unittest.TestCase):
    def test_probe_only_platform_mention_rate_none(self):
        rows = [make_row(qid="Q1", probe=True, question="AIGCLINK定制家是什么"),
                make_row(qid="Q2", probe=True, question="AIGCLINK定制家官网是哪个")]
        agg = S.aggregate(rows, CFG)
        m = agg["deepseek"]
        self.assertIsNone(m["mention_rate"])
        self.assertEqual(m["samples"], 0)
        self.assertEqual(m["probe"]["samples"], 2)
        self.assertEqual(m["probe"]["recognized_rate"], 1.0)

    def test_mixed_platform_still_splits(self):
        rows = [make_row(qid="Q1", probe=True, question="AIGCLINK定制家是什么"),
                make_row(qid="Q2", mentioned=True),
                make_row(qid="Q3", mentioned=False)]
        agg = S.aggregate(rows, CFG)
        m = agg["deepseek"]
        self.assertEqual(m["samples"], 2)
        self.assertEqual(m["mention_rate"], 0.5)
        self.assertEqual(m["probe"]["samples"], 1)

    def test_short_latin_brand_requires_question_token_boundary(self):
        cfg = {"brand": {"name": "AI", "aliases": [], "site": "https://ai.example"},
               "competitors": [], "questions": []}
        self.assertFalse(S.brand_in_question("Which paid tool is best?", cfg))
        self.assertTrue(S.brand_in_question("Is AI useful?", cfg))


class TestProviderPacing(unittest.TestCase):
    def test_provider_delay_is_bounded_and_configurable(self):
        with mock.patch.dict(os.environ, {"GEO_PROVIDER_DELAY_SECONDS": "2.5"}):
            self.assertEqual(S._provider_delay("deepseek"), 2.5)
        with mock.patch.dict(os.environ, {"GEO_PROVIDER_DELAY_SECONDS": "-3"}):
            self.assertEqual(S._provider_delay("deepseek"), 0.0)
        with mock.patch.dict(os.environ, {"GEO_PROVIDER_DELAY_SECONDS": "not-a-number"}):
            self.assertEqual(S._provider_delay("deepseek"), S.DEFAULT_PROVIDER_DELAY)


class TestProviderObservability(unittest.TestCase):
    def test_summarizes_usage_retries_models_and_search_evidence(self):
        rows = [
            {"platform": "openai", "ok": True, "retry_count": 1,
             "raw_model": "model-b", "usage": {"total_tokens": 9},
             "search_evidence": "not_searched"},
            {"platform": "openai", "ok": False, "retry_count": 2,
             "raw_model": "model-a", "usage": {}, "search_evidence": "request_failed"},
        ]
        summary = S._provider_observability(rows)
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["successful"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["retries"], 3)
        self.assertEqual(summary["usage"]["total_tokens"], 9)
        self.assertEqual(summary["platforms"]["openai"]["models"], ["model-a", "model-b"])
        self.assertEqual(summary["platforms"]["openai"]["search_evidence"]["request_failed"], 1)


class TestMarketOf(unittest.TestCase):
    def test_unknown_platform_code(self):
        self.assertEqual(S.market_of("deepssek"), "unknown")

    def test_known_codes_unchanged(self):
        self.assertEqual(S.market_of("deepseek"), "global")
        self.assertEqual(S.market_of("perplexity"), "global")
        self.assertEqual(S.market_of("chatgpt"), "global")


class _Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


OK_PAYLOAD = {
    "choices": [{"message": {"content": "你好"}, "finish_reason": "stop"}],
    "model": "deepseek-v4-flash",
    "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
}


class TestAskRetry(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"})
        self._env.start()
        self._sleep = mock.patch.object(S.time, "sleep")
        self.sleep = self._sleep.start()

    def tearDown(self):
        self._env.stop()
        self._sleep.stop()

    def _ask(self, side_effect):
        with mock.patch.object(S.requests, "post", side_effect=side_effect) as post:
            res = S.ask("deepseek", "测试问题")
        return res, post

    def test_retry_on_429_then_success(self):
        res, post = self._ask([_Resp(429, text="rate limited"),
                               _Resp(500, text="server error"),
                               _Resp(200, OK_PAYLOAD)])
        self.assertTrue(res["ok"])
        self.assertFalse(res["searched"])
        self.assertEqual(res["retry_count"], 2)
        self.assertEqual(res["usage"]["total_tokens"], 9)
        self.assertEqual(res["stop_reason"], "stop")
        self.assertEqual(post.call_count, 3)

    def test_retry_after_header_controls_wait(self):
        res, _ = self._ask([
            _Resp(429, text="rate limited", headers={"Retry-After": "7"}),
            _Resp(200, OK_PAYLOAD, headers={"x-request-id": "req-123"}),
        ])
        self.assertTrue(res["ok"])
        self.assertEqual(res["request_id"], "req-123")
        self.sleep.assert_called_once_with(7.0)

    def test_retry_exhausted_returns_error(self):
        res, post = self._ask([_Resp(500, text="err")] * 5)
        self.assertFalse(res["ok"])
        self.assertEqual(post.call_count, 3)  # 1 + 2 次重试

    def test_timeout_retried(self):
        res, post = self._ask([S.requests.exceptions.Timeout("t"),
                               _Resp(200, OK_PAYLOAD)])
        self.assertTrue(res["ok"])
        self.assertEqual(post.call_count, 2)

    def test_timeout_exhausted(self):
        res, post = self._ask([S.requests.exceptions.Timeout("t")] * 5)
        self.assertFalse(res["ok"])
        self.assertEqual(post.call_count, 3)

    def test_no_retry_on_400(self):
        res, post = self._ask([_Resp(400, text="bad request")] * 5)
        self.assertFalse(res["ok"])
        self.assertEqual(post.call_count, 1)

    def test_empty_success_response_is_not_counted_as_a_sample(self):
        res, post = self._ask([_Resp(200, {"choices": [{"message": {"content": "  "}}]})])
        self.assertFalse(res["ok"])
        self.assertIn("empty answer", res["error"])
        self.assertEqual(post.call_count, 1)

    def test_anthropic_success_declares_search_mode_when_tool_is_on(self):
        payload = {"model": "claude-test", "content": [{"type": "server_tool_use"}, {"type": "text", "text": "OK"}]}
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "post", return_value=_Resp(200, payload)) as post:
            result = S.ask("claude", "Question?")
        self.assertTrue(result["ok"])
        self.assertTrue(result["searched"])
        tools = post.call_args.kwargs["json"]["tools"]
        self.assertEqual(tools[0]["name"], "web_search")

    def test_anthropic_can_still_run_parametric_when_search_disabled(self):
        payload = {"model": "claude-test", "content": [{"type": "text", "text": "OK"}]}
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "post", return_value=_Resp(200, payload)) as post:
            result = S.ask("claude", "Question?", search=False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["searched"])
        self.assertNotIn("tools", post.call_args.kwargs["json"])


class TestProviderHeaders(unittest.TestCase):
    """供应商级请求头按协议注入，未配置的 provider 逐字节不变。"""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"CITEAURA_CUSTOM_TEST_API_KEY": "custom-key"})
        self._env.start()
        self._sleep = mock.patch.object(S.time, "sleep")
        self._sleep.start()
        self.provider = {
            "name": "Custom Gateway",
            "market": "both",
            "base": "https://gateway.example.com/v1",
            "model": "vendor/model",
            "model_env": None,
            "key_env": "CITEAURA_CUSTOM_TEST_API_KEY",
            "note": "Custom provider",
            "headers": {"User-Agent": "CiteAura/1.0", "x-opencode-session": "citeaura"},
        }
        self._registry = mock.patch.dict(S.PROVIDERS, {"custom_test": self.provider})
        self._registry.start()

    def tearDown(self):
        self._registry.stop()
        self._env.stop()
        self._sleep.stop()

    def test_chat_headers_are_merged_without_dropping_auth(self):
        with mock.patch.object(S.requests, "post", return_value=_Resp(200, OK_PAYLOAD)) as post:
            result = S.ask("custom_test", "Question?")

        self.assertTrue(result["ok"])
        self.assertEqual(post.call_args.kwargs["headers"], {
            "Authorization": "Bearer custom-key",
            "Content-Type": "application/json",
            "User-Agent": "CiteAura/1.0",
            "x-opencode-session": "citeaura",
        })

    def test_headers_are_stable_across_retries(self):
        with mock.patch.object(S.requests, "post", side_effect=[
            _Resp(429, text="rate limited"),
            _Resp(200, OK_PAYLOAD),
        ]) as post:
            result = S.ask("custom_test", "Question?")

        self.assertTrue(result["ok"])
        self.assertEqual(post.call_count, 2)
        first, second = (call.kwargs["headers"] for call in post.call_args_list)
        self.assertEqual(first, second)

    def test_anthropic_protocol_keeps_x_api_key_and_adds_provider_headers(self):
        payload = {"model": "vendor/model", "content": [{"type": "text", "text": "OK"}]}
        self.provider["protocol"] = "anthropic"
        with mock.patch.object(S.requests, "post", return_value=_Resp(200, payload)) as post:
            result = S.ask("custom_test", "Question?")

        self.assertTrue(result["ok"])
        self.assertEqual(post.call_args.args[0], "https://gateway.example.com/v1/messages")
        self.assertEqual(post.call_args.kwargs["headers"], {
            "x-api-key": "custom-key",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "User-Agent": "CiteAura/1.0",
            "x-opencode-session": "citeaura",
        })

    def test_registry_switch_flag_routes_search_to_responses_with_headers(self):
        payload = {"output": [{"type": "message",
                               "content": [{"type": "output_text", "text": "OK"}]}]}
        self.provider["protocol"] = "openai"
        self.provider["search"] = True
        with mock.patch.object(S.requests, "post", return_value=_Resp(200, payload)) as post:
            result = S.ask("custom_test", "Question?")

        self.assertTrue(result["ok"])
        self.assertEqual(post.call_args.args[0], "https://gateway.example.com/v1/responses")
        self.assertEqual(post.call_args.kwargs["headers"]["x-opencode-session"], "citeaura")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer custom-key")

    def test_search_flag_is_off_by_default_and_skips_the_responses_path(self):
        with mock.patch.object(S.requests, "post", return_value=_Resp(200, OK_PAYLOAD)) as post:
            result = S.ask("custom_test", "Question?")

        self.assertTrue(result["ok"])
        self.assertFalse(result["searched"])
        self.assertEqual(post.call_args.args[0], "https://gateway.example.com/v1/chat/completions")

    def test_official_providers_without_headers_key_are_unchanged(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "post", return_value=_Resp(200, OK_PAYLOAD)) as post:
            S.ask("deepseek", "Question?")

        self.assertEqual(post.call_args.kwargs["headers"], {
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        })


class TestAskWebSearch(unittest.TestCase):
    def test_openai_uses_responses_web_search(self):
        payload = {
            "output": [{
                "type": "web_search_call",
                "action": {"type": "search", "query": "best tool"},
            }, {
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "Acme is cited.",
                    "annotations": [{"url": "https://acme.example", "title": "Acme"}],
                }],
            }],
        }
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "post", return_value=_Resp(200, payload)) as post:
            result = S.ask("openai", "Best tool?")
        self.assertTrue(result["ok"])
        self.assertTrue(result["searched"])
        self.assertEqual(result["citations"][0]["url"], "https://acme.example")
        self.assertTrue(post.call_args.args[0].endswith("/responses"))
        self.assertEqual(post.call_args.kwargs["json"]["tools"], [{"type": "web_search"}])

    def test_openai_falls_back_to_chat_when_responses_missing(self):
        chat = {"choices": [{"message": {"content": "Memory only."}}]}
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "post", side_effect=[
                 _Resp(404, text="no responses"),
                 _Resp(200, chat),
             ]):
            result = S.ask("openai", "Best tool?")
        self.assertTrue(result["ok"])
        self.assertFalse(result["searched"])
        self.assertEqual(result["answer"], "Memory only.")

    def test_gemini_uses_google_search_grounding(self):
        payload = {
            "candidates": [{
                "content": {"parts": [{"text": "Grounded answer."}]},
                "groundingMetadata": {
                    "groundingChunks": [{"web": {"uri": "https://docs.example", "title": "Docs"}}],
                },
            }],
        }
        session = mock.Mock()
        session.post.return_value = _Resp(200, payload)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "Session", return_value=session):
            result = S.ask("gemini", "Best tool?")
        self.assertTrue(result["ok"])
        self.assertTrue(result["searched"])
        self.assertEqual(result["citations"][0]["url"], "https://docs.example")
        self.assertFalse(session.trust_env)
        self.assertIn("generateContent", session.post.call_args.args[0])
        self.assertIn("google_search", session.post.call_args.kwargs["json"]["tools"][0])
        self.assertNotIn("key", session.post.call_args.kwargs)

    def test_grok_falls_back_to_live_search_parameters(self):
        chat = {
            "choices": [{"message": {"content": "Live search answer."}}],
            "citations": ["https://news.example"],
        }
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "test-key"}), \
             mock.patch.object(S.requests, "post", side_effect=[
                 _Resp(404, text="no responses"),
                 _Resp(200, chat),
             ]) as post:
            result = S.ask("grok", "Best tool?")
        self.assertTrue(result["ok"])
        self.assertTrue(result["searched"])
        self.assertEqual(result["citations"][0]["url"], "https://news.example")
        self.assertEqual(post.call_args.kwargs["json"]["search_parameters"]["mode"], "on")

    def test_registry_marks_global_apis_as_search_capable(self):
        for code in ("openai", "claude", "gemini", "grok", "perplexity"):
            self.assertTrue(S.PROVIDERS[code]["search"], code)
        self.assertFalse(S.PROVIDERS["deepseek"]["search"])


class TestProviderBaseResolution(unittest.TestCase):
    """base URL 在调用时解析：注册表留静态默认值，覆盖走 base_env。"""

    def test_openai_registry_keeps_static_default_and_env_hook(self):
        provider = S.PROVIDERS["openai"]
        self.assertEqual(provider["base"], "https://api.openai.com/v1")
        self.assertEqual(provider["base_env"], "OPENAI_BASE_URL")

    def test_base_env_override_resolves_at_call_time(self):
        provider = S.PROVIDERS["openai"]
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": "https://gateway.example/v1"}):
            self.assertEqual(S._p_base(provider), "https://gateway.example/v1")
        # 清掉覆盖后回落到注册表里的静态默认值
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": ""}):
            self.assertEqual(S._p_base(provider), "https://api.openai.com/v1")


class TestResponsesRetry(unittest.TestCase):
    def test_responses_path_retries_rate_limits_before_falling_back(self):
        chat = {"choices": [{"message": {"content": "Memory only."}}]}
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key",
                                          "OPENAI_BASE_URL": ""}), \
             mock.patch.object(S.time, "sleep") as sleep, \
             mock.patch.object(S.requests, "post", side_effect=[
                 _Resp(503, text="busy"),
                 _Resp(429, text="slow down"),
                 _Resp(404, text="no responses"),
                 _Resp(200, chat),
             ]) as post:
            result = S.ask("openai", "Best tool?")
        self.assertTrue(result["ok"])
        self.assertFalse(result["searched"])
        self.assertEqual(result["answer"], "Memory only.")
        self.assertEqual(post.call_count, 4)
        self.assertEqual(sleep.call_count, 2)  # 503 与 429 各退避一次，404 直接回退 chat
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/chat/completions")


class TestRunValidation(unittest.TestCase):
    def test_invalid_limits_fail_before_loading_project(self):
        with self.assertRaisesRegex(ValueError, "repeat"):
            S.run("missing", repeat=0)
        with self.assertRaisesRegex(ValueError, "limit"):
            S.run("missing", limit=0)

    def test_unknown_provider_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            pdir = G.project_dir("demo")
            pdir.mkdir()
            (pdir / "geo.json").write_text(json.dumps({
                "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
                "market": "both", "questions": [{"id": "q001", "market": "both", "text": "Best tool?"}],
            }), "utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown API platform"):
                S.run("demo", platforms=["typo"])

    def test_deepseek_uses_existing_questions_when_its_cohort_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            pdir = G.project_dir("demo")
            pdir.mkdir()
            (pdir / "geo.json").write_text(json.dumps({
                "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
                "market": "both", "platforms": ["deepseek", "glm"],
                "questions": [{"id": "q001", "market": "cn", "text": "有什么好用的工具？"}],
            }), "utf-8")
            response = {"ok": True, "answer": "可以看看 Acme。", "citations": [], "searched": False}
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), \
                 mock.patch.object(S, "ask", return_value=response) as ask:
                metrics = S.run("demo", platforms=["deepseek"])
            row = G.read_jsonl(next((pdir / "samples").glob("*.jsonl")))[0]
        self.assertEqual(ask.call_count, G.DEFAULT_SAMPLE_REPEAT)
        self.assertEqual(row["market"], "cn")
        self.assertEqual(row["question_id"], "q001")
        self.assertEqual(metrics["successful_sample_count"], G.DEFAULT_SAMPLE_REPEAT)

    def test_deepseek_keeps_global_cohort_when_those_questions_exist(self):
        cfg = {
            "market": "both",
            "questions": [
                {"id": "q001", "market": "cn", "text": "国内怎么选？"},
                {"id": "q101", "market": "global", "text": "Which tool is best?"},
            ],
        }
        self.assertEqual([q["id"] for q in S.questions_for(cfg, "deepseek")], ["q101"])
        self.assertEqual([q["id"] for q in S.questions_for(cfg, "glm")], ["q001"])

    def test_both_market_provider_samples_project_questions(self):
        """自定义供应商的 both 表示覆盖两个地区，不该因为没有 both 问题被跳过。"""
        cfg = {
            "market": "both",
            "questions": [
                {"id": "q001", "market": "cn", "text": "有什么好用的工具？"},
                {"id": "q101", "market": "global", "text": "Which tool is best?"},
            ],
        }
        provider = {
            "name": "Gateway", "market": "both", "base": "https://gateway.example.com/v1",
            "model": "vendor/model", "model_env": None,
            "key_env": "CITEAURA_CUSTOM_TEST_API_KEY", "note": "Custom provider",
        }
        with mock.patch.dict(S.PROVIDERS, {"custom_test_both": provider}):
            self.assertEqual(
                [q["id"] for q in S.questions_for(cfg, "custom_test_both")],
                ["q001", "q101"],
            )

    def test_billing_failure_stops_remaining_requests(self):
        """402 是确定性失败，继续跑满整轮只会制造上百条同样的错误。"""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            pdir = G.project_dir("demo")
            pdir.mkdir()
            (pdir / "geo.json").write_text(json.dumps({
                "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
                "market": "global", "platforms": ["deepseek"],
                "questions": [{"id": "q001", "market": "global", "text": "Best tool?"}],
            }), "utf-8")
            failure = {"ok": False, "error": 'HTTP 402: {"error":{"message":"Insufficient Balance"}}'}
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), \
                 mock.patch.object(S, "ask", return_value=failure) as ask:
                metrics = S.run("demo", repeat=5)
            rows = G.read_jsonl(next((pdir / "samples").glob("*.jsonl")))
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(metrics["sample_count"], 1)
        self.assertEqual(metrics["successful_sample_count"], 0)

    def test_no_market_matching_questions_does_not_create_empty_run(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            pdir = G.project_dir("demo")
            pdir.mkdir()
            (pdir / "geo.json").write_text(json.dumps({
                "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
                "market": "global", "questions": [
                    {"id": "q001", "market": "global", "text": "Best tool?"},
                ],
            }), "utf-8")
            with mock.patch.dict(os.environ, {"ZHIPUAI_API_KEY": "test"}):
                self.assertEqual(S.run("demo", platforms=["glm"]), {})
            self.assertFalse((pdir / "samples").exists())

    def test_run_persists_provider_and_search_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            pdir = G.project_dir("demo")
            pdir.mkdir()
            (pdir / "geo.json").write_text(json.dumps({
                "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
                "market": "global", "platforms": ["perplexity"],
                "questions": [{"id": "q001", "market": "global", "text": "Best tool?"}],
            }), "utf-8")
            response = {
                "ok": True, "answer": "Acme is useful.", "citations": [], "searched": True,
                "raw_model": "sonar-exact", "usage": {"total_tokens": 11},
                "request_id": "req-1", "retry_count": 1, "stop_reason": "stop",
            }
            with mock.patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test"}), \
                 mock.patch.object(S, "ask", return_value=response), \
                 mock.patch.object(S.time, "sleep"):
                metrics = S.run("demo")
            row = G.read_jsonl(next((pdir / "samples").glob("*.jsonl")))[0]
        self.assertEqual(row["raw_model"], "sonar-exact")
        self.assertEqual(row["usage"]["total_tokens"], 11)
        self.assertEqual(row["request_id"], "req-1")
        self.assertEqual(row["retry_count"], 1)
        self.assertEqual(row["search_evidence"], "provider_search_without_citations")
        self.assertEqual(
            metrics["provider_observability"]["usage"]["total_tokens"],
            11 * G.DEFAULT_SAMPLE_REPEAT,
        )
        self.assertEqual(metrics["provider_observability"]["retries"], G.DEFAULT_SAMPLE_REPEAT)


class TestSamplingConcurrency(unittest.TestCase):
    def test_providers_overlap_but_each_provider_stays_serial(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            pdir = G.project_dir("soak")
            pdir.mkdir()
            questions = [{"id": f"q{i:03d}", "market": "both", "text": f"Question {i}?"}
                         for i in range(1, 11)]
            (pdir / "geo.json").write_text(json.dumps({
                "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
                "market": "both", "platforms": ["deepseek", "openai"], "questions": questions,
            }), "utf-8")
            lock = threading.Lock()
            barrier = threading.Barrier(2)
            active = {"deepseek": 0, "openai": 0}
            calls = {"deepseek": 0, "openai": 0}
            peak_total = 0
            peak_provider = {"deepseek": 0, "openai": 0}

            def ask(platform, _question):
                nonlocal peak_total
                with lock:
                    calls[platform] += 1
                    first = calls[platform] == 1
                    active[platform] += 1
                    peak_provider[platform] = max(peak_provider[platform], active[platform])
                    peak_total = max(peak_total, sum(active.values()))
                if first:
                    barrier.wait(timeout=2)
                time.sleep(0.001)
                with lock:
                    active[platform] -= 1
                return {"ok": True, "answer": "No brand mentioned.", "citations": [], "searched": False}

            env = {"DEEPSEEK_API_KEY": "test", "OPENAI_API_KEY": "test"}
            with mock.patch.dict(os.environ, env), mock.patch.object(S, "ask", side_effect=ask), \
                 mock.patch.object(S.time, "sleep"):
                result = S.run("soak", repeat=2)
        self.assertEqual(result["sample_count"], 40)
        self.assertEqual(calls, {"deepseek": 20, "openai": 20})
        self.assertEqual(peak_provider, {"deepseek": 1, "openai": 1})
        self.assertGreaterEqual(peak_total, 2)


if __name__ == "__main__":
    unittest.main()
