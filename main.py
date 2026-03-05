import re
import os
import uuid
import httpx
import logging
from abc import ABC, abstractmethod

from astrbot.api.star import Star, register, Context
from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
import astrbot.api.message_components as Comp

logger = logging.getLogger("astrbot_plugin_tts_bridge")

# 过滤翻译API可能附加的语言标注
_LANG_TAG_PATTERN = re.compile(
    r'[\(\[（【]\s*(?:japanese|japanese translation|日语|日文|ja|jp)\s*[\)\]）】]',
    re.IGNORECASE
)

# MiniMax 支持的情感列表
MINIMAX_EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "shy", "excited", "neutral"]


# ─────────────────────────────────────────────
# 翻译供应商抽象接口
# ─────────────────────────────────────────────

class TranslateProvider(ABC):
    @abstractmethod
    async def translate(self, text: str) -> str:
        pass


class OpenAICompatTranslateProvider(TranslateProvider):
    def __init__(self, api_key: str, base_url: str, model: str, prompt: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt = prompt

    async def translate(self, text: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self.prompt},
                        {"role": "user", "content": text}
                    ],
                    "max_tokens": 500
                }
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()


# ─────────────────────────────────────────────
# 情感识别器
# ─────────────────────────────────────────────

class EmotionDetector:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def detect(self, text: str) -> str:
        """分析文本情感，返回 MiniMax 情感标签名"""
        emotion_list = "、".join(MINIMAX_EMOTIONS)
        system_prompt = (
            f"你是一个情感分析助手。请分析以下日语文本的情感，从以下选项中选择最匹配的一个：{emotion_list}。\n"
            "只输出情感标签的英文名称，不要输出任何其他内容。"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    "max_tokens": 20
                }
            )
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip().lower()
            # 确保返回值在合法列表内，否则降级为 neutral
            return result if result in MINIMAX_EMOTIONS else "neutral"


# ─────────────────────────────────────────────
# TTS 供应商抽象接口
# ─────────────────────────────────────────────

class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> str:
        pass


class MinimaxTTSProvider(TTSProvider):
    def __init__(self, api_key: str, group_id: str, voice_id: str, model: str):
        self.api_key = api_key
        self.group_id = group_id
        self.voice_id = voice_id
        self.model = model

    async def synthesize(self, text: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.minimax.chat/v1/t2a_v2?GroupId={self.group_id}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "text": text,
                    "voice_setting": {"voice_id": self.voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
                    "audio_setting": {"format": "mp3", "sample_rate": 32000}
                }
            )
            result = resp.json()
            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise Exception(f"MiniMax TTS 错误: {base_resp.get('status_msg')}")
            audio_hex = result["data"]["audio"]
            audio_bytes = bytes.fromhex(audio_hex)
            os.makedirs("/AstrBot/data/temp", exist_ok=True)
            path = f"/AstrBot/data/temp/tts_bridge_{uuid.uuid4().hex}.mp3"
            with open(path, "wb") as f:
                f.write(audio_bytes)
            return path


# ─────────────────────────────────────────────
# 帮助文本
# ─────────────────────────────────────────────

HELP_TEXT = (
    "📖 tts_bridge 插件指令列表\n"
    "─────────────────\n"
    "/ttsb          查看此帮助信息\n"
    "/ttsb help     查看此帮助信息\n"
    "/ttsb on       开启当前会话的语音桥接\n"
    "/ttsb off      关闭当前会话的语音桥接\n"
    "─────────────────\n"
    "功能说明：将 AI 文字回复翻译为目标语言后进行 TTS 语音合成，"
    "实现文字与语音使用不同语言的效果。"
)


# ─────────────────────────────────────────────
# 插件主体
# ─────────────────────────────────────────────

