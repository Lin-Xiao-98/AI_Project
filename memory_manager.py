import json


MEMORY_FILE = "memory.json"


def load_memory():
    """读取长期记忆"""
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_memory_text():
    """把长期记忆转换成 AI 可以理解的文字"""
    memory = load_memory()

    return "\n".join(
        f"- {item}"
        for item in memory["memories"]
    )


def save_memory(new_memory):
    """保存一条新的长期记忆"""
    memory = load_memory()

    memory["memories"].append(new_memory)

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            memory,
            f,
            ensure_ascii=False,
            indent=4
        )