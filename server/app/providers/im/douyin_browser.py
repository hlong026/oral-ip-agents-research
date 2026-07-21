"""用扫码保存的浏览器登录态同步抖音网页私信并发送回复。"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.publish.browser_pool import BrowserSlot
from app.providers.publish.sau_conf import resolve_browser_executable

logger = get_logger("oral.im.douyin_browser")

CHAT_URL = "https://www.douyin.com/chat"
CONVERSATION_SELECTOR = 'div[class*="conversationConversationItemwrapper"]'
INPUT_SELECTOR = '[contenteditable="true"].public-DraftEditor-content, [contenteditable="true"]'
_BROWSER_LOCK = asyncio.Lock()


class BrowserIMError(RuntimeError):
    pass


def normalize_browser_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    conversation = snapshot.get("conversation") or {}
    nickname = str(conversation.get("name") or "").strip()
    avatar = str(conversation.get("avatar") or "").strip()
    conversation_id = str(conversation.get("conversationId") or "").strip()
    row_remote_uid = str(conversation.get("remoteUid") or "").strip()
    identity = conversation_id or row_remote_uid or f"{nickname}|{avatar}"
    remote_uid = row_remote_uid or f"browser:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"

    records: list[dict[str, Any]] = []
    for fallback_index, raw in enumerate(snapshot.get("messages") or []):
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        direction = "out" if raw.get("mine") else "in"
        browser_index = int(raw.get("index", fallback_index))
        timestamp = str(raw.get("time") or "")
        message_key = "|".join((identity, direction, timestamp, str(browser_index), text))
        records.append(
            {
                "remote_uid": remote_uid,
                "remote_nickname": nickname,
                "remote_avatar": avatar,
                "direction": direction,
                "msg_type": 7,
                "content": text,
                "dy_conversation_id": conversation_id,
                "dy_conversation_short_id": "",
                "dy_ticket": "",
                "remote_message_id": f"browser:{hashlib.sha256(message_key.encode()).hexdigest()}",
                # 网页 DOM 序号不是平台真实消息序号，不能作为唯一键。
                "remote_index": None,
            }
        )
    return records


class DouyinBrowserIMClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def sync_messages(self, session: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        if not self._settings.douyin_im_browser_enabled:
            return []
        async with asyncio.timeout(self._settings.douyin_im_browser_timeout_sec), _BROWSER_LOCK, BrowserSlot():
            async with self._browser_page(session) as page:
                await self._open_chat(page)
                conversations = (await self._conversation_rows(page))[:20]
                records: list[dict[str, Any]] = []
                per_conversation = max(1, limit // max(1, len(conversations)))
                for conversation in conversations:
                    if not await self._click_conversation(
                        page,
                        conversation["name"],
                        conversation.get("remoteUid", ""),
                    ):
                        continue
                    await page.wait_for_timeout(600)
                    await self._load_older_messages(page)
                    messages = await self._visible_messages(page)
                    snapshot = {"conversation": conversation, "messages": messages}
                    records.extend(normalize_browser_snapshot(snapshot)[-per_conversation:])
                return records[:limit]

    async def send_message(
        self,
        session: dict[str, Any],
        remote_uid: str,
        remote_nickname: str,
        content: str,
    ) -> bool:
        if not self._settings.douyin_im_browser_enabled:
            raise BrowserIMError("抖音浏览器回复未启用")
        target = remote_nickname.strip()
        if not target and (not remote_uid or remote_uid.startswith("browser:")):
            raise BrowserIMError("会话缺少抖音昵称，请先同步历史会话后再回复")

        async with asyncio.timeout(self._settings.douyin_im_browser_timeout_sec), _BROWSER_LOCK, BrowserSlot():
            async with self._browser_page(session) as page:
                await self._open_chat(page)
                if not await self._click_conversation(page, target, remote_uid):
                    label = target or remote_uid
                    raise BrowserIMError(f"私信列表中未找到“{label}”")
                await page.wait_for_timeout(600)
                input_box = await self._visible_input(page)
                if input_box is None:
                    raise BrowserIMError("未找到抖音私信输入框")
                await input_box.click()
                await input_box.press_sequentially(content, delay=20)
                sent = await self._click_send(page)
                if not sent:
                    raise BrowserIMError("未找到可用的抖音发送按钮")
                await page.wait_for_timeout(1500)
                remaining = (await input_box.inner_text()).strip()
                if remaining:
                    raise BrowserIMError("抖音页面未确认发送成功")
                return True

    @asynccontextmanager
    async def _browser_page(self, session: dict[str, Any]) -> AsyncIterator[Any]:
        try:
            from patchright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserIMError("patchright 未安装，无法启动抖音消息页") from exc

        storage_state = {
            "cookies": list(session.get("cookies") or []),
            "origins": list(session.get("origins") or []),
        }
        if not storage_state["cookies"]:
            raise BrowserIMError("抖音登录态缺少浏览器 Cookie，请重新扫码绑定")

        executable = resolve_browser_executable(self._settings.publish_browser_executable_path)
        if not executable:
            raise BrowserIMError("未找到 Chrome 或 Edge，请配置 PUBLISH_BROWSER_EXECUTABLE_PATH")
        launch_kwargs: dict[str, Any] = {
            "headless": self._settings.publish_browser_headless,
            "executable_path": executable,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                storage_state=cast(Any, storage_state),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            try:
                yield page
            finally:
                await context.close()
                await browser.close()

    async def _open_chat(self, page: Any) -> None:
        await page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=self._settings.douyin_im_browser_timeout_ms)
        await page.wait_for_timeout(2000)
        if await page.locator(CONVERSATION_SELECTOR).count() > 0:
            return

        clicked = await page.evaluate(
            """() => {
                const all = Array.from(document.querySelectorAll('*'));
                const entry = all.find(el => {
                    const text = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    return (text === '私信' || text.startsWith('私信'))
                        && rect.width > 0 && rect.height > 0 && rect.width < 120
                        && rect.left > window.innerWidth - 240;
                });
                if (!entry) return false;
                entry.click();
                return true;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(1800)

        body = (await page.locator("body").inner_text()).strip()
        if await page.locator(CONVERSATION_SELECTOR).count() == 0 and any(
            marker in body for marker in ("扫码登录", "登录后即可", "手机号登录")
        ):
            raise BrowserIMError("抖音网页登录态已失效，请重新扫码绑定")

    async def _conversation_rows(self, page: Any) -> list[dict[str, str]]:
        rows = await page.evaluate(
            """selector => {
              const metadata = el => {
                const seen = new Set();
                const queue = [];
                for (const key of Object.keys(el)) {
                  if (key.startsWith('__reactProps$') || key.startsWith('__reactFiber$')) queue.push(el[key]);
                }
                for (let i = 0; i < queue.length && i < 250; i++) {
                  const value = queue[i];
                  if (!value || typeof value !== 'object' || seen.has(value)) continue;
                  seen.add(value);
                  const uid = value.uid || value.userId || value.user_id || value.secUid || value.sec_uid;
                  const conversationId = value.conversationId || value.conversation_id;
                  if (uid || conversationId) return {
                    remoteUid: uid ? String(uid) : '', conversationId: conversationId ? String(conversationId) : ''
                  };
                  for (const child of Object.values(value)) {
                    if (child && typeof child === 'object') queue.push(child);
                  }
                }
                return {remoteUid: '', conversationId: ''};
              };
              return Array.from(document.querySelectorAll(selector)).map((el, index) => {
                const lines = (el.innerText || '').split('\n').map(v => v.trim()).filter(Boolean);
                const img = el.querySelector('img');
                const conversationAttr = Array.from(el.attributes).find(attr =>
                    attr.name.toLowerCase().includes('conversation') && attr.name.toLowerCase().includes('id')
                );
                const meta = metadata(el);
                return {
                    name: lines.find(line => line !== '置顶') || '',
                    avatar: img ? (img.currentSrc || img.src || '') : '',
                    conversationId: conversationAttr ? conversationAttr.value : meta.conversationId,
                    remoteUid: meta.remoteUid,
                    index: String(index),
                };
              }).filter(item => item.name);
            }""",
            CONVERSATION_SELECTOR,
        )
        return list(rows)

    async def _click_conversation(self, page: Any, target: str, remote_uid: str = "") -> bool:
        return bool(
            await page.evaluate(
                """({selector, target, remoteUid}) => {
                    const candidates = Array.from(document.querySelectorAll(selector));
                    const row = candidates.find(el => {
                        if (target && (el.innerText || '').includes(target)) return true;
                        if (!remoteUid || remoteUid.startsWith('browser:')) return false;
                        const seen = new Set();
                        const queue = Object.keys(el)
                            .filter(key => key.startsWith('__reactProps$') || key.startsWith('__reactFiber$'))
                            .map(key => el[key]);
                        for (let i = 0; i < queue.length && i < 250; i++) {
                            const value = queue[i];
                            if (!value || typeof value !== 'object' || seen.has(value)) continue;
                            seen.add(value);
                            const uid = value.uid || value.userId || value.user_id || value.secUid || value.sec_uid;
                            if (uid && String(uid) === remoteUid) return true;
                            for (const child of Object.values(value)) {
                                if (child && typeof child === 'object') queue.push(child);
                            }
                        }
                        return false;
                    });
                    if (!row) return false;
                    row.scrollIntoView({block: 'center', behavior: 'instant'});
                    const rect = row.getBoundingClientRect();
                    const event = type => new MouseEvent(type, {
                        view: window, bubbles: true, cancelable: true,
                        clientX: rect.left + rect.width / 2,
                        clientY: rect.top + rect.height / 2,
                        buttons: 1,
                    });
                    row.dispatchEvent(event('mousedown'));
                    row.dispatchEvent(event('mouseup'));
                    row.dispatchEvent(event('click'));
                    return true;
                }""",
                {"selector": CONVERSATION_SELECTOR, "target": target, "remoteUid": remote_uid},
            )
        )

    async def _visible_input(self, page: Any) -> Any | None:
        inputs = page.locator(INPUT_SELECTOR)
        for index in range(await inputs.count() - 1, -1, -1):
            candidate = inputs.nth(index)
            if await candidate.is_visible():
                return candidate
        return None

    async def _load_older_messages(self, page: Any) -> None:
        for _ in range(3):
            moved = await page.evaluate(
                """() => {
                    const preferred = document.querySelector('.IRB0Sra6') || document.querySelector('.z1iI1SFY');
                    const candidates = preferred ? [preferred] : Array.from(document.querySelectorAll('*'));
                    const area = candidates.find(el => {
                        const r = el.getBoundingClientRect();
                        return r.width >= 380 && r.width <= 650 && r.height >= 280 && r.height <= 820
                            && r.left > window.innerWidth * 0.45 && el.scrollHeight > el.clientHeight;
                    });
                    if (!area || area.scrollTop === 0) return false;
                    area.scrollTop = 0;
                    return true;
                }"""
            )
            if not moved:
                break
            await page.wait_for_timeout(700)

    async def _visible_messages(self, page: Any) -> list[dict[str, Any]]:
        return list(
            await page.evaluate(
                """() => {
                    const preferred = document.querySelector('.IRB0Sra6') || document.querySelector('.z1iI1SFY');
                    const candidates = preferred ? [preferred] : Array.from(document.querySelectorAll('*'));
                    const area = candidates.find(el => {
                        const r = el.getBoundingClientRect();
                        return r.width >= 380 && r.width <= 700 && r.height >= 280 && r.height <= 900
                            && r.left > window.innerWidth * 0.35 && el.scrollHeight >= el.clientHeight;
                    });
                    if (!area) return [];
                    let blocks = Array.from(area.querySelectorAll('.mM66nPpS'));
                    if (!blocks.length) {
                        blocks = Array.from(area.children).filter(el => {
                            const r = el.getBoundingClientRect();
                            const text = (el.innerText || '').trim();
                            return text && r.height >= 20 && r.height <= 240;
                        });
                    }
                    const areaRect = area.getBoundingClientRect();
                    return blocks.map((block, index) => {
                        const blockRect = block.getBoundingClientRect();
                        const time = (block.querySelector('.mA74174G')?.textContent || '').trim();
                        const textNode = block.querySelector('.G3hOMUUp') || block.querySelector('.J3X6BOUb') || block;
                        const text = (textNode.textContent || '').replace('撤回', '').trim();
                        const mine = blockRect.left + blockRect.width / 2 > areaRect.left + areaRect.width / 2;
                        return {text, time, mine, index};
                    }).filter(item => item.text);
                }"""
            )
        )

    async def _click_send(self, page: Any) -> bool:
        return bool(
            await page.evaluate(
                """() => {
                    const direct = document.querySelector('.e2e-send-msg-btn')
                        || document.querySelector('[class*="PygT7Ced"]');
                    if (direct) {
                        direct.click();
                        return true;
                    }
                    const button = Array.from(document.querySelectorAll('button, [role="button"], div')).find(el => {
                        const rect = el.getBoundingClientRect();
                        const cls = String(el.className || '').toLowerCase();
                        return rect.width >= 20 && rect.width <= 60 && rect.height >= 20 && rect.height <= 60
                            && rect.left > window.innerWidth * 0.65 && rect.top > window.innerHeight * 0.5
                            && (cls.includes('send') || (el.textContent || '').trim() === '发送');
                    });
                    if (!button) return false;
                    button.click();
                    return true;
                }"""
            )
        )