@register("astrbot_plugin_tts_bridge", "magic-sun", "多语言文字+语音桥接插件，支持翻译后TTS合成", "1.3.0")
class TtsBridgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.enabled_sessions = set()
        self.translate_provider: TranslateProvider = None
        self.tts_provider: TTSProvider = None
        self.emotion_detector: EmotionDetector = None
        self._init_providers()

    def _init_providers(self):
        tp = self.config.get("translate_provider", "openai_compat")
        if tp == "openai_compat":
            self.translate_provider = OpenAICompatTranslateProvider(
                api_key=self.config.get("translate_api_key", ""),
                base_url=self.config.get("translate_base_url", "https://api.siliconflow.cn/v1"),
                model=self.config.get("translate_model", "deepseek-ai/DeepSeek-V3"),
                prompt=self.config.get("translate_prompt", "请将以下文本翻译成日语。只输出翻译结果，不要添加任何解释或其他内容。")
            )

        tp2 = self.config.get("tts_provider", "minimax")
        if tp2 == "minimax":
            self.tts_provider = MinimaxTTSProvider(
                api_key=self.config.get("minimax_api_key", ""),
                group_id=self.config.get("minimax_group_id", ""),
                voice_id=self.config.get("minimax_voice_id", ""),
                model=self.config.get("minimax_model", "speech-2.8-turbo")
            )

        # 情感识别器：复用翻译API的配置
        if self.config.get("enable_emotion", True):
            self.emotion_detector = EmotionDetector(
                api_key=self.config.get("translate_api_key", ""),
                base_url=self.config.get("translate_base_url", "https://api.siliconflow.cn/v1"),
                model=self.config.get("emotion_model", "deepseek-ai/DeepSeek-V3")
            )

    def _debug(self, msg: str):
        if self.config.get("debug_mode", False):
            logger.warning(f"[TTS_BRIDGE DEBUG] {msg}")

    @filter.command_group("ttsb", alias=set(), desc="tts_bridge 插件")
    async def ttsb_group(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @ttsb_group.command("help", desc="查看所有指令及其作用")
    async def help_tts(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @ttsb_group.command("on", desc="开启当前会话的语音桥接")
    async def enable_tts(self, event: AstrMessageEvent):
        self._init_providers()
        self.enabled_sessions.add(event.unified_msg_origin)
        yield event.plain_result("✅ 语音桥接已开启。发送 /ttsb off 可关闭。")

    @ttsb_group.command("off", desc="关闭当前会话的语音桥接")
    async def disable_tts(self, event: AstrMessageEvent):
        self.enabled_sessions.discard(event.unified_msg_origin)
        yield event.plain_result("🔇 语音桥接已关闭。")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        if event.unified_msg_origin not in self.enabled_sessions:
            return

        text = ""
        for comp in resp.result_chain.chain:
            if hasattr(comp, "text"):
                text += comp.text
        if not text:
            return

        self._debug(f"原始文本: {text}")

        # 正则过滤
        filter_regex = self.config.get("filter_regex", r'[（(][^）)]*[）)]')
        if filter_regex:
            try:
                filtered = re.sub(filter_regex, '', text).strip()
                if filtered != text:
                    self._debug(f"过滤后文本: {filtered}")
                text = filtered
            except re.error as e:
                logger.warning(f"[TTS_BRIDGE] 过滤正则有误: {e}，已跳过")

        if not text:
            return

        try:
            # 翻译
            if self.config.get("enable_translate", True) and self.translate_provider:
                translated = await self.translate_provider.translate(text)
                self._debug(f"翻译后原始返回: {translated}")
                translated = _LANG_TAG_PATTERN.sub('', translated).strip()
                self._debug(f"翻译后清洗文本: {translated}")
                if not translated:
                    return
                text = translated

            # 情感识别
            if self.config.get("enable_emotion", True) and self.emotion_detector:
                emotion = await self.emotion_detector.detect(text)
                self._debug(f"识别情感: {emotion}")
                text = f"[emotion={emotion}]{text}"
                self._debug(f"发送给 TTS 的文本: {text}")
            else:
                self._debug(f"发送给 TTS 的文本: {text}")

            if not self.tts_provider:
                logger.warning("[TTS_BRIDGE] TTS 供应商未初始化，请检查配置")
                return
            audio_path = await self.tts_provider.synthesize(text)
            if not audio_path:
                return

            resp.result_chain.chain.insert(0, Comp.Record(file=audio_path))

        except Exception as e:
            logger.warning(f"[TTS_BRIDGE] 失败: {e}")
