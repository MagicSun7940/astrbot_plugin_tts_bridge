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

_LANG_TAG_PATTERN = re.compile(
    r'[\(\[（【]\s*(?:japanese|japanese translation|日语|日文|ja|jp)\s*[\)\]）】]',
    re.IGNORECASE
)

MINIMAX_EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "shy", "excited", "neutral"]


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


class EmotionDetector:
    def __init__(self, api_key: str, base_url: str, model: str, prompt_template: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt_template = prompt_template

    async def detect(self, text: str) -> str:
        emotion_list = "、".join(MINIMAX_EMOTIONS)
        system_prompt = self.prompt_template.replace("{emotion_list}", emotion_list)
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
            return result if result in MINIMAX_EMOTIONS else "neutral"


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, emotion: str = None) -> str:
        pass


class MinimaxTTSProvider(TTSProvider):
    def __init__(self, api_key: str, group_id: str, voice_id: str, model: str):
        self.api_key = api_key
        self.group_id = group_id
        self.voice_id = voice_id
        self.model = model

    async def synthesize(self, text: str, emotion: str = None) -> str:
        voice_setting = {
            "voice_id": self.voice_id,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0
        }
        # emotion 作为 voice_setting 参数传入，而非拼入文本
        if emotion and emotion in MINIMAX_EMOTIONS:
            voice_setting["emotion"] = emotion

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.minimax.chat/v1/t2a_v2?GroupId={self.group_id}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "text": text,
                    "voice_setting": voice_setting,
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

DEFAULT_EMOTION_PROMPT = (
    "你是一个情感分析助手。请分析以下日语文本的情感，从以下选项中选择最匹配的一个：{emotion_list}。\n\n"
    "角色性格参考：该角色是傲娇萌妹，日常偏害羞和平静，只在明显情绪波动时才使用对应情感。\n\n"
    "只输出情感标签的英文名称，不要输出任何其他内容。"
)


@register("astrbot_plugin_tts_bridge", "magic-sun", "多语言文字+语音桥接插件，支持翻译后TTS合成", "1.3.4")
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

        if self.config.get("enable_emotion", True):
            self.emotion_detector = EmotionDetector(
                api_key=self.config.get("translate_api_key", ""),
                base_url=self.config.get("translate_base_url", "https://api.siliconflow.cn/v1"),
                model=self.config.get("emotion_model", "Qwen/Qwen2.5-7B-Instruct"),
                prompt_template=self.config.get("emotion_prompt", DEFAULT_EMOTION_PROMPT)
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
            if self.config.get("enable_translate", True) and self.translate_provider:
                translated = await self.translate_provider.translate(text)
                self._debug(f"翻译后原始返回: {translated}")
                translated = _LANG_TAG_PATTERN.sub('', translated).strip()
                self._debug(f"翻译后清洗文本: {translated}")
                if not translated:
                    return
                text = translated

            # 情感识别：结果作为 API 参数传入，不拼入文本
            emotion = None
            if self.config.get("enable_emotion", True) and self.emotion_detector:
                emotion = await self.emotion_detector.detect(text)
                self._debug(f"识别情感: {emotion}")

            self._debug(f"发送给 TTS 的文本: {text}，情感参数: {emotion}")

            if not self.tts_provider:
                logger.warning("[TTS_BRIDGE] TTS 供应商未初始化，请检查配置")
                return
            audio_path = await self.tts_provider.synthesize(text, emotion=emotion)
            if not audio_path:
                return

            resp.result_chain.chain.insert(0, Comp.Record(file=audio_path))

        except Exception as e:
            logger.warning(f"[TTS_BRIDGE] 失败: {e}")
