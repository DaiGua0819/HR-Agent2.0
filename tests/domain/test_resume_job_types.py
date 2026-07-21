from app.domain.resume.job_types import (
    canonical_resume_job_type,
    display_resume_job_type,
)


def test_senior_fullstack_titles_use_fullstack_resume_label() -> None:
    titles = (
        "资深全栈工程师",
        "资深全栈工程师（AI 原生 B2B 平台 ）",
        "资深全栈工程师（AI 原生 B2B 平台 / 工程 Owner）",
        "资深全栈工程师(AI原生B2B平台/工程Owner)",
        "资深全栈工程...程 Owner）",
    )

    for title in titles:
        assert canonical_resume_job_type(title) == "全栈工程师"
        assert display_resume_job_type(title) == "全栈工程师"
