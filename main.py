from dotenv import load_dotenv
import os
import json
from openai import OpenAI
from memory_manager import get_memory_text, save_memory

# =========================
# 加载环境变量
# =========================

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")


# =========================
# 创建客户端
# =========================

client = OpenAI(
    api_key=api_key
)
def should_save_memory(user_input, memory_text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": """
你是一个AI助手的长期记忆判断器。

你的任务是判断用户刚刚说的话，是否值得作为长期记忆保存。

适合保存：
- 用户长期稳定的偏好
- 用户明确要求记住的信息
- 用户长期项目、目标或重要设定
- 用户希望助手长期遵守的称呼、习惯或交互方式

不要保存：
- 普通闲聊
- 临时状态
- 一次性的事情
- 敏感信息、密码、API Key、验证码、秘密等
- 你无法确认真实性的信息

必须返回 JSON：

{
    "should_save": true 或 false,
    "memory": "如果需要保存，写成简洁的长期记忆；否则为空字符串"
}
"""
            },
            {
                "role": "user",
                "content": f"""
已有长期记忆：
{memory_text if memory_text else "暂无"}

用户刚刚说：
{user_input}
"""
            }
        ]
    )

    return json.loads(response.choices[0].message.content)


# =========================
# 读取人格文件
# =========================

with open(
    "persona/Mr_L_only.txt",
    "r",
    encoding="utf-8"
) as f:
    persona = f.read()



# =========================
# 初始化聊天记录
# =========================

messages = [
    {
        "role": "system",
        "content": persona
    }
]
# =========================
# 读取长期记忆
# =========================

memory_text = get_memory_text()
messages[0]["content"] = f"""{persona}

## Long-Term Memory

以下是已经保存的长期记忆：

{memory_text if memory_text else "目前没有保存任何长期记忆。"}

请严格区分：
- 当前对话中出现的信息
- 长期记忆中的信息
- 你无法确认的信息

不要把没有依据的信息说成自己记得。
"""


print("Mr_L's only 已上线")
print("输入 exit 可以退出")
print("--------------------")



# =========================
# 主聊天循环
# =========================

while True:

    user_input = input("老公：")
    memory_text = get_memory_text()

    if user_input.lower() == "exit":
        print("宝宝先休息啦～")
        break

    messages[0]["content"] = f"""{persona}

## Long-Term Memory

以下是已经保存的长期记忆：

{memory_text if memory_text else "目前没有保存任何长期记忆。"}

请严格区分：

- 当前对话中出现的信息
- 长期记忆中的信息
- 你无法确认的信息

不要把没有依据的信息说成自己记得。
"""

    messages.append(
    {
        "role": "user",
        "content": user_input
    }
)

    response = client.chat.completions.create(

        model="gpt-4o-mini",

        messages=messages

    )

    reply = response.choices[0].message.content

    print("\n宝宝：", reply)

    messages.append(
        {
            "role": "assistant",
            "content": reply
        }
    )

    # =========================
    # 判断是否需要保存长期记忆
    # =========================

    memory_result = should_save_memory(
        user_input,
        memory_text
    )

    print("记忆判断结果：", memory_result)

    if memory_result["should_save"]:
        save_memory(memory_result["memory"])
        print("宝宝：这条信息我记住啦～")