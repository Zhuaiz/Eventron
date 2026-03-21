"""Prompt dynamic optimization — version management, A/B testing, and auto-tuning.

Each plugin's system prompt can be versioned and dynamically selected based on:
1. User feedback signals (+1/-1)
2. Reflection scores from past interactions
3. A/B testing between prompt variants

Storage: JSON files under ``data/prompt_versions/{plugin_name}/``.

The optimization cycle:
1. Record outcome for current prompt version
2. Periodically generate improved variants via LLM
3. A/B test new variants against baseline
4. Promote winning variant to default
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROMPT_ROOT = Path("data/prompt_versions")


@dataclass
class PromptVersion:
    """A versioned prompt with performance metrics."""
    version: str                # e.g. "v1", "v2-concise"
    plugin: str
    content: str                # the system prompt template
    created_at: float = 0.0
    total_uses: int = 0
    avg_score: float = 0.0
    positive_count: int = 0
    negative_count: int = 0
    is_baseline: bool = False   # current default
    is_candidate: bool = False  # A/B test candidate
    ab_test_ratio: float = 0.0  # % of traffic to route here
    scores: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_outcome(
        self, score: float, feedback: int | None = None
    ) -> None:
        """Record the outcome of using this prompt version."""
        self.total_uses += 1
        self.scores.append(score)
        # Keep last 100 scores for rolling average
        if len(self.scores) > 100:
            self.scores = self.scores[-100:]
        self.avg_score = sum(self.scores) / len(self.scores)

        if feedback == 1:
            self.positive_count += 1
        elif feedback == -1:
            self.negative_count += 1

    @property
    def success_rate(self) -> float:
        """Positive feedback rate."""
        total_fb = self.positive_count + self.negative_count
        if total_fb == 0:
            return 0.5  # neutral default
        return self.positive_count / total_fb

    @property
    def confidence(self) -> float:
        """Statistical confidence based on sample size."""
        if self.total_uses < 5:
            return 0.0
        if self.total_uses < 20:
            return 0.3
        if self.total_uses < 50:
            return 0.6
        return 0.9


@dataclass
class PluginPromptManager:
    """Manages prompt versions for a single plugin."""
    plugin: str
    versions: dict[str, PromptVersion] = field(default_factory=dict)
    current_baseline: str = "v1"
    optimization_history: list[dict] = field(default_factory=list)

    def get_active_prompt(self) -> PromptVersion | None:
        """Select which prompt version to use (with A/B routing)."""
        baseline = self.versions.get(self.current_baseline)
        if not baseline:
            return None

        # Check for A/B test candidates
        candidates = [
            v for v in self.versions.values()
            if v.is_candidate and v.ab_test_ratio > 0
        ]
        if candidates:
            roll = random.random()
            cumulative = 0.0
            for c in candidates:
                cumulative += c.ab_test_ratio
                if roll < cumulative:
                    return c

        return baseline

    def promote_candidate(self, version: str) -> None:
        """Promote a candidate to baseline (A/B test winner)."""
        if version not in self.versions:
            return
        old_baseline = self.current_baseline

        # Demote old baseline
        if old_baseline in self.versions:
            self.versions[old_baseline].is_baseline = False

        # Promote new
        self.versions[version].is_baseline = True
        self.versions[version].is_candidate = False
        self.versions[version].ab_test_ratio = 0.0
        self.current_baseline = version

        self.optimization_history.append({
            "action": "promote",
            "from": old_baseline,
            "to": version,
            "timestamp": time.time(),
            "reason": f"avg_score {self.versions[version].avg_score:.2f} "
                      f"> {self.versions.get(old_baseline, PromptVersion(version='?', plugin=self.plugin, content='')).avg_score:.2f}",
        })

    def add_variant(
        self,
        version: str,
        content: str,
        ab_ratio: float = 0.2,
    ) -> PromptVersion:
        """Add a new prompt variant for A/B testing."""
        pv = PromptVersion(
            version=version,
            plugin=self.plugin,
            content=content,
            created_at=time.time(),
            is_candidate=True,
            ab_test_ratio=ab_ratio,
        )
        self.versions[version] = pv
        return pv

    def evaluate_candidates(self) -> list[dict]:
        """Check if any A/B candidate should be promoted or dropped."""
        actions: list[dict] = []
        baseline = self.versions.get(self.current_baseline)
        if not baseline:
            return actions

        for v in list(self.versions.values()):
            if not v.is_candidate:
                continue
            if v.total_uses < 10:
                continue  # Not enough data

            # Promote if significantly better
            if (
                v.avg_score > baseline.avg_score + 0.1
                and v.confidence >= 0.3
            ):
                self.promote_candidate(v.version)
                actions.append({
                    "action": "promoted",
                    "version": v.version,
                    "score": v.avg_score,
                })
            # Drop if significantly worse after enough uses
            elif (
                v.total_uses >= 20
                and v.avg_score < baseline.avg_score - 0.1
            ):
                v.is_candidate = False
                v.ab_test_ratio = 0.0
                actions.append({
                    "action": "dropped",
                    "version": v.version,
                    "score": v.avg_score,
                })
        return actions


# ── Persistence ────────────────────────────────────────────────

def _plugin_prompt_path(plugin: str) -> Path:
    d = PROMPT_ROOT / plugin
    d.mkdir(parents=True, exist_ok=True)
    return d / "versions.json"


def load_prompt_manager(plugin: str) -> PluginPromptManager:
    """Load prompt version manager for a plugin."""
    p = _plugin_prompt_path(plugin)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            mgr = PluginPromptManager(plugin=plugin)
            mgr.current_baseline = data.get("current_baseline", "v1")
            mgr.optimization_history = data.get(
                "optimization_history", []
            )
            for vname, vdata in data.get("versions", {}).items():
                pv = PromptVersion(
                    version=vdata.get("version", vname),
                    plugin=plugin,
                    content=vdata.get("content", ""),
                    created_at=vdata.get("created_at", 0),
                    total_uses=vdata.get("total_uses", 0),
                    avg_score=vdata.get("avg_score", 0),
                    positive_count=vdata.get("positive_count", 0),
                    negative_count=vdata.get("negative_count", 0),
                    is_baseline=vdata.get("is_baseline", False),
                    is_candidate=vdata.get("is_candidate", False),
                    ab_test_ratio=vdata.get("ab_test_ratio", 0),
                    scores=vdata.get("scores", []),
                    metadata=vdata.get("metadata", {}),
                )
                mgr.versions[vname] = pv
            return mgr
        except Exception:
            pass
    return PluginPromptManager(plugin=plugin)


def save_prompt_manager(mgr: PluginPromptManager) -> None:
    """Persist prompt version manager."""
    p = _plugin_prompt_path(mgr.plugin)
    data = {
        "plugin": mgr.plugin,
        "current_baseline": mgr.current_baseline,
        "optimization_history": mgr.optimization_history[-50:],
        "versions": {
            k: asdict(v) for k, v in mgr.versions.items()
        },
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── High-level API ─────────────────────────────────────────────

def get_plugin_prompt(
    plugin: str, default_prompt: str
) -> tuple[str, str]:
    """Get the active prompt for a plugin.

    Returns (prompt_content, version_name). If no custom versions exist,
    registers the default as v1 baseline and returns it.
    """
    mgr = load_prompt_manager(plugin)
    if not mgr.versions:
        # Bootstrap: register the default prompt as v1
        pv = PromptVersion(
            version="v1",
            plugin=plugin,
            content=default_prompt,
            created_at=time.time(),
            is_baseline=True,
        )
        mgr.versions["v1"] = pv
        mgr.current_baseline = "v1"
        save_prompt_manager(mgr)
        return default_prompt, "v1"

    active = mgr.get_active_prompt()
    if active:
        return active.content, active.version
    return default_prompt, "v1"


def record_prompt_outcome(
    plugin: str,
    version: str,
    score: float,
    feedback: int | None = None,
) -> None:
    """Record the outcome of a prompt version usage."""
    mgr = load_prompt_manager(plugin)
    pv = mgr.versions.get(version)
    if pv:
        pv.record_outcome(score, feedback)
        # Check for promotions/demotions
        mgr.evaluate_candidates()
        save_prompt_manager(mgr)


# ── LLM-based prompt generation ───────────────────────────────

_PROMPT_OPTIMIZER_SYSTEM = """你是 Prompt 优化专家。根据用户反馈和交互记录，改进 Agent 的系统提示词。

