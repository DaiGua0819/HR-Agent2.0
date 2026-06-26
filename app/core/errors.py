"""项目级异常类型。"""


class HrAgentError(Exception):
    """招聘智能体新系统的基础异常。"""


class LLMConfigurationError(HrAgentError):
    """LLM 运行期配置缺失或不合法。"""
