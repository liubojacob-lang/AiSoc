"""Deterministic fake provider for tests and offline dev.

NOT a production model. Two honest uses:
1. CI/unit/integration tests: scripted responses (``provider.script(...)``)
   give byte-identical, fast agent-loop coverage.
2. Local dev without API keys: a keyword-heuristic fallback that exercises
   the full pipeline. Results are marked ``degraded`` downstream by config
   (routing normally points embed/chat at real providers in any real deploy).

embed() is a deterministic lexical hashing embedder: shared tokens raise
cosine similarity, which is enough to test retrieval wiring end-to-end.
"""

from __future__ import annotations

import hashlib  # noqa: S324 - md5 here is a lexical hash for fake embeddings, not security
import json
import math
import re

from app.modules.ai.providers.base import LLMProvider

DIM = 1024


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        self._scripts: dict[str, list[str]] = {}

    def script(self, model: str, *responses: str) -> None:
        """Queue canned responses (FIFO) for a model; the last one repeats."""
        self._scripts[model] = list(responses)

    # ---------- chat ----------

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        json_mode: bool,
    ) -> tuple[str, int, int]:
        queue = self._scripts.get(model)
        if queue:
            content = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            prompt = "\n".join(m["content"] for m in messages)
            if '"direct_answer"' in prompt:
                # CopilotAction schema detected → copilot-style heuristic
                content = self._heuristic_copilot_json(prompt)
            else:
                content = self._heuristic_verdict_json(messages)
        prompt_all = "\n".join(m["content"] for m in messages)
        return content, self._tokens(prompt_all), self._tokens(content)

    def _heuristic_copilot_json(self, prompt: str) -> str:
        """CopilotAction heuristic: route data questions to search_alerts."""
        import json as _json

        # 回答轮：观察结果已在上下文中 → 产出自然语言摘要（而非再返回 JSON）
        obs_m = re.search(r"TOOL (\w+) RESULT: (\{.*\})", prompt, re.DOTALL)
        if obs_m:
            try:
                payload = _json.loads(obs_m.group(2))
            except _json.JSONDecodeError:
                payload = {}
            if obs_m.group(1) == "search_alerts" and "alerts" in payload:
                n = payload.get("matched", 0)
                lines = [
                    f"- {a['title']}（{a['severity']}/{a['status']}，{a['occurred_at']}）"
                    for a in payload.get("alerts", [])[:5]
                ]
                body = "\n".join(lines) if lines else "（无匹配告警）"
                return f"当前查询到 {n} 条告警，最近的有：\n{body}\n（内置确定性模型的摘要；接入真实 LLM 后为更自然的分析。）"
            return "（内置确定性模型）已查询到相关数据。"

        question_m = re.search(r"USER QUESTION:\s*(.+)", prompt)
        question = question_m.group(1).strip() if question_m else ""
        data_kw = ("告警", "警报", "alert", "高危", "事件", "incident", "统计", "多少", "how many")
        needs_data = any(k in question.lower() for k in data_kw)
        if needs_data:
            return _json.dumps(
                {"thought": "fake heuristic: data question → search alerts", "tool": "search_alerts", "args": {}},
                ensure_ascii=False,
            )
        return _json.dumps(
            {"thought": "fake heuristic: direct", "tool": None, "args": {},
             "direct_answer": "（内置确定性模型）你好！我是 AISOC 助手。接入真实 LLM Key 后，我可以基于工具数据回答告警、事件、统计与知识库问题。"},
            ensure_ascii=False,
        )

    def _heuristic_verdict_json(self, messages: list[dict[str, str]]) -> str:
        """Keyword-heuristic single-step finalize. Mirrors the rule fallback."""
        text = "\n".join(m["content"] for m in messages)
        alert_type_m = re.search(r'"alert_type"\s*:\s*"([^"]+)"', text)
        alert_type = alert_type_m.group(1) if alert_type_m else "unknown"
        reputation_m = re.search(r'"reputation"\s*:\s*(\d+)', text)
        reputation = int(reputation_m.group(1)) if reputation_m else 50
        critical_m = re.search(r'"criticality"\s*:\s*"(\w+)"', text)
        criticality = critical_m.group(1) if critical_m else "medium"

        danger = {"brute_force", "malware", "sql_injection", "web_attack", "lateral_movement"}
        is_danger = alert_type in danger or reputation >= 70 or criticality == "high"
        verdict = {
            "thought": "fake provider heuristic: classify from alert fields",
            "final": {
                "classification": "true_positive" if is_danger else "false_positive",
                "severity": "high" if is_danger else "low",
                "confidence": 70 if is_danger else 60,
                "reasoning": (
                    f"Fake heuristic: alert_type={alert_type}, intel reputation={reputation}, "
                    f"asset criticality={criticality}. Scripted deterministic output for dev/test."
                ),
                "evidence": [
                    {"source": "alert", "detail": f"alert_type={alert_type}"},
                    {"source": "query_threat_intel", "detail": f"reputation={reputation}"},
                ],
                "recommended_actions": [
                    {
                        "action": "monitor" if not is_danger else "block_ip",
                        "target": None,
                        "reason": "fake heuristic recommendation",
                    }
                ],
            },
        }
        return json.dumps(verdict, ensure_ascii=False)

    @staticmethod
    def _tokens(text: str) -> int:
        return max(1, len(text) // 4)

    # ---------- embed ----------

    async def embed(self, texts: list[str], model: str, *, timeout_s: float) -> list[list[float]]:
        return [self._lexical_vector(t) for t in texts]

    @staticmethod
    def _lexical_vector(text: str) -> list[float]:
        vec = [0.0] * DIM
        for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()):
            h = int(hashlib.md5(token.encode()).hexdigest()[:12], 16)
            vec[h % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
