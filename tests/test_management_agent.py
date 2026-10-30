from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from aaoca_pipeline.io_utils import write_json
from aaoca_pipeline.management import write_management_package
from aaoca_pipeline.management_agent import (
    PatientTools, create_deepseek_model, parse_final_json, prepare_review, route_case,
    run_review, validate_assessment, validate_review_package, validate_review_run,
)
from test_management_llm import _make_sources, _section


def _assessment(section_id: str, quote: str) -> dict:
    return {"observed_management": "unknown", "actual_aaoca_surgery": "unknown",
            "overall_treatment_status": "surgery", "aaoca_handling": "unclear",
            "rationale": "已完成VSD修补，但AAOCA是否处理未明确。",
            "citations": [{"section_id": section_id, "quote": quote}], "uncertainties": ["AAOCA操作目标不明"]}


class ToolThenFinalModel:
    model_name = "synthetic-only"

    def __init__(self, sid: str, *, fail: bool = False):
        self.sid, self.fail, self.calls, self.choices = sid, fail, 0, []

    def bind_tools(self, tools, **kwargs):
        self.choices.append(kwargs["tool_choice"])
        return self

    def invoke(self, messages, **kwargs):
        from langchain_core.messages import AIMessage

        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic-sensitive-error-must-not-be-saved")
        usage = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{"name": "get_section", "args": {"section_id": self.sid}, "id": "t1"}], usage_metadata=usage)
        return AIMessage(content="判断仍不明确。\n```json\n" + json.dumps(_assessment(self.sid, "完成VSD修补，冠状动脉起源异常，术中探查冠脉。"), ensure_ascii=False) + "\n```", usage_metadata=usage)


