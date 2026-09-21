import asyncio
from agent.service import agent

async def ask(question):
    print(f"\n=== 问题：{question} ===")
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    for msg in result["messages"]:
        if msg.content:
            print(f"[{msg.type}] {msg.content}")

async def main():
    await ask("帮我算一下 123 * 456 等于多少")
    await ask("现在几点了？")

asyncio.run(main())