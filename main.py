import re
import os
import json
import uuid
import asyncio
import tempfile
import httpx
from abc import ABC, abstractmethod

from astrbot.api.star import Star, register, Context, StarTools
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
import astrbot.api.message_components as Comp

MINIMAX_EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "shy", "excited", "neutral"]

_LANG_TAG_PATTERN = re.compile(
    r'[\(\[（【]\s*(?:japanese|japanese translation|日语|日文|ja|jp)\s*[\)\]）】]',
    re.IGNORECASE
)

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_REGEX_LEN = 500


# ─────────────────────────────────────────────
# 翻译供应商
# ─────────────────────────────────────────────

class TranslateProvider(ABC):
    @abstractmethod
    async def translate(self, text: str) -> str:
        pass

    async def close(self):
        pass


class OpenAICompatTranslateProvider(TranslateProvider):
    def __init__(self, api_key: str, base_url: str, model: str, prompt: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt = prompt
        self.client = httpx.AsyncClient(timeout=30)

    async def translate(self, text: str) -> str:
        resp = await self.client.post(
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
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            raise ValueError("翻译 API 返回结构异常，未找到 content 字段")
        return content.strip()

    async def close(self):
        await self.client.aclose()


# ─────────────────────────────────────────────
# 情感识别
# ─────────────────────────────────────────────

class EmotionDetector:
    def __init__(self, api_key: str, base_url: str, model: str, prompt_template: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt_template = prompt_template
        self.client = httpx.AsyncClient(timeout=20)

    async def detect(self, text: str) -> str:
        emotion_list = "、".join(MINIMAX_EMOTIONS)
        system_prompt = self.prompt_template.replace("{emotion_list}", emotion_list)
        resp = await self.client.post(
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
        resp.raise_for_status()
        data = resp.json()
        result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        result = result.strip().lower()
        return result if result in MINIMAX_EMOTIONS else "neutral"

    async def close(self):
        await self.client.aclose()


# ─────────────────────────────────────────────
# TTS 供应商
# ─────────────────────────────────────────────

class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, emotion: str = None) -> str:
        pass

    async def close(self):
        pass


class MinimaxTTSProvider(TTSProvider):
    def __init__(self, api_key: str, group_id: str, voice_id: str, model: str):
        self.api_key = api_key
        self.group_id = group_id
        self.voice_id = voice_id
        self.model = model
        self.client = httpx.AsyncClient(timeout=60)

    async def synthesize(self, text: str, emotion: str = None) -> str:
        voice_setting = {"voice_id": self.voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0}
        if emotion and emotion in MINIMAX_EMOTIONS:
            voice_setting["emotion"] = emotion

        resp = await self.client.post(
            f"https://api.minimax.chat/v1/t2a_v2?GroupId={self.group_id}",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "text": text,
                "voice_setting": voice_setting,
                "audio_setting": {"format": "mp3", "sample_rate": 32000}
            }
        )
        resp.raise_for_status()
        result = resp.json()
        base_resp = result.get("base_resp", {})
        if base_resp.get("status_code") != 0:
            raise Exception(f"MiniMax TTS 错误: {base_resp.get('status_msg')}")

        audio_hex = result.get("data", {}).get("audio")
        if not audio_hex or not isinstance(audio_hex, str):
            raise ValueError("MiniMax 返回结构异常，未找到 audio 字段")
        if len(audio_hex) > MAX_AUDIO_BYTES * 2:
            raise ValueError(f"音频数据超过最大限制 {MAX_AUDIO_BYTES} 字节")

        audio_bytes = bytes.fromhex(audio_hex)
        return _save_audio(audio_bytes, "mp3")

    async def close(self):
        await self.client.aclose()


class OpenAITTSProvider(TTSProvider):
    def __init__(self, api_key: str, base_url: str, model: str, voice: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.client = httpx.AsyncClient(timeout=60)

    async def synthesize(self, text: str, emotion: str = None) -> str:
        resp = await self.client.post(
            f"{self.base_url}/audio/speech",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "input": text,
                "voice": self.voice,
                "response_format": "mp3"
            }
        )
        resp.raise_for_status()
        if len(resp.content) > MAX_AUDIO_BYTES:
            raise ValueError(f"音频数据超过最大限制 {MAX_AUDIO_BYTES} 字节")
        return _save_audio(resp.content, "mp3")

    async def close(self):
        await self.client.aclose()


def _save_audio(data: bytes, fmt: str) -> str:
    temp_dir = tempfile.gettempdir()
    path = os.path.join(temp_dir, f"tts_bridge_{uuid.uuid4().hex}.{fmt}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _cleanup_old_audio():
    """清理临时目录中超过1小时的 tts_bridge_*.mp3 文件"""
    import time
    temp_dir = tempfile.gettempdir()
    now = time.time()
    try:
        for fname in os.listdir(temp_dir):
            if fname.startswith("tts_bridge_") and fname.endswith(".mp3"):
                fpath = os.path.join(temp_dir, fname)
                try:
                    if now - os.path.getmtime(fpath) > 3600:
                        os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        pass


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

DEFAULT_EMOTION_PROMPT = (
    "你是一个情感分析助手。请分析以下日语文本的情感，从以下选项中选择最匹配的一个：{emotion_list}。\n\n"
    "角色性格参考：该角色是傲娇萌妹，日常偏害羞和平静，只在明显情绪波动时才使用对应情感。\n\n"
    "只输出情感标签的英文名称，不要输出任何其他内容。"
)


# ─────────────────────────────────────────────
# 插件主体
# ─────────────────────────────────────────────

@register("astrbot_plugin_tts_bridge", "MagicSun7940", "多语言文字+语音桥接插件，支持翻译后TTS合成", "1.4.5")
class TtsBridgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.enabled_sessions = set()
        self._sessions_lock = asyncio.Lock()
        self.translate_provider: TranslateProvider = None
        self.tts_provider: TTSProvider = None
        self.emotion_detector: EmotionDetector = None
        self._load_sessions()
        self._init_providers()

    def _get_sessions_path(self) -> str:
        data_dir = StarTools.get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / "tts_bridge_sessions.json")

    def _load_sessions(self):
        path = self._get_sessions_path()
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    self.enabled_sessions = set(json.load(f))
        except Exception as e:
            logger.warning(f"[TTS_BRIDGE] 加载会话状态失败: {e}")
            self.enabled_sessions = set()

    async def _save_sessions(self):
        async with self._sessions_lock:
            path = self._get_sessions_path()
            try:
                with open(path, "w") as f:
                    json.dump(list(self.enabled_sessions), f)
            except Exception as e:
                logger.warning(f"[TTS_BRIDGE] 保存会话状态失败: {e}")

    async def _close_providers(self):
        for provider in [self.translate_provider, self.tts_provider, self.emotion_detector]:
            if provider:
                try:
                    await provider.close()
                except Exception as e:
                    logger.warning(f"[TTS_BRIDGE] 关闭 provider 失败: {e}")

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
        elif tp2 == "openai_tts":
            self.tts_provider = OpenAITTSProvider(
                api_key=self.config.get("openai_tts_api_key", ""),
                base_url=self.config.get("openai_tts_base_url", "https://api.openai.com/v1"),
                model=self.config.get("openai_tts_model", "gpt-4o-mini-tts"),
                voice=self.config.get("openai_tts_voice", "alloy")
            )

        if tp2 == "minimax" and self.config.get("enable_emotion", True):
            self.emotion_detector = EmotionDetector(
                api_key=self.config.get("translate_api_key", ""),
                base_url=self.config.get("translate_base_url", "https://api.siliconflow.cn/v1"),
                model=self.config.get("emotion_model", "Qwen/Qwen2.5-7B-Instruct"),
                prompt_template=self.config.get("emotion_prompt", DEFAULT_EMOTION_PROMPT)
            )
        else:
            self.emotion_detector = None

    async def terminate(self):
        await self._close_providers()

    @filter.command_group("ttsb", alias=set(), desc="tts_bridge 插件")
    async def ttsb_group(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @ttsb_group.command("help", desc="查看所有指令及其作用")
    async def help_tts(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @ttsb_group.command("on", desc="开启当前会话的语音桥接")
    async def enable_tts(self, event: AstrMessageEvent):
        # 配置校验
        tp2 = self.config.get("tts_provider", "minimax")
        if tp2 == "minimax":
            if not self.config.get("minimax_api_key") or not self.config.get("minimax_group_id") or not self.config.get("minimax_voice_id"):
                yield event.plain_result("❌ MiniMax 配置不完整，请检查 minimax_api_key、minimax_group_id、minimax_voice_id")
                return
        elif tp2 == "openai_tts":
            if not self.config.get("openai_tts_api_key"):
                yield event.plain_result("❌ OpenAI TTS 配置不完整，请检查 openai_tts_api_key")
                return

        if self.config.get("enable_translate", True) and not self.config.get("translate_api_key"):
            yield event.plain_result("❌ 翻译功能已启用但未配置 translate_api_key")
            return

        # 仅更新会话状态，不重建全局 provider，避免中断其他正在进行的请求
        async with self._sessions_lock:
            self.enabled_sessions.add(event.unified_msg_origin)
        await self._save_sessions()
        yield event.plain_result("✅ 语音桥接已开启。发送 /ttsb off 可关闭。")

    @ttsb_group.command("off", desc="关闭当前会话的语音桥接")
    async def disable_tts(self, event: AstrMessageEvent):
        async with self._sessions_lock:
            self.enabled_sessions.discard(event.unified_msg_origin)
        await self._save_sessions()
        yield event.plain_result("🔇 语音桥接已关闭。")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        if event.unified_msg_origin not in self.enabled_sessions:
            return

        text = "".join(comp.text for comp in resp.result_chain.chain if hasattr(comp, "text"))
        if not text:
            return

        filter_regex = self.config.get("filter_regex", r'[（(][^）)]*[）)]')
        if filter_regex:
            if len(filter_regex) > MAX_REGEX_LEN:
                logger.warning(f"[TTS_BRIDGE] filter_regex 超过最大长度 {MAX_REGEX_LEN}，已跳过过滤")
            else:
                try:
                    text = re.sub(filter_regex, '', text).strip()
                except re.error as e:
                    logger.warning(f"[TTS_BRIDGE] 过滤正则有误: {e}，已跳过")

        if not text:
            return

        # 每次处理时顺带清理过期临时文件
        _cleanup_old_audio()

        try:
            if self.config.get("enable_translate", True) and self.translate_provider:
                translated = await self.translate_provider.translate(text)
                translated = _LANG_TAG_PATTERN.sub('', translated).strip()
                if not translated:
                    return
                text = translated

            emotion = None
            if self.emotion_detector:
                try:
                    emotion = await self.emotion_detector.detect(text)
                except Exception as e:
                    logger.warning(f"[TTS_BRIDGE] 情感识别失败，降级为 neutral: {e}")
                    emotion = "neutral"

            if not self.tts_provider:
                return

            audio_path = await self.tts_provider.synthesize(text, emotion=emotion)
            if not audio_path:
                return

            resp.result_chain.chain.insert(0, Comp.Record(file=audio_path))

        except Exception as e:
            logger.error(f"[TTS_BRIDGE] 失败: {e}")
