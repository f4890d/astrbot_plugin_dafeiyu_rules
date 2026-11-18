"""小鲸鱼的规矩：按场合往系统提示末尾加一小段临时规矩。

为什么单独做：人格卡是「她是谁」，改了要走审核；这里是「这几天该注意什么」，
比如「晚上十点以后别催睡」「群里别主动约人打游戏」，可以随手加、随手关，
不用动人格、不用重启。

写法（WebUI 插件配置的 rules 里一行一条）：

    all | 说话别太整齐，允许有错别字
    group | 群里不要主动聊主人的私事
    private | 主人说累了就不要再追问他今天干了什么

范围只认 all / group / private；# 开头的行当注释跳过。
"""

from __future__ import annotations

import sys
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

try:
    from .rules_core import parse_rules, render, select
except ImportError:  # 单独跑测试时按脚本导入
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from rules_core import parse_rules, render, select

PLUGIN_NAME = "astrbot_plugin_dafeiyu_rules"
DEFAULT_HEADER = "【此刻的规矩】"


class DafeiyuRules(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.conf = config or {}
        self._raw = None
        self._rules = []
        self._errors = []
        self._last_logged = None
        self._reload()

    # ---------- 配置 ----------

    def _get(self, key, default=None):
        try:
            value = self.conf.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        return default if value is None else value

    def _enabled(self) -> bool:
        value = self._get("enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "off", "关")
        return bool(value)

    def _reload(self) -> None:
        raw = str(self._get("rules", "") or "")
        if raw == self._raw:
            return
        self._raw = raw
        self._rules, self._errors = parse_rules(raw)
        for err in self._errors:
            logger.warning(f"[rules] 规矩格式有问题：{err}")
        logger.info(f"[rules] 载入 {len(self._rules)} 条规矩")

    # ---------- 场合 ----------

    @staticmethod
    def _is_group(event) -> bool:
        try:
            if event.get_group_id():
                return True
        except Exception:  # noqa: BLE001
            pass
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        return "GroupMessage" in umo or ":group:" in umo

    # ---------- 注入 ----------

    def _build_block(self, event) -> tuple[str, int]:
        """按这个场合拼出要追加的一段；返回（文本，生效条数）。单独拆出来是方便测。"""
        if not self._enabled():
            return "", 0
        self._reload()
        active = select(self._rules, self._is_group(event))
        block = render(
            active,
            header=str(self._get("header", DEFAULT_HEADER) or DEFAULT_HEADER),
            max_chars=self._get("max_chars", 600),
        )
        return block, len(active)

    @filter.on_llm_request()
    async def add_scoped_rules(self, event: AstrMessageEvent, req) -> None:
        try:
            block, count = self._build_block(event)
            if not block:
                return
            # 一次请求可能因为重试被钩多次，同一段别重复塞
            marker = getattr(event, "_dafeiyu_rules_block", None)
            if marker == block:
                return
            event._dafeiyu_rules_block = block  # type: ignore[attr-defined]

            base = getattr(req, "system_prompt", "") or ""
            if block in base:
                return
            req.system_prompt = f"{base}\n\n{block}" if base else block

            # 只在「这轮注入跟上一轮不一样」时记一条 info，免得刷屏
            stamp = (self._is_group(event), block)
            if stamp != self._last_logged:
                self._last_logged = stamp
                where = "群里" if stamp[0] else "私聊"
                logger.info(f"[rules] {where}注入 {count} 条规矩（{len(block)} 字）")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[rules] 注入失败，跳过这轮：{exc}")

    # ---------- 命令 ----------

    @filter.command("规矩")
    async def show_rules(self, event: AstrMessageEvent):
        """看看这个场合现在生效哪几条（只给主人看）"""
        try:
            if not event.is_admin():
                yield event.plain_result("这个只有主人能看。")
                return
        except Exception:  # noqa: BLE001
            pass

        self._reload()
        here_group = self._is_group(event)
        active = select(self._rules, here_group)
        where = "群里" if here_group else "私聊"

        if not self._rules:
            yield event.plain_result(
                f"现在一条规矩都没有。要加的话去插件配置里写「范围 | 规矩」，"
                f"范围填 all / group / private。"
            )
            return

        lines = [f"{where}现在用 {len(active)} 条（一共 {len(self._rules)} 条）："]
        for rule in active:
            lines.append(f"· [{rule.scope}] {rule.text}")
        if self._errors:
            lines.append(f"另有 {len(self._errors)} 行格式没认出来，去看日志。")
        yield event.plain_result("\n".join(lines))
