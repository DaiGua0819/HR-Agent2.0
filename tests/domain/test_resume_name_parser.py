"""Resume display-name parsing and source-priority regression tests."""

from app.domain.resume.name_parser import (
    choose_resume_name,
    parse_resume_name,
    parse_resume_name_from_file,
)


def test_parse_resume_name_rejects_resume_section_headings_and_job_text() -> None:
    text = """个人简历
应聘职位：AI 产品经理（杭州）
联系方式
教育背景
杭州博彦信息技术有限公司
"""

    assert parse_resume_name(text) == ""


def test_parse_resume_name_accepts_explicit_labeled_chinese_name() -> None:
    text = """个人信息
姓名：仲猷平 性别：男 出生日期：19880702
AI 产品经理
"""

    assert parse_resume_name(text) == "仲猷平"


def test_parse_resume_name_from_supported_platform_file_names() -> None:
    assert parse_resume_name_from_file("51job_蔡希玮_AI 产品经理_c36b898f.pdf") == "蔡希玮"
    assert parse_resume_name_from_file("zhilian_隋心怡_AI应用开发实习生_47476.pdf") == "隋心怡"
    assert parse_resume_name_from_file("隋心怡_21岁_AI应用开发实习生_湖州_智联简历.pdf") == "隋心怡"
    assert parse_resume_name_from_file("邮箱_8205_【AI产品经理】刘帅_10年.pdf") == "刘帅"
    assert parse_resume_name_from_file("zhilian_resume_attachment_480b1fa3.pdf") == ""


def test_choose_resume_name_keeps_explicit_platform_name() -> None:
    assert (
        choose_resume_name(
            platform_name="蔡希玮",
            document_name="应聘职位",
            file_name="51job_蔡希玮_AI 产品经理_c36b898f.pdf",
        )
        == "蔡希玮"
    )


def test_choose_resume_name_can_expand_anonymous_platform_name() -> None:
    assert (
        choose_resume_name(
            platform_name="周先生",
            document_name="周浩然",
            file_name="51job_周先生_AI 产品经理_0ff83d5d.pdf",
        )
        == "周浩然"
    )


def test_choose_resume_name_falls_back_to_anonymous_platform_name() -> None:
    assert (
        choose_resume_name(
            platform_name="周先生",
            document_name="教育背景",
            file_name="51job_周先生_AI 产品经理_0ff83d5d.pdf",
        )
        == "周先生"
    )
