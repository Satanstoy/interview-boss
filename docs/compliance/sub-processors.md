# 子处理器清单（Sub-processors）

> 最后更新：2026-08-15

本文档列出本服务实际使用的第三方（子处理器）及其处理的数据、使用场景、所在地区。**清单基于后端代码实际配置查证**（backend/app/services/ 与 deploy/），不包含未在代码中出现的虚构供应商。

多数第三方按**用户/运营者个人配置**启用：未配置对应 API Key 时，相应功能不可用且数据不会被送出。

## 1. LLM 模型服务商（OpenAI 兼容 / Anthropic / MiMo 等）

| 项 | 内容 |
|------|------|
| 供应商 | 不固定（自选）：任何 OpenAI 兼容端点 / Anthropic / 小美 MiMo（xiaomimimo）等，按用户设置的 base_url，见 services/llm.py 的 `_PROVIDER_CAPABILITIES` |
| 处理的数据 | 你的提示词、JD/面经文本、聊天上下文、简历摘要、聚类/抽题请求、生成答案与对话 |
| 使用场景 | 答案生成、聚类去重、模拟面试、题目分类、标题生成、管理助手 |
| 数据流向 | 云端 API；发送到你所选的模型服务商所在地区 |
| 配置存储 | 用户 API Key 存于 user_llm_config 表，不落日志 |

## 2. SiliconFlow（Embedding 向量化）

| 项 | 内容 |
|------|------|
| 供应商 | SiliconFlow（`https://api.siliconflow.cn/v1`），模型 `BAAI/bge-m3`（1024 维），见 embedding_service.py |
| 处理的数据 | 题目/面经文本片段，用于生成语义向量 |
| 使用场景 | 题库检索预筛选、聚类候选排序 |
| 数据流向 | 云端 API（SiliconFlow 数据中心） |
| 备注 | embedding 双后端之一：默认 siliconflow；亦可切回本地 ONNX（Xenova/bge-small-zh-v1.5，本地离线） |

## 3. Deepgram（语音转写）

| 项 | 内容 |
|------|------|
| 供应商 | Deepgram，模型 `nova-3`，见 deepgram_service.py |
| 处理的数据 | 你上传的音频文件内容，返回转写文本 |
| 使用场景 | 音频面试/练习转写 |
| 数据流向 | 云端 API（Deepgram 数据中心） |
| 配置 | 需设置 DEEPGRAM_API_KEY |

## 4. 联网搜索服务商（答案增强，需显式开启）

| 供应商 | 用途 | 数据 |
|------|------|------|
| Tavily（`api.tavily.com`） | AI Agent 实时搜索 | 查询关键词 |
| Brave Search（`api.search.brave.com`） | 通用搜索 | 查询关键词 |
| 博查 Bocha（`api.bochaai.com`） | 中文搜索 | 查询关键词 |
| Exa（`api.exa.ai`） | 语义检索 | 查询关键词 |

见 services/search_service.py 的 `SUPPORTED_SEARCH_PROVIDERS`。仅在你的搜索配置显式启用了对应 provider 时才会把查询发给该服务，用于答案生成时增强。

## 5. SMTP 邮件服务商（邮箱验证）

| 项 | 内容 |
|------|------|
| 供应商 | 运营者自行配置的 SMTP（如任何邮箱服务商的 SMTP），见 email_service.py |
| 处理的数据 | 收件人邮箱、验证码、密码重置邮件（不含业务正文） |
| 使用场景 | 邮箱验证码登录/注册/改密、密码重置 |
| 数据流向 | 由 SMTP 服务商处理；from 地址来自 SMTP_USERNAME / SMTP_FROM |

## 6. HuggingFace / ONNX 模型资源（本地缓存）

| 项 | 内容 |
|------|------|
| 供应商 | HuggingFace Hub（模型资源下载源） |
| 处理的数据 | 无业务数据；仅下载 embedding 模型权重 |
| 使用场景 | 本地 embedding（Xenova/bge-small-zh-v1.5 ONNX export） |
| 备注 | 生产环境 HF_HUB_OFFLINE=1 强制离线，模型缓存只读挂载，运行时不与 huggingface.co 通信 |

## 7. 镜像 / 构建源（仅部署阶段，不接触用户数据）

这些仅用于**构建与部署阶段**（拉取依赖镜像），绝不处理运行时的用户数据：

| 供应商 | 用途 |
|------|------|
| npmmirror（registry.npmmirror.com / .cn） | npm 前端依赖镜像 |
| 腾讯云镜像（mirrors.cloud.tencent.com） | npm、PyPI 镜像 |
| 阿里云镜像（mirrors.aliyun.com） | PyPI、APT、APK 镜像 |
| Docker Hub registry mirror | Docker 镜像加速 |

见 deploy/mirrors.sh 与 docker-compose.yml 的 NPM_MIRROR / PYPI_MIRROR / APT_MIRROR / APK_MIRROR。

## 8. 主机 / 云基础设施

| 项 | 内容 |
|------|------|
| 供应商 | 部署运营者选择的托管主机（云厂商或私有服务器） |
| 数据 | 承载全部数据库、Redis、容器与日志 |
| 地区 | 由运营者部署所在地区决定（通常为所选云厂商的可用区） |
| 说明 | 自托管场景下，所有数据均存储于你/运营者所控制的服务器 |

## 9. 说明与联系

- 本清单随代码变化更新。核对依据：`backend/app/services/{llm,embedding_service,deepgram_service,search_service,email_service}.py` 与 `deploy/mirrors.sh`、`docker-compose.yml`。
- 如你发现清单与实际配置不符，请联系本部署实例运营者纠正。
- 用户数据共享原则见《隐私政策》第 4 节。