import os
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from agent.tools import calculate, get_current_time, web_search
from dotenv import load_dotenv

load_dotenv()

model = ChatOpenAI(
    model="deepseek-chat",
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    api_key=os.getenv("DEEPSEEK_API_KEY")
)

agent = create_agent(
    model,
    tools=[calculate, get_current_time, web_search],
    system_prompt=(
        "你是一个任务助手，可以自主调用工具完成任务。"
        "重要规则："
        "1. 涉及实时信息（天气、新闻、股价、赛事等）必须调用 web_search，不能凭时间或记忆编造。"
        "2. 涉及数学计算必须调用 calculate。"
        "3. 只有明确问'现在几点''今天几号'时才调用 get_current_time。"
    )
)