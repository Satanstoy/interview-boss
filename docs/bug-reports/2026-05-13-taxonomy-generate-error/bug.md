# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-13
**状态:** 已确认

## 问题概述

AI智能生成功能调用失败，返回500错误。根本原因是外部LLM服务不可用。

## 根本原因分析

### BUG-001: 外部LLM服务返回500错误
- **位置:** `backend/app/services/taxonomy_suggest.py:96-108`
- **症状:** LLM API调用返回500 Internal Server Error
- **根因:** 外部LLM服务（`token-plan-cn.xiaomimimo.com`）故障
- **影响:** AI智能生成功能完全不可用
- **严重程度:** P1

### BUG-002: 错误信息不够详细
- **位置:** `backend/app/routers/profile.py:388-390`
- **症状:** 前端只显示"AI生成失败"
- **根因:** 后端捕获异常后返回通用错误信息，没有区分错误类型
- **影响:** 用户无法了解具体失败原因，无法自行解决问题
- **严重程度:** P2

## 复现步骤

1. 打开前端页面
2. 进入系统配置界面
3. 选择目标岗位
4. 点击"AI智能生成分类"按钮
5. **预期:** 显示AI生成的分类建议
6. **实际:** 显示"AI生成失败"

## 日志分析

```
May 13 15:46:12 [INFO] HTTP Request: POST https://token-plan-cn.xiaomimimo.com/v1/chat/completions "HTTP/1.1 500 Internal Server Error"
May 13 15:46:12 [INFO] Retrying request to /chat/completions in 0.399236 seconds
May 13 15:46:13 [INFO] HTTP Request: POST https://token-plan-cn.xiaomimimo.com/v1/chat/completions "HTTP/1.1 500 Internal Server Error"
May 13 15:46:13 [INFO] Retrying request to /chat/completions in 0.973535 seconds
May 13 15:46:14 [INFO] HTTP Request: POST https://token-plan-cn.xiaomimimo.com/v1/chat/completions "HTTP/1.1 500 Internal Server Error"
May 13 15:46:14 [ERROR] LLM调用失败: position=agent开发/大模型应用开发/大模型开发, error=Error code: 500 - {'timestamp': 1778658374240, 'path': '/v1/chat/completions', 'status': 500, 'error': 'Internal Server Error', 'requestId': '9e898d39-350971'}
May 13 15:46:14 [ERROR] 生成分类建议失败: Error code: 500 - {'timestamp': 1778658374240, 'path': '/v1/chat/completions', 'status': 500, 'error': 'Internal Server Error', 'requestId': '9e898d39-350971'}
May 13 15:46:14 [WARNING] POST /api/profile/taxonomy/generate → 500 (1449.2ms)
```

## 修复建议

### 针对BUG-001: 外部LLM服务不可用
1. **短期:** 等待外部服务恢复
2. **中期:** 配置备用LLM服务端点
3. **长期:** 实现本地缓存分类建议

### 针对BUG-002: 错误信息不够详细
1. 区分不同类型的错误（网络错误、LLM服务错误、解析错误）
2. 提供更详细的错误信息给用户
3. 添加重试按钮
