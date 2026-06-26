"""面试题生成。

对应旧 `questionGenerator.js`：基于简历、岗位和会话上下文组 prompt 调 LLM。测试用假 LLM，
真实调用走已有 `LLMClient.chat_completions`。
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.core.text import clean_text, clip_text
from app.llm.client import LLMClient


class QuestionLLMProtocol(Protocol):
    """出题所需的 LLM 协议。"""

    async def chat_completions(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """返回 OpenAI 兼容响应。"""


async def generate_interview_questions(
    resume_id: str,
    *,
    resume: dict[str, Any] | None = None,
    job_type: str = "",
    conversation: list[dict[str, Any]] | None = None,
    llm: QuestionLLMProtocol | None = None,
) -> list[dict[str, str]]:
    """按简历和岗位生成结构化面试题。"""

    generator = InterviewQuestionGenerator(llm or LLMClient())
    return await generator.generate(
        resume={"id": resume_id, **(resume or {})},
        job_type=job_type,
        conversation=conversation or [],
    )


class InterviewQuestionGenerator:
    """面试题生成器。"""

    def __init__(self, llm: QuestionLLMProtocol) -> None:
        self.llm = llm

    async def generate(
        self,
        *,
        resume: dict[str, Any],
        job_type: str,
        conversation: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """生成 5 道面试题，优先解析 LLM JSON；失败时返回保守兜底题。"""

        messages = build_question_prompt(
            resume=resume,
            job_type=job_type,
            conversation=conversation,
        )
        try:
            response = await self.llm.chat_completions(messages, temperature=0.2)
        except Exception:
            return fallback_questions(job_type)
        content = _extract_content(response)
        parsed = _parse_questions(content)
        return parsed or fallback_questions(job_type)


def build_question_prompt(
    *,
    resume: dict[str, Any],
    job_type: str,
    conversation: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """构造出题 prompt。"""

    resume_text = clip_text(
        json.dumps(resume, ensure_ascii=False, sort_keys=True),
        max_length=3000,
    )
    conversation_text = clip_text(
        "\n".join(
            f"{item.get('sender', '')}: {item.get('text', '')}"
            for item in conversation
        ),
        max_length=1200,
    )
    return [
        {
            "role": "system",
            "content": "你是招聘面试官，请输出 JSON 数组，每项包含 category/question/focus。",
        },
        {
            "role": "user",
            "content": (
                f"岗位：{job_type or resume.get('job_type') or resume.get('applied_position')}\n"
                f"简历：{resume_text}\n"
                f"沟通记录：{conversation_text}\n"
                "请生成 5 道可追问的结构化面试题。"
            ),
        },
    ]


def fallback_questions(job_type: str) -> list[dict[str, str]]:
    """LLM 异常或返回不可解析时的保守题库。"""

    role = clean_text(job_type) or "目标岗位"
    return [
        {
            "category": "经历核验",
            "question": f"请介绍一次最能体现你匹配{role}的项目。",
            "focus": "真实性",
        },
        {
            "category": "岗位理解",
            "question": f"你认为{role}最关键的三项能力是什么？",
            "focus": "岗位认知",
        },
        {
            "category": "能力追问",
            "question": "遇到目标不清晰或资源不足时你如何推进？",
            "focus": "解决问题",
        },
        {"category": "协作沟通", "question": "请举例说明一次跨团队协作经历。", "focus": "沟通协作"},
        {"category": "稳定性", "question": "你选择下一份机会时最看重什么？", "focus": "动机稳定性"},
    ]


def _extract_content(response: dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return ""


def _parse_questions(content: str) -> list[dict[str, str]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    questions: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        question = clean_text(item.get("question"))
        if not question:
            continue
        questions.append(
            {
                "category": clean_text(item.get("category")) or "综合",
                "question": question,
                "focus": clean_text(item.get("focus")) or "追问证据",
            }
        )
    return questions
