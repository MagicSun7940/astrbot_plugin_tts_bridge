# astrbot_plugin_tts_bridge

AstrBot 插件：多语言文字 + 语音桥接

将 AI 的文字回复翻译为目标语言后进行 TTS 语音合成，实现**文字和语音使用不同语言**的效果。支持自动情感识别，使语音语气更贴合语境。

**典型使用场景：** AI 用中文回复，同时附带带情感的日语语音（适合日语角色扮演）。

---

## 更新日志

### v1.3.2
- 新增 `emotion_prompt` 配置项，可自定义情感识别提示词，支持描述角色性格倾向引导情感选择
- `{emotion_list}` 占位符会自动替换为支持的情感列表
- `translate_prompt` 输入框现在显示为多行大文本框，方便编辑长提示词

### v1.3.1
- `translate_prompt` 默认值改为多行萌妹风格提示词，配置页输入框自动显示为大文本框，方便编辑
- 翻译提示词默认风格：日系二次元萌妹对哥哥撒娇，以「お兄ちゃん」称呼哥哥

### v1.3.0
- 新增自动情感识别功能：翻译完成后自动分析文本情感，在发给 TTS 的文本前插入 `[emotion=xxx]` 标签，使语音语气更符合语境（害羞时害羞、开心时开心）
- 支持的情感：`happy`、`sad`、`angry`、`fearful`、`disgusted`、`surprised`、`shy`、`excited`、`neutral`
- 情感识别复用翻译 API 的 Key 和 Base URL，可单独配置使用的模型（推荐轻量模型减少延迟）
- 新增 `filter_regex` 常用预设规则说明（英文括号、【】、标签、Markdown 符号）
- 修复语音中插入语言标注的问题，翻译结果发送前自动清洗
- 修复 debug 模式日志无输出问题，debug 输出新增情感识别结果一项
- 翻译模型默认值改为 `deepseek-ai/DeepSeek-V3`

### v1.2.0
- `/ttsb` 不带子命令时直接显示帮助界面（与 `/ttsb help` 效果相同）

### v1.1.0
- 指令重构：改为 `/ttsb on`、`/ttsb off`、`/ttsb help`
- 新增指令组，在 AstrBot 行为管理中统一归属 `tts_bridge` 文件夹显示
- 新增 `debug_mode` 调试模式配置项
- 新增 `filter_regex` 过滤规则配置项

### v1.0.0
- 初始版本
- 翻译供应商：OpenAI 兼容格式（硅基流动、DeepSeek、OpenAI 等）
- TTS 供应商：MiniMax
- 策略模式设计，支持多供应商扩展

---

## 工作原理

1. 拦截 AI 的文字回复
2. 按配置的正则过滤不需要朗读的内容（如括号内的动作描写）
3. 调用翻译 API 将文本翻译为目标语言（可关闭）
4. 自动清洗翻译结果中可能附带的语言标注
5. 调用情感识别 API 分析文本情感，插入 `[emotion=xxx]` 标签（可关闭）
6. 调用 TTS API 合成语音
7. 语音和原始文字一起发送给用户

---

## 安装方法

**方式一：插件市场安装（推荐）**

在 AstrBot 插件市场搜索 `astrbot_plugin_tts_bridge` 直接安装。

**方式二：手动安装**

将插件文件夹放入 AstrBot 插件目录：

```
AstrBot/data/plugins/astrbot_plugin_tts_bridge/
```

重启或在控制台重载插件。

---

## 前置准备

### TTS 供应商：MiniMax

