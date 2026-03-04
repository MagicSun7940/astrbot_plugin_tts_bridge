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


# ─────────────────────────────────────────────
# 翻译供应商抽象接口
# ─────────────────────────────────────────────

class TranslateProvider(ABC):
    @abstractmethod
    async def translate(self, text: str) -> str:
        pass


class OpenAICompatTranslateProvider(TranslateProvider):
    """兼容 OpenAI 格式的翻译供应商（硅基流动、OpenAI、DeepSeek 等）"""
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
# TTS 供应商抽象接口
# ─────────────────────────────────────────────

class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> str:
        """合成语音，返回音频文件路径"""
        pass


class MinimaxTTSProvider(TTSProvider):
    """MiniMax TTS 供应商"""
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
# 插件主体
# ─────────────────────────────────────────────

@register("astrbot_plugin_tts_bridge", "magic-sun", "多语言文字+语音桥接插件，支持翻译后TTS合成", "1.0.0")
class TtsBridgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.enabled_sessions = set()
        self.translate_provider: TranslateProvider = None
        self.tts_provider: TTSProvider = None
        self._init_providers()

    def _init_providers(self):
        # 初始化翻译供应商
        tp = self.config.get("translate_provider", "openai_compat")
        if tp == "openai_compat":
            self.translate_provider = OpenAICompatTranslateProvider(
                api_key=self.config.get("translate_api_key", ""),
                base_url=self.config.get("translate_base_url", "https://api.siliconflow.cn/v1"),
                model=self.config.get("translate_model", "Qwen/Qwen2.5-7B-Instruct"),
                prompt=self.config.get("translate_prompt", "请将以下文本翻译成日语。只输出翻译结果，不要添加任何解释或其他内容。")
            )

        # 初始化TTS供应商
        tp2 = self.config.get("tts_provider", "minimax")
        if tp2 == "minimax":
            self.tts_provider = MinimaxTTSProvider(
                api_key=self.config.get("minimax_api_key", ""),
                group_id=self.config.get("minimax_group_id", ""),
                voice_id=self.config.get("minimax_voice_id", ""),
                model=self.config.get("minimax_model", "speech-2.8-turbo")
            )

    @filter.command("ttsbridge")
    async def enable_tts(self, event: AstrMessageEvent):
        """开启语音桥接：/ttsbridge"""
        self._init_providers()  # 每次开启时重新加载配置
        self.enabled_sessions.add(event.unified_msg_origin)
        yield event.plain_result("✅ 语音桥接已开启。关闭请发 /ttsbridge_off")

    @filter.command("ttsbridge_off")
    async def disable_tts(self, event: AstrMessageEvent):
        """关闭语音桥接：/ttsbridge_off"""
        self.enabled_sessions.discard(event.unified_msg_origin)
        yield event.plain_result("🔇 语音桥接已关闭。")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        if event.unified_msg_origin not in self.enabled_sessions:
            return

        # 提取文本
        text = ""
        for comp in resp.result_chain.chain:
            if hasattr(comp, "text"):
                text += comp.text
        if not text:
            return

        # 按配置的正则过滤内容
        filter_regex = self.config.get("filter_regex", r'[（(][^）)]*[）)]')
        if filter_regex:
            try:
                text = re.sub(filter_regex, '', text).strip()
            except re.error as e:
                logger.warning(f"过滤正则表达式有误: {e}，已跳过过滤")

        if not text:
            return

        try:
            # 翻译
            if self.config.get("enable_translate", True) and self.translate_provider:
                text = await self.translate_provider.translate(text)
                if not text:
                    return

            # TTS 合成
            if not self.tts_provider:
                logger.error("TTS 供应商未初始化，请检查配置")
                return
            audio_path = await self.tts_provider.synthesize(text)
            if not audio_path:
                return

            resp.result_chain.chain.insert(0, Comp.Record(file=audio_path))

        except Exception as e:
            logger.error(f"TTS Bridge 失败: {e}")
