# 修复计划

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-13
**优先级:** P1

## 修复步骤

### 步骤 1: 改进错误处理，区分错误类型
**文件:** `backend/app/routers/profile.py`
**行号:** 382-390
**修改类型:** 修正

**修改前:**
```python
try:
    suggestion = await generate_taxonomy_suggestion(position, user_id=user['id'])
except ValueError as e:
    raise HTTPException(status_code=422, detail=str(e))
except TimeoutError:
    raise HTTPException(status_code=504, detail="AI生成超时，请稍后重试")
except Exception as e:
    logger.error(f"生成分类建议失败: {e}")
    raise HTTPException(status_code=500, detail="AI生成失败，请稍后重试")
```

**修改后:**
```python
try:
    suggestion = await generate_taxonomy_suggestion(position, user_id=user['id'])
except ValueError as e:
    raise HTTPException(status_code=422, detail=str(e))
except TimeoutError:
    raise HTTPException(status_code=504, detail="AI生成超时，请稍后重试")
except Exception as e:
    error_msg = str(e)
    logger.error(f"生成分类建议失败: {error_msg}")

    # 区分不同类型的错误
    if "500" in error_msg and "Internal Server Error" in error_msg:
        detail = "AI服务暂时不可用，请稍后重试"
    elif "Connection" in error_msg or "timeout" in error_msg.lower():
        detail = "网络连接失败，请检查网络后重试"
    elif "401" in error_msg or "403" in error_msg:
        detail = "AI服务认证失败，请检查API配置"
    else:
        detail = f"AI生成失败: {error_msg[:100]}"

    raise HTTPException(status_code=500, detail=detail)
```

### 步骤 2: 改进服务层错误处理
**文件:** `backend/app/services/taxonomy_suggest.py`
**行号:** 96-108
**修改类型:** 修正

**修改前:**
```python
try:
    response = await raw_llm_call(
        user_id=user_id,
        model=None,  # 使用默认模型
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
except TimeoutError:
    logger.error(f"LLM调用超时: position={position}")
    raise
except Exception as e:
    logger.error(f"LLM调用失败: position={position}, error={e}")
    raise
```

**修改后:**
```python
try:
    response = await raw_llm_call(
        user_id=user_id,
        model=None,  # 使用默认模型
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
except TimeoutError:
    logger.error(f"LLM调用超时: position={position}")
    raise
except Exception as e:
    error_msg = str(e)
    logger.error(f"LLM调用失败: position={position}, error={error_msg}")

    # 提供更详细的错误信息
    if "500" in error_msg:
        raise Exception(f"LLM服务内部错误: {error_msg}") from e
    elif "Connection" in error_msg:
        raise Exception(f"网络连接失败: {error_msg}") from e
    elif "401" in error_msg or "403" in error_msg:
        raise Exception(f"LLM服务认证失败: {error_msg}") from e
    else:
        raise
```

## 验证方法

1. **测试正常情况:** 当LLM服务正常时，应该能成功生成分类建议
2. **测试LLM服务不可用:** 当LLM服务返回500时，应该显示"AI服务暂时不可用，请稍后重试"
3. **测试网络连接失败:** 当网络连接失败时，应该显示"网络连接失败，请检查网络后重试"
4. **测试认证失败:** 当API认证失败时，应该显示"AI服务认证失败，请检查API配置"

## 回滚方案

如果修复失败，可以回滚到原始代码：
```bash
cd /root/sj/interview-boss
git checkout HEAD~1 backend/app/routers/profile.py backend/app/services/taxonomy_suggest.py
```