- 注册地址：[minimaxi.com](https://minimaxi.com)
- 获取 **API Key** 和 **Group ID**（账户管理 → 基本信息）
- 如需克隆自定义音色，参考 MiniMax 声音克隆文档

### 翻译 + 情感识别供应商：硅基流动（免费，推荐）

- 注册地址：[siliconflow.cn](https://siliconflow.cn)
- 注册后创建 API Key，新用户有免费额度
- 翻译推荐模型：`deepseek-ai/DeepSeek-V3`
- 情感识别推荐模型：`Qwen/Qwen2.5-7B-Instruct`（轻量快速）

---

## 配置项说明

### 通用配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_translate` | 是否启用翻译。关闭后直接对原文 TTS | `true` |
| `filter_regex` | 过滤正则表达式，见下方说明 | 过滤中文圆括号内容 |
| `debug_mode` | 调试模式，见下方说明 | `false` |

### filter_regex 过滤规则

多个规则用 `|` 连接组合使用。

| 过滤目标 | 正则表达式 |
|----------|-----------|
| 中文圆括号内容（默认） | `[（(][^）)]*[）)]` |
| 英文括号内容 | `\([^)]*\)` |
| 方括号内容 | `【[^】]*】` |
| XML/HTML 标签 | `<[^>]+>` |
| Markdown 粗体/斜体符号 | `\*{1,3}\|_{1,3}` |

全能组合版：
```
[（(][^）)]*[）)]|\([^)]*\)|【[^】]*】|<[^>]+>|\*{1,3}|_{1,3}
```

### 情感识别配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_emotion` | 是否启用情感识别 | `true` |
| `emotion_model` | 情感识别模型，复用翻译 API 的 Key 和 Base URL | `Qwen/Qwen2.5-7B-Instruct` |

支持的情感标签：

| 标签 | 含义 |
|------|------|
| `happy` | 开心 |
| `sad` | 悲伤 |
| `angry` | 生气 |
| `fearful` | 害怕 |
| `disgusted` | 厌恶 |
| `surprised` | 惊讶 |
| `shy` | 害羞 |
| `excited` | 兴奋 |
| `neutral` | 平静（默认降级） |

### 调试模式（debug_mode）

开启后以 `[TTS_BRIDGE DEBUG]` 为前缀输出：

| 输出项 | 说明 |
|--------|------|
| `原始文本` | AI 回复的原始文字 |
| `过滤后文本` | 经正则过滤后的文字（有变化才输出） |
| `翻译后原始返回` | 翻译 API 返回的原始结果 |
| `翻译后清洗文本` | 去除语言标注后的结果 |
| `识别情感` | 情感识别结果 |
| `发送给 TTS 的文本` | 最终发送给语音合成的文字（含情感标签） |

### 翻译配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `translate_provider` | 翻译供应商，目前支持 `openai_compat` | `openai_compat` |
| `translate_api_key` | 翻译 API Key（情感识别也使用此 Key） | 空 |
| `translate_base_url` | 翻译 API 地址 | `https://api.siliconflow.cn/v1` |
| `translate_model` | 翻译模型 | `deepseek-ai/DeepSeek-V3` |
| `translate_prompt` | 翻译系统提示词 | 翻译成日语 |

**推荐提示词（日系萌妹对哥哥撒娇风格）：**
```
你是一个日系二次元萌妹，正在把中文台词翻译成你说话的日语风格。

翻译要求：
- 用第一人称「私」或「あたし」
- 称呼哥哥为「お兄ちゃん」
- 语气要撒娇、可爱、带点小傲娇
- 句尾可以适当加「～」「の」「よ」「ね」「もん」等语气词
- 只输出翻译后的日语文本，不要输出任何解释、标注、括号说明或其他多余内容
- 绝对不要输出英文单词或语言标注
```

### TTS 配置（MiniMax）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `tts_provider` | TTS 供应商，目前支持 `minimax` | `minimax` |
| `minimax_api_key` | MiniMax API Key | 空 |
| `minimax_group_id` | MiniMax Group ID | 空 |
| `minimax_voice_id` | 音色 ID | 空 |
| `minimax_model` | TTS 模型 | `speech-2.8-turbo` |

---

## 使用指令

| 指令 | 说明 |
|------|------|
| `/ttsb` | 查看帮助信息 |
| `/ttsb help` | 查看帮助信息 |
| `/ttsb on` | 开启当前会话的语音桥接 |
| `/ttsb off` | 关闭当前会话的语音桥接 |

---

## 注意事项

- 使用前请关闭 AstrBot 原生的 TTS 功能，避免冲突
- 情感识别会额外消耗一次 API 调用，推荐使用轻量模型（7B）以减少延迟
- MiniMax 按字符收费（2元/万字符）

---

## 扩展开发

```python
class MyTranslateProvider(TranslateProvider):
    async def translate(self, text: str) -> str:
        ...

class MyTTSProvider(TTSProvider):
    async def synthesize(self, text: str) -> str:
        ...
```

在 `_init_providers` 中注册，`_conf_schema.json` 中添加配置项即可。
