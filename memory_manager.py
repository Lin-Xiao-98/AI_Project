import json
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
MEMORY_FILE = PROJECT_DIR / "data" / "memory.json"
LEGACY_MEMORY_FILE = PROJECT_DIR / "memory.json"

USER_SUBCATEGORIES = {"preferences", "habits", "learning_style"}
VALID_CATEGORIES = {"user", "projects", "temporary", "assistant"}

EMPTY_MEMORY = {
    "user": {
        "preferences": [],
        "habits": [],
        "learning_style": [],
    },
    "projects": {},
    "temporary": [],
    "assistant": [],
}

SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?[^\s]*key=", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{12,}\b", re.I),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"(?i)(?:api[_ -]?key|password|passwd|token|secret|密码|验证码|令牌)"
        r"\s*(?::|=|：|是|为|is)\s*\S{4,}"
    ),
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
)


def _metadata_file():
    return MEMORY_FILE.with_name("memory_metadata.json")


def _load_metadata():
    path = _metadata_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_metadata(metadata):
    path = _metadata_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix="memory_meta_", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _set_temporary_expiration(value):
    days = max(int(os.getenv("TEMPORARY_MEMORY_DAYS", "30")), 1)
    metadata = _load_metadata()
    metadata[_normalise_text(value)] = {
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(
            timespec="seconds"
        )
    }
    _write_metadata(metadata)


def _remove_expiration(value):
    metadata = _load_metadata()
    if metadata.pop(_normalise_text(value), None) is not None:
        _write_metadata(metadata)


def _prune_expired(memory):
    metadata = _load_metadata()
    if not metadata:
        return False
    now = datetime.now(timezone.utc)
    kept = []
    changed = False
    for value in memory["temporary"]:
        key = _normalise_text(value)
        raw_expiration = (metadata.get(key) or {}).get("expires_at")
        try:
            expired = bool(
                raw_expiration and datetime.fromisoformat(raw_expiration) <= now
            )
        except (TypeError, ValueError):
            expired = False
        if expired:
            metadata.pop(key, None)
            changed = True
        else:
            kept.append(value)
    if changed:
        memory["temporary"] = kept
        _write_metadata(metadata)
    return changed


def _normalise_text(value):
    """生成仅用于比较的文本，不修改真实保存内容。"""
    if not isinstance(value, str):
        return ""

    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", "", value).casefold()
    return value.rstrip("。！？，、；：.!?,;:")


def _normalise_memory_structure(raw_memory):
    """补齐缺失字段，并兼容 V0.1 的 {"memories": [...]} 格式。"""
    memory = deepcopy(EMPTY_MEMORY)

    if not isinstance(raw_memory, dict):
        raise ValueError("memory.json 的顶层必须是 JSON 对象")

    if isinstance(raw_memory.get("memories"), list):
        memory["user"]["preferences"] = list(raw_memory["memories"])
        return memory

    raw_user = raw_memory.get("user", {})
    if isinstance(raw_user, dict):
        for subcategory in USER_SUBCATEGORIES:
            values = raw_user.get(subcategory, [])
            if isinstance(values, list):
                memory["user"][subcategory] = list(values)

    raw_projects = raw_memory.get("projects", {})
    if isinstance(raw_projects, dict):
        memory["projects"] = {
            str(name): list(values)
            for name, values in raw_projects.items()
            if isinstance(values, list)
        }

    for category in ("temporary", "assistant"):
        values = raw_memory.get(category, [])
        if isinstance(values, list):
            memory[category] = list(values)

    return memory


def load_memory():
    """读取长期记忆；文件不存在时返回空结构。"""
    if not MEMORY_FILE.exists():
        if LEGACY_MEMORY_FILE.exists():
            with open(LEGACY_MEMORY_FILE, "r", encoding="utf-8") as file:
                migrated = _normalise_memory_structure(json.load(file))
            _write_memory(migrated)
            return migrated
        return deepcopy(EMPTY_MEMORY)

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            memory = _normalise_memory_structure(json.load(file))
        if _prune_expired(memory):
            _write_memory(memory)
        return memory
    except json.JSONDecodeError as error:
        raise ValueError(f"memory.json 格式错误：{error}") from error


def _write_memory(memory):
    """先写临时文件再替换，降低程序中断造成文件损坏的风险。"""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix="memory_",
        suffix=".tmp",
        dir=MEMORY_FILE.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(memory, file, ensure_ascii=False, indent=4)
            file.write("\n")
        os.replace(temp_name, MEMORY_FILE)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _validate_location(category, subcategory=None):
    if category not in VALID_CATEGORIES:
        raise ValueError(f"未知的记忆分类：{category}")

    if category == "user" and subcategory not in USER_SUBCATEGORIES:
        raise ValueError(f"未知的用户记忆分类：{subcategory}")

    if category == "projects":
        if not isinstance(subcategory, str) or not subcategory.strip():
            raise ValueError("项目记忆必须提供项目名称")


