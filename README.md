# astrbot_plugin_tts_bridge

AstrBot 插件：多语言文字 + 语音桥接

将 AI 的文字回复翻译为目标语言后进行 TTS 语音合成，实现**文字和语音使用不同语言**的效果。

**典型使用场景：** AI 用中文回复，同时附带带情感的日语语音（适合日语角色扮演）。

---

## 更新日志

### v1.4.0
- 新增 OpenAI TTS 供应商，支持 `gpt-4o-mini-tts`、`tts-1`、`tts-1-hd` 等模型，兼容所有 OpenAI 格式的 TTS 接口
- 移除 debug 模式配置项，精简插件配置页面
- 配置项描述精简，移除多余的推荐说明文字
- 情感识别现在仅在 `tts_provider` 为 `minimax` 时生效，切换到其他供应商时自动禁用

### v1.3.5
- 修复 debug 日志无法输出的问题（已在 v1.4.0 随 debug 模式一起移除）

### v1.3.4
- 修复情感标签被朗读出来的根本问题：情感由文本内嵌 `[emotion=xxx]` 改为通过 MiniMax API 的 `voice_setting.emotion` 参数传入

### v1.3.3
- 配置项描述精简，左侧标签文字不再截断
- `filter_regex`、`emotion_prompt`、`translate_prompt` 改为大文本框显示

### v1.3.2
- 新增 `emotion_prompt` 配置项，可自定义情感识别提示词及角色性格倾向
- `{emotion_list}` 占位符自动替换为支持的情感列表
- `translate_prompt` 输入框改为多行大文本框

### v1.3.1
- `translate_prompt` 默认值改为多行萌妹风格提示词

### v1.3.0
- 新增自动情感识别，翻译完成后自动分析情感并通过 API 参数控制语音语气
- 新增语言标注自动清洗，过滤翻译结果中的 `(Japanese)` 等标注
- 新增 `filter_regex` 常用预设规则（英文括号、方括号、标签、Markdown 符号）
- 翻译模型默认值改为 `deepseek-ai/DeepSeek-V3`

### v1.2.0
- `/ttsb` 不带子命令时直接显示帮助界面

### v1.1.0
- 指令重构为 `/ttsb on`、`/ttsb off`、`/ttsb help`
- 新增指令组，在 AstrBot 行为管理中统一归属 `tts_bridge` 文件夹
- 新增 `filter_regex` 过滤规则配置项

### v1.0.0
- 初始版本，支持 MiniMax TTS + OpenAI 兼容翻译

---

## 工作原理

1. 拦截 AI 的文字回复
2. 按配置的正则过滤不需要朗读的内容
3. 调用翻译 API 将文本翻译为目标语言（可关闭）
4. 自动清洗翻译结果中可能附带的语言标注
5. 调用情感识别分析文本情感（仅 MiniMax 支持）
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

---

## 配置项说明

### 通用

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_translate` | 启用翻译 | `true` |
| `filter_regex` | TTS 前过滤正则，多规则用 `\|` 连接 | 过滤括号/标签/Markdown |

### 情感识别（仅 MiniMax）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_emotion` | 启用情感识别 | `true` |
| `emotion_model` | 情感识别模型 | `Qwen/Qwen2.5-7B-Instruct` |
| `emotion_prompt` | 情感识别提示词，`{emotion_list}` 自动替换 | 傲娇萌妹性格描述 |

支持的情感：`happy` / `sad` / `angry` / `fearful` / `disgusted` / `surprised` / `shy` / `excited` / `neutral`

### 翻译配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `translate_provider` | 供应商，支持 `openai_compat` | `openai_compat` |
| `translate_api_key` | API Key（情感识别同用） | 空 |
| `translate_base_url` | Base URL | `https://api.siliconflow.cn/v1` |
| `translate_model` | 翻译模型 | `deepseek-ai/DeepSeek-V3` |
| `translate_prompt` | 翻译提示词 | 日系萌妹风格 |

### TTS 配置

`tts_provider` 填 `minimax` 或 `openai_tts`。

**MiniMax：**

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `minimax_api_key` | API Key | 空 |
| `minimax_group_id` | Group ID | 空 |
| `minimax_voice_id` | 音色 ID | 空 |
| `minimax_model` | 模型 | `speech-2.8-turbo` |

**OpenAI TTS：**

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `openai_tts_api_key` | API Key | 空 |
| `openai_tts_base_url` | Base URL | `https://api.openai.com/v1` |
| `openai_tts_model` | 模型（tts-1 / tts-1-hd / gpt-4o-mini-tts） | `gpt-4o-mini-tts` |
| `openai_tts_voice` | 音色（alloy / echo / fable / onyx / nova / shimmer） | `alloy` |

---

## 使用指令

| 指令 | 说明 |
|------|------|
| `/ttsb` 或 `/ttsb help` | 查看帮助 |
| `/ttsb on` | 开启语音桥接 |
| `/ttsb off` | 关闭语音桥接 |

---

## 扩展开发

```python
class MyTTSProvider(TTSProvider):
    async def synthesize(self, text: str, emotion: str = None) -> str:
        # 实现合成逻辑，返回音频文件路径
        ...
```

在 `_init_providers` 中注册，`_conf_schema.json` 中添加配置项即可。
