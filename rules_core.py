"""规矩的小内核：解析、按场合挑、渲染成一段话。

故意不 import astrbot，这样这份逻辑能脱离插件单独测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 一行一条，写成「范围 | 规矩正文」；范围支持中英文写法，方便我自己记
_SCOPES = {
    "all": "all",
    "both": "all",
    "全部": "all",
    "公共": "all",
    "group": "group",
    "群": "group",
    "群聊": "group",
    "private": "private",
    "私": "private",
    "私聊": "private",
}

_SEP = re.compile(r"\s*[|｜]\s*")


@dataclass(frozen=True)
class Rule:
    scope: str      # all / group / private
    text: str


def parse_rules(raw: str) -> tuple[list[Rule], list[str]]:
    """把配置里的多行文本解析成规矩列表；解析不了的行收集成错误说明。"""
    rules: list[Rule] = []
    errors: list[str] = []
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = _SEP.split(s, maxsplit=1)
        if len(parts) == 1:
            errors.append(f"第 {lineno} 行没写范围（要 all/group/private 加竖线）：{s[:40]}")
            continue
        scope_key = parts[0].strip().lower()
        text = parts[1].strip()
        scope = _SCOPES.get(scope_key)
        if scope is None:
            errors.append(f"第 {lineno} 行范围「{scope_key}」不认识，只能是 all / group / private")
            continue
        if not text:
            errors.append(f"第 {lineno} 行只有范围没有内容")
            continue
        rules.append(Rule(scope, text))
    return rules, errors


def select(rules: list[Rule], is_group: bool) -> list[Rule]:
    """挑出这个场合该说的规矩：all 一直生效，group/private 各管一边。"""
    want = "group" if is_group else "private"
    return [r for r in rules if r.scope == "all" or r.scope == want]


def render(rules: list[Rule], header: str = "【此刻的规矩】", max_chars: int = 600) -> str:
    """渲染成可直接追加到 system prompt 末尾的一段；空列表返回空串。"""
    if not rules:
        return ""
    head = (header or "").strip() or "【此刻的规矩】"
    try:
        limit = max(80, int(max_chars))
    except (TypeError, ValueError):
        limit = 600

    lines: list[str] = []
    used = len(head) + 1
    truncated = False
    for r in rules:
        line = f"- {r.text}"
        if used + len(line) + 1 > limit:
            truncated = True
            break
        lines.append(line)
        used += len(line) + 1
    if truncated:
        lines.append("- （规矩还有几条，这次没全写进来）")
    return head + "\n" + "\n".join(lines)
