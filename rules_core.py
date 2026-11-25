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
# 时段前缀：@22:00-06:00（跨天也行）
_TIME = re.compile(r"^@?\s*(\d{1,2})[:：](\d{2})\s*[-~—]\s*(\d{1,2})[:：](\d{2})$")


@dataclass(frozen=True)
class Rule:
    scope: str      # all / group / private
    text: str
    window: tuple[str, str] | None = None   # ("22:00", "06:00")，None＝全天都算


def _hmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def in_window(now_hm: str, start: str, end: str) -> bool:
    """now 落在 [start, end) 里吗；start > end 表示跨天（比如 22:00-06:00）。"""
    now = str(now_hm or "").strip()
    if not now or not start or not end:
        return True
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def parse_rules(raw: str) -> tuple[list[Rule], list[str]]:
    """把配置里的多行文本解析成规矩列表；解析不了的行收集成错误说明。

    一行两种写法：`范围 | 正文`，或带时段 `@22:00-06:00 范围 | 正文`（范围可省，省了就是 all）。
    """
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
        head = parts[0].strip()
        text = parts[1].strip()

        window: tuple[str, str] | None = None
        bad_time = False
        tokens = head.split()
        scope_key = "all"
        for token in tokens:
            hit = _TIME.match(token)
            if hit:
                h1, m1, h2, m2 = (int(x) for x in hit.groups())
                if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
                    bad_time = True
                    errors.append(f"第 {lineno} 行时段「{token}」不是合法时间")
                else:
                    window = (_hmm(h1, m1), _hmm(h2, m2))
                continue
            scope_key = token.strip().lower()

        if bad_time:
            # 时段写歪了就整行丢掉，别让这条悄悄变成全天生效
            continue

        scope = _SCOPES.get(scope_key)
        if scope is None:
            errors.append(f"第 {lineno} 行范围「{scope_key}」不认识，只能是 all / group / private")
            continue
        if not text:
            errors.append(f"第 {lineno} 行只有范围没有内容")
            continue
        rules.append(Rule(scope, text, window))
    return rules, errors


def select(rules: list[Rule], is_group: bool, now_hm: str = "") -> list[Rule]:
    """挑出这个场合、这个钟点该说的规矩：all 一直生效，group/private 各管一边，时段题的到点才算。"""
    want = "group" if is_group else "private"
    out: list[Rule] = []
    for r in rules:
        if r.scope != "all" and r.scope != want:
            continue
        if r.window and not in_window(now_hm, r.window[0], r.window[1]):
            continue
        out.append(r)
    return out


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
