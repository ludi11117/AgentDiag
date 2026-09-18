from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Prompt 模板环境
_prompt_env: Environment = None


def get_prompt_env() -> Environment:
    """获取 Jinja2 模板环境（单例）"""
    global _prompt_env
    if _prompt_env is None:
        template_dir = Path(__file__).parent / "prompts"
        _prompt_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _prompt_env


def render_prompt(template_name: str, **kwargs) -> str:
    """渲染 Prompt 模板"""
    env = get_prompt_env()
    template = env.get_template(template_name)
    return template.render(**kwargs)


# 预定义模板名称常量
class PromptTemplates:
    EXTRACT_FAULT_INFO = "extract_fault_info.j2"
    CHECK_RELEVANCE = "check_relevance.j2"
    AGENT_DIAGNOSE = "agent_diagnose.j2"
    AGENT_REVIEW = "agent_review.j2"
    AGENT_COST = "agent_cost.j2"
    AGENT_WORKORDER = "agent_workorder.j2"
    AGENT_REBUTTAL = "agent_rebuttal.j2"
    AGENT_REVIEW_FINAL = "agent_review_final.j2"
    MAP_EXCLUDED_CAUSES = "map_excluded_causes.j2"
    EVALUATE_SEMANTIC = "evaluate_semantic.j2"
    EXTRACT_IMAGE_INFO = "extract_image_info.j2"
    FIX_SCHEMA = "fix_schema.j2"