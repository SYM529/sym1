"""模型定义。

单独成模块是为了打破循环依赖：graph 的节点需要 model，而 service 又要 import graph，
如果 model 定义在 service 里就会形成 service → graph → service 的环。

模型**懒加载**，不在模块导入时创建。这样在没有 API Key 的环境里
（例如 CI 里跑单元测试、只做静态校验）依然可以正常 import，
只有真正调用模型时才报错——把"配置缺失"推迟到使用点，
而不是让整个进程在 import 阶段就崩掉。
"""

import os

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI  # noqa: E402

# 模型接入统一走 LLM_* 变量；未配置时回退到早期的 DEEPSEEK_* 变量名。
# 任何 OpenAI 兼容服务商（DeepSeek 官方、硅基流动、OpenRouter 等）
# 都只需要改 .env 里的三行，代码不用动。
MODEL_NAME = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

_model: ChatOpenAI | None = None


def get_model() -> ChatOpenAI:
    """获取对话模型实例（单例，首次调用时校验配置）。"""
    global _model
    if _model is None:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("缺少 LLM_API_KEY（或 DEEPSEEK_API_KEY），请在 .env 中配置")
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL")
        kwargs = {}
        # 混合推理模型（如 DeepSeek-V4-Flash）默认会输出 <think> 思考过程，
        # 原样透传到聊天界面就是一屏推理文字。LLM_DISABLE_THINKING=1 时
        # 请求携带 enable_thinking=false；不支持该参数的服务商会报 400，
        # 所以做成开关而不是无条件发送。
        if os.getenv("LLM_DISABLE_THINKING", "").lower() in ("1", "true", "yes"):
            kwargs["extra_body"] = {"enable_thinking": False}
        _model = ChatOpenAI(
            model=MODEL_NAME,
            base_url=base_url,
            api_key=api_key,
            temperature=0,
            **kwargs,
        )
    return _model
