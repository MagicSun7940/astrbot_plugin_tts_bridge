# astrbot_plugin_tts_bridge

AstrBot 插件：多语言文字 + 语音桥接

将 AI 的文字回复翻译为目标语言后进行 TTS 语音合成，实现**文字和语音使用不同语言**的效果。翻译供应商和 TTS 供应商均支持扩展。

**典型使用场景：** AI 用中文回复，同时附带日语语音（适合日语角色扮演）。

---

## 更新日志

### v1.2.0
- `/ttsb` 不带子命令时直接显示帮助界面（与 `/ttsb help` 效果相同）

### v1.1.0
- 指令重构：原 `/ttsbridge` 系列指令改为 `/ttsb on`、`/ttsb off`、`/ttsb help`
- 新增指令组 `ttsb`，在 AstrBot 行为管理中统一归属 `tts_bridge` 文件夹显示
- 新增 `debug_mode` 调试模式配置项
- 新增 `filter_regex` 过滤规则配置项，过滤规则完全可配置

### v1.0.0
- 初始版本
- 支持中文回复 + 日语 TTS 语音
- 翻译供应商：OpenAI 兼容格式（硅基流动、DeepSeek、OpenAI 等）
- TTS 供应商：MiniMax
- 策略模式设计，支持多供应商扩展

---

## 工作原理

1. 拦截 AI 的文字回复
2. 按配置的正则过滤掉不需要朗读的内容（如括号内的动作描写）
3. 调用翻译 API 将文本翻译为目标语言（可关闭，直接对原文 TTS）
4. 调用 TTS API 合成语音
5. 语音和原始文字一起发送给用户

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

### 翻译供应商：硅基流动（免费，推荐）

- 注册地址：[siliconflow.cn](https://siliconflow.cn)
- 注册后创建 API Key，新用户有免费额度

也可以使用其他兼容 OpenAI 格式的 API（OpenAI、DeepSeek 等），修改对应配置项即可。

---

## 配置项说明

### 通用配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_translate` | 是否启用翻译。关闭后直接对原文进行 TTS | `true` |
| `filter_regex` | 过滤正则表达式，匹配到的内容不会被朗读。留空则不过滤 | 过滤中文括号及其中内容 |
| `debug_mode` | 调试模式，见下方说明 | `false` |

**filter_regex 示例：**
```
# 只过滤中文括号（默认）
[（(][^）)]*[）)]

# 同时过滤中英文括号和【】
[（(【][^）)】]*[）)】]

# 不过滤任何内容（留空即可）
```

### 调试模式（debug_mode）

开启后，每次 TTS 处理时会在 AstrBot 日志中输出以下信息，方便排查翻译错误或语音合成异常：

- `[DEBUG] 原始文本`：AI 回复的原始文字
- `[DEBUG] 过滤后文本`：经正则过滤后的文字（若有变化才输出）
- `[DEBUG] 翻译后文本`：翻译 API 返回的结果
- `[DEBUG] 发送给 TTS 的文本`：最终发送给语音合成的文字

日志可在 AstrBot 控制台或服务器日志文件中查看。

### 翻译配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `translate_provider` | 翻译供应商，目前支持 `openai_compat` | `openai_compat` |
| `translate_api_key` | 翻译 API Key | 空 |
| `translate_base_url` | 翻译 API 地址 | `https://api.siliconflow.cn/v1` |
| `translate_model` | 翻译使用的模型 | `Qwen/Qwen2.5-7B-Instruct` |
| `translate_prompt` | 翻译系统提示词，可自定义目标语言和风格 | 翻译成日语 |

**translate_prompt 示例：**
```
# 翻译成日语（默认）
请将以下文本翻译成日语。只输出翻译结果，不要添加任何解释或其他内容。

# 翻译成傲娇风格日语
请将以下中文文本翻译成自然的日语口语，语气要像一个傲娇的少女在说话。只输出翻译结果。

# 翻译成英语
请将以下文本翻译成英语。只输出翻译结果，不要添加任何解释或其他内容。
```

### TTS 配置（MiniMax）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `tts_provider` | TTS 供应商，目前支持 `minimax` | `minimax` |
| `minimax_api_key` | MiniMax API Key | 空 |
| `minimax_group_id` | MiniMax Group ID | 空 |
| `minimax_voice_id` | 音色 ID（克隆音色填克隆时指定的名称） | 空 |
| `minimax_model` | TTS 模型 | `speech-2.8-turbo` |

---

## 使用指令

所有指令归属于 `tts_bridge` 指令组，在 AstrBot 行为管理中统一显示。

| 指令 | 说明 |
|------|------|
| `/ttsb` | 查看帮助信息 |
| `/ttsb help` | 查看帮助信息 |
| `/ttsb on` | 开启当前会话的语音桥接 |
| `/ttsb off` | 关闭当前会话的语音桥接 |

---

## 注意事项

- 使用前请关闭 AstrBot 原生的 TTS 功能，避免冲突
- MiniMax 按字符收费（2元/万字符），日常聊天消耗极少
- 硅基流动翻译免费额度充足

---

## 扩展开发

插件采用策略模式设计，新增供应商只需在 `main.py` 中继承对应的抽象类：

```python
# 新增翻译供应商
class MyTranslateProvider(TranslateProvider):
    async def translate(self, text: str) -> str:
        # 实现翻译逻辑
        ...

# 新增 TTS 供应商
class MyTTSProvider(TTSProvider):
    async def synthesize(self, text: str) -> str:
        # 实现合成逻辑，返回音频文件路径
        ...
```

然后在 `_init_providers` 方法中注册新供应商，并在 `_conf_schema.json` 中添加对应配置项即可。