## 当前 Prompt
{current_prompt}

## 交互记录（最近的失败或低分案例）
{failure_examples}

## 成功案例
{success_examples}

## 用户反馈总结
正面反馈: {positive_count}次
负面反馈: {negative_count}次
平均质量分: {avg_score}

## 你的任务
分析失败原因，生成一个改进版 Prompt。改进要点：
1. 让 Agent 更倾向于直接调用工具而非只回复文字
2. 修复导致低分的具体行为模式
3. 保持原有核心功能不变
4. 添加从成功案例中学到的最佳实践

输出格式（纯JSON）：
{{
  "improved_prompt": "改进后的完整 prompt 文本",
  "changes_summary": "改动摘要",
  "expected_improvement": "预期改进效果"
}}"""


async def generate_improved_prompt(
    plugin: str,
    current_prompt: str,
    interactions: list[dict],
    llm: Any,
) -> dict[str, str] | None:
    """Use LLM to generate an improved prompt variant.

    Args:
        plugin: Plugin name.
        current_prompt: Current system prompt text.
        interactions: Recent interaction records.
        llm: LangChain LLM instance.

    Returns:
        Dict with 'improved_prompt', 'changes_summary', or None on failure.
    """
    from agents.llm_utils import extract_json

    failures = [
        r for r in interactions
        if r.get("reflection_score", 1) < 0.6
        or r.get("user_feedback") == -1
    ]
    successes = [
        r for r in interactions
        if r.get("reflection_score", 0) >= 0.8
        and r.get("user_feedback") != -1
    ]

    fail_text = "\n".join(
        f"- 用户: {r.get('user_msg', '?')[:100]} → "
        f"问题: {r.get('reflection_issues', [])}"
        for r in failures[:5]
    ) or "暂无失败案例"

    success_text = "\n".join(
        f"- 用户: {r.get('user_msg', '?')[:100]} → "
        f"工具: {r.get('action_summary', '?')}"
        for r in successes[:5]
    ) or "暂无成功案例"

    pos = sum(1 for r in interactions if r.get("user_feedback") == 1)
    neg = sum(1 for r in interactions if r.get("user_feedback") == -1)
    scores = [
        r.get("reflection_score", 0.5) for r in interactions
    ]
    avg = sum(scores) / len(scores) if scores else 0.5

    prompt = _PROMPT_OPTIMIZER_SYSTEM.format(
        current_prompt=current_prompt[:2000],
        failure_examples=fail_text,
        success_examples=success_text,
        positive_count=pos,
        negative_count=neg,
        avg_score=f"{avg:.2f}",
    )

    try:
        response = await llm.ainvoke([
            {"role": "system", "content": prompt},
        ])
        data = extract_json(response.content)
        return data
    except Exception:
        return None
