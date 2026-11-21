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


# 平台 id → 她嘴里怎么称呼这个渠道
CHANNELS = {
    "aiocqhttp": "QQ",
    "qq": "QQ",
    "weixin_oc": "微信",
    "wechat": "微信",
    "bluewhale": "桌面桌宠（桌面上那个 Live2D 的她）",
    "webchat": "网页 / DSH 桌面端",
    "dsh": "网页 / DSH 桌面端",
    "lark": "飞书",
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "Slack",
    "kook": "KOOK",
    "dingtalk": "钉钉",
}


def channel_name(platform: str, shown: str = "") -> str:
    """把平台 id 翻成人话；认不出来就用对方给的显示名，再不行就返回原 id。"""
    key = str(platform or "").strip().lower()
    if key in CHANNELS:
        return CHANNELS[key]
    # 复合 id（比如 wechat:aiocqhttp）里取最长的那个匹配，别让短词先抢走
    for k, v in sorted(CHANNELS.items(), key=lambda kv: -len(kv[0])):
        if k and k in key:
            return v
    return str(shown or platform or "").strip() or "未知渠道"


def channel_line(platform: str, umo: str, is_group: bool, shown: str = "") -> str:
    """「你现在在哪」这一行：让她知道这句是从哪个渠道、哪个场合来的。

    私聊不写会话 id：模型不需要，还会把 wxid / QQ 号写进提示和日志里。
    群聊只留群号，她确实用得上（同一个群和不同群要分得清）。
    """
    name = channel_name(platform, shown)
    where = "群聊" if is_group else "私聊"
    line = f"【你现在在哪】主人这条消息是从「{name}」的{where}发来的"
    umo = str(umo or "").strip()
    if is_group and umo:
        gid = umo.rsplit(":", 1)[-1]
        if gid.isdigit():
            line += f"（群 {gid}）"
    line += "。渠道别答错：主人问起你从哪跟他说话，就照这个说；他说自己在手机/电脑上，那是设备，不是渠道。"
    return line


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