@unittest.skipUnless(importlib.util.find_spec("langchain_deepseek") and importlib.util.find_spec("regex"), "Install the llm extra for agent tests")
class ManagementAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run, self.review, self.management = _make_sources(self.root)
        self.sid = "doc_unknown_s0001"
        self.source = self.run / "sections/doc_unknown.json"
        section = _section("p_unknown", self.sid,
                           "手术记录。完成VSD修补，冠状动脉起源异常，术中探查冠脉。具体处理目标未说明。",
                           day="2024-03-02", section_type="procedure", subtype="surgery_record")
        write_json(self.source, {"sections": [section]})
        write_management_package(self.run, self.review, self.management)

    def prepare(self):
        output = self.root / "requests"
        result = prepare_review(self.management, self.run, self.review, output, patient_ids=["p_unknown"])
        self.assertEqual(result["prepared_cases"], 1)
        self.assertFalse(result["model_invoked"])
        return output

    def test_selective_routing_keeps_missing_data_and_routine_rules_off_model(self):
        summary = {"observed_management": "unknown"}
        self.assertEqual(route_case(summary, [], [])['route'], "insufficient_documentation")
        summary = {"observed_management": "surgery", "review_required": "true", "review_reasons": '["ocr_derived_completion_or_date_evidence"]'}
        self.assertEqual(route_case(summary, [], [])['route'], "rules_sufficient")
        section = _section("p", "d_s1", "影像提示冠状动脉起源异常，建议定期随访。", day="2024-01-01", section_type="imaging")
        self.assertEqual(route_case({"observed_management": "unknown"}, [], [section])['route'], "insufficient_documentation")

    def test_free_text_consent_decision_and_later_typo_history_are_not_dropped(self):
        consent = _section("p", "c_s1", "其他需告知的事项：患儿右冠开口于左侧冠窦，因患儿目前较小，暂不处理，后期随访。",
                           day="", section_type="administrative", subtype="treatment_procedure_consent")
        route = route_case({"observed_management": "unknown"}, [], [consent])
        self.assertEqual(route['route'], "needs_llm")
        self.assertIn("coronary_decision_not_resolved_by_rules", route['reasons'])
        history = _section("p", "o_s1", "现病史: AOOCA术后2年。", day="2025-01-01", section_type="outpatient")
        route = route_case({"observed_management": "conservative"}, [], [history])
        self.assertIn("postoperative_history_conflicts_with_no_completion", route['reasons'])

    def test_preparation_binds_sources_and_blocks_overwrite_and_ineligible_cases(self):
        package = self.prepare()
        self.assertEqual(validate_review_package(package)["validation_status"], "passed")
        with self.assertRaises(ValueError):
            prepare_review(self.management, self.run, self.review, package)
        with self.assertRaises(ValueError):
            prepare_review(self.management, self.run, self.review, self.root / "invalid", patient_ids=["p_surgery"])
        with self.assertRaises(ValueError):
            prepare_review(self.management, self.run, self.review, self.management)
        with self.assertRaises(ValueError):
            prepare_review(self.management, self.run, self.review, self.root / "too_many", max_cases=4)

    def test_source_drift_blocks_client_before_any_paid_call(self):
        package = self.prepare()
        self.source.write_text(self.source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        fake = ToolThenFinalModel(self.sid)
        with self.assertRaises(ValueError):
            run_review(package, self.root / "results", model=fake)
        self.assertEqual(fake.calls, 0)

    def test_tool_loop_counts_calls_and_validates_replay_without_network(self):
        package = self.prepare()
        fake = ToolThenFinalModel(self.sid)
        output = self.root / "results"
        result = run_review(package, output, model=fake)
        self.assertEqual(result["validation_status"], "passed")
        self.assertEqual(result["attempted_api_calls"], 2)
        self.assertEqual(result["input_tokens"], 80)
        self.assertEqual(fake.choices, ["auto", "none"])
        self.assertEqual(validate_review_run(package, output)["validation_status"], "passed")
        self.assertTrue(json.loads((output / "responses.jsonl").read_text(encoding="utf-8"))["requires_human_review"])
        with self.assertRaises(ValueError):
            run_review(package, output, model=fake)
        self.assertEqual(fake.calls, 2)
        raw = (output / "responses.jsonl").read_text(encoding="utf-8")
        (output / "responses.jsonl").write_text(raw.replace("冠脉。", "冠脉！"), encoding="utf-8")
        self.assertEqual(validate_review_run(package, output)["validation_status"], "failed")

    def test_provider_failure_has_no_retry_or_sensitive_exception_text(self):
        package = self.prepare()
        fake = ToolThenFinalModel(self.sid, fail=True)
        output = self.root / "error"
        result = run_review(package, output, model=fake)
        self.assertEqual(result["attempted_api_calls"], 1)
        self.assertEqual(result["passed"], 0)
        self.assertEqual(fake.calls, 1)
        self.assertNotIn("synthetic-sensitive-error", (output / "responses.jsonl").read_text(encoding="utf-8"))

    def test_search_scope_pagination_and_exact_exposure_citations(self):
        own = _section("own", "d_s1", "AAOCA。" * 20, day="2024-01-01", section_type="progress")
        other = _section("other", "d_s2", "不能读取这个患者", day="2024-01-02", section_type="progress")
        tools = PatientTools("own", [own, other])
        self.assertIn("error", tools.get_section("d_s2"))
        self.assertIn("error", tools.search_sections("[", mode="regex"))
        self.assertIn("error", tools.search_sections("", mode="keyword"))
        page = tools.search_sections("AAOCA")
        self.assertEqual(page["total_matches"], 20)
        self.assertTrue(page["scanned_all_sections"])
        self.assertTrue(page["truncated"])
        self.assertEqual(page["next_offset"], 10)
        self.assertEqual(len(tools.search_sections("AAOCA", offset=10)["matches"]), 10)
        assessment = _assessment("d_s1", "AAOCA。")
        self.assertEqual(validate_assessment(assessment, tools)[0], [])
        assessment["citations"][0]["quote"] = "AAOCA改写"
        self.assertIn("citation_not_exact_or_not_seen", validate_assessment(assessment, tools)[0])
        self.assertIn("citation_not_exact_or_not_seen", validate_assessment(_assessment("d_s2", other["text"]), tools)[0])
        no_exposure = PatientTools("own", [own])
        self.assertIn("citation_not_exact_or_not_seen", validate_assessment(_assessment("d_s1", "AAOCA。"), no_exposure)[0])

    def test_long_section_and_regex_cost_are_bounded(self):
        section = _section("p", "long", "a" * 25000 + "!", day="", section_type="progress")
        tools = PatientTools("p", [section])
        result = tools.get_section("long")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["next_offset"], 10000)
        self.assertEqual(len(tools.get_section("long", 10000)["text"]), 10000)
        result = tools.search_sections("(a+)+$", mode="regex")
        self.assertFalse(result["scanned_all_sections"])
        self.assertIn("long", result["timed_out_sections"])

    def test_direct_surgery_fact_is_independent_of_management_pathway(self):
        section = _section("p", "s1", "明确截至本次记录未接受过AAOCA手术。", day="2025-01-01", section_type="progress")
        tools = PatientTools("p", [section])
        tools.get_section("s1")
        assessment = _assessment("s1", section["text"])
        assessment["actual_aaoca_surgery"] = "no"
        assessment["overall_treatment_status"] = "unknown"
        self.assertEqual(validate_assessment(assessment, tools)[0], [])

    def test_episode_nonintervention_does_not_validate_a_global_no(self):
        section = _section("p", "s1", "冠脉本次暂不处理，后期随访。", day="2025-01-01", section_type="progress")
        tools = PatientTools("p", [section])
        tools.get_section("s1")
        assessment = _assessment("s1", section["text"])
        assessment.update(observed_management="conservative", actual_aaoca_surgery="no")
        self.assertIn("actual_no_requires_direct_negative_surgical_history", validate_assessment(assessment, tools)[0])

    def test_absence_of_a_repair_description_is_not_explicit_nonintervention(self):
        section = _section("p", "s1", "探查冠脉开口，随后缝合关闭主动脉切口。", day="2025-01-01", section_type="procedure")
        tools = PatientTools("p", [section])
        tools.get_section("s1")
        assessment = _assessment("s1", section["text"])
        assessment["aaoca_handling"] = "explicitly_not_treated"
        self.assertIn("explicit_nonintervention_requires_direct_quote", validate_assessment(assessment, tools)[0])

    def test_whitespace_only_quotes_resolve_to_exact_unique_seen_source(self):
        text = "右冠状动脉异常起源于左冠窦\n未处理，后期随访。"
        section = _section("p", "s1", text, day="2025-01-01", section_type="progress")
        tools = PatientTools("p", [section])
        tools.get_section("s1")
        quote = "右冠状动脉异常起源于左冠窦未处理"
        errors, citations = validate_assessment(_assessment("s1", quote), tools)
        self.assertEqual(errors, [])
        self.assertEqual(citations[0]["match_method"], "whitespace_only")
        self.assertEqual(citations[0]["model_quote"], quote)
        self.assertIn("\n", citations[0]["quote"])
        self.assertEqual(text[citations[0]["char_start"]:citations[0]["char_end"]], citations[0]["quote"])
        bad = _assessment("s1", quote.replace("右", "左"))
        self.assertIn("citation_not_exact_or_not_seen", validate_assessment(bad, tools)[0])
        duplicate = _section("p", "s2", text + "\n" + text, day="2025-01-01", section_type="progress")
        ambiguous = PatientTools("p", [duplicate])
        ambiguous.get_section("s2")
        self.assertIn("citation_not_exact_or_not_seen", validate_assessment(_assessment("s2", quote), ambiguous)[0])

    def test_final_json_is_complete_but_may_follow_short_explanation(self):
        self.assertEqual(parse_final_json('解释。\n```json\n{"x": {"a": 1}}\n```'), {"x": {"a": 1}})
        for text in ['{"x": 1', '{"x": 1} 额外尾注', '没有JSON']:
            with self.assertRaises(ValueError):
                parse_final_json(text)

    def test_offline_deepseek_payload_has_no_response_format_or_retries(self):
        model = create_deepseek_model(api_key="synthetic-not-a-real-key")
        payload = model._get_request_payload([("user", "synthetic")])
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["extra_body"]["thinking"]["type"], "disabled")
        self.assertEqual(model.max_retries, 0)
        self.assertEqual(model.openai_api_base, "https://api.deepseek.com")

    def test_real_sdk_serializes_tools_and_thinking_without_network(self):
        import httpx
        from openai import OpenAI
        from aaoca_pipeline.management_agent import TOOL_SCHEMAS

        sent = []
        def respond(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion", "created": 1,
                "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {
                        "name": "get_section", "arguments": '{"section_id":"synthetic_s1"}'}}]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}})
        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            client = OpenAI(api_key="synthetic", base_url="https://api.deepseek.com", http_client=http, max_retries=0)
            model = create_deepseek_model(api_key="synthetic")
            model.client = client.chat.completions
            reply = model.bind_tools(TOOL_SCHEMAS, tool_choice="auto").invoke([("user", "synthetic only")])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["thinking"], {"type": "disabled"})
        self.assertNotIn("response_format", sent[0])
        self.assertEqual(sent[0]["tool_choice"], "auto")
        self.assertEqual(reply.tool_calls[0]["args"], {"section_id": "synthetic_s1"})
        self.assertEqual(reply.usage_metadata["input_tokens"], 10)


if __name__ == "__main__":
    unittest.main()