def _get_bucket(memory, category, subcategory=None, create=False):
    _validate_location(category, subcategory)

    if category == "user":
        return memory["user"][subcategory]
    if category == "projects":
        project_name = subcategory.strip()
        if create:
            return memory["projects"].setdefault(project_name, [])
        return memory["projects"].get(project_name)
    return memory[category]


def _iter_buckets(memory):
    for subcategory in sorted(USER_SUBCATEGORIES):
        yield "user", subcategory, memory["user"][subcategory]
    for project_name, values in memory["projects"].items():
        yield "projects", project_name, values
    yield "temporary", "", memory["temporary"]
    yield "assistant", "", memory["assistant"]


def _find_memory(memory, target_memory):
    target_key = _normalise_text(target_memory)
    if not target_key:
        return None

    for category, subcategory, bucket in _iter_buckets(memory):
        for index, item in enumerate(bucket):
            if _normalise_text(item) == target_key:
                return category, subcategory, bucket, index
    return None


def _validate_memory_content(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("记忆内容不能为空")
    if any(pattern.search(value) for pattern in SENSITIVE_PATTERNS):
        raise ValueError("检测到密钥、密码、验证码或身份证号，拒绝写入长期记忆")


def get_memory_text():
    """把结构化长期记忆转换成 AI 可以理解的文字。"""
    memory = load_memory()
    sections = []

    labels = {
        "preferences": "用户偏好",
        "habits": "用户习惯",
        "learning_style": "学习方式",
    }
    for subcategory, label in labels.items():
        values = memory["user"][subcategory]
        if values:
            sections.append(
                f"## {label}\n" + "\n".join(f"- {item}" for item in values)
            )

    for project_name, values in memory["projects"].items():
        if values:
            sections.append(
                f"## 项目：{project_name}\n"
                + "\n".join(f"- {item}" for item in values)
            )

    for category, label in (
        ("temporary", "临时记忆"),
        ("assistant", "助手信息"),
    ):
        values = memory[category]
        if values:
            sections.append(
                f"## {label}\n" + "\n".join(f"- {item}" for item in values)
            )

    return "\n\n".join(sections)


def get_memory_count():
    """返回所有分类中的长期记忆总数。"""
    memory = load_memory()
    return sum(len(bucket) for _, _, bucket in _iter_buckets(memory))


def save_memory(new_memory, category, subcategory=None):
    """保存新记忆。成功返回 True，重复记忆返回 False。"""
    _validate_memory_content(new_memory)

    memory = load_memory()
    if _find_memory(memory, new_memory) is not None:
        return False

    bucket = _get_bucket(memory, category, subcategory, create=True)
    bucket.append(new_memory.strip())
    _write_memory(memory)
    if category == "temporary":
        _set_temporary_expiration(new_memory)
    return True


def update_memory(target_memory, new_memory, category, subcategory=None):
    """更新一条已有记忆，也允许把它移动到新的分类。"""
    _validate_memory_content(new_memory)

    memory = load_memory()
    found = _find_memory(memory, target_memory)
    if found is None:
        return False

    old_category, old_subcategory, old_bucket, old_index = found
    old_value = old_bucket[old_index]
    new_key = _normalise_text(new_memory)

    existing = _find_memory(memory, new_memory)
    if existing is not None:
        _, _, existing_bucket, existing_index = existing
        if existing_bucket is not old_bucket or existing_index != old_index:
            old_bucket.pop(old_index)
            if old_category == "projects" and not old_bucket:
                del memory["projects"][old_subcategory]
            _write_memory(memory)
            if old_category == "temporary":
                _remove_expiration(old_value)
            return True

    target_bucket = _get_bucket(memory, category, subcategory, create=True)

    if old_bucket is target_bucket:
        for index, item in enumerate(target_bucket):
            if index != old_index and _normalise_text(item) == new_key:
                old_bucket.pop(old_index)
                _write_memory(memory)
                return True
        old_bucket[old_index] = new_memory.strip()
    else:
        old_bucket.pop(old_index)
        if old_category == "projects" and not old_bucket:
            del memory["projects"][old_subcategory]
        if not any(_normalise_text(item) == new_key for item in target_bucket):
            target_bucket.append(new_memory.strip())

    _write_memory(memory)
    if old_category == "temporary":
        _remove_expiration(old_value)
    if category == "temporary":
        _set_temporary_expiration(new_memory)
    return True


def delete_memory(target_memory):
    """按规范化后的完整文本删除一条记忆。"""
    memory = load_memory()
    found = _find_memory(memory, target_memory)
    if found is None:
        return False

    category, subcategory, bucket, index = found
    bucket.pop(index)
    if category == "projects" and not bucket:
        del memory["projects"][subcategory]
    _write_memory(memory)
    if category == "temporary":
        _remove_expiration(target_memory)
    return True
