# V2 端点测试数据与脚本

## 测试账号

| 字段 | 值 |
|------|-----|
| username | testuser |
| password | Test1234! |
| user_id | 1004 (自增，清理后重建会变) |

## 清理测试数据 SQL

```sql
-- 1. 删除测试用户的 question_bank 关联表数据
DELETE FROM question_sources WHERE question_bank_id IN (SELECT id FROM question_bank WHERE owner_id = 1004);
DELETE FROM question_original_item_sources WHERE original_item_id IN (SELECT id FROM question_original_items WHERE question_bank_id IN (SELECT id FROM question_bank WHERE owner_id = 1004));
DELETE FROM question_original_items WHERE question_bank_id IN (SELECT id FROM question_bank WHERE owner_id = 1004);
DELETE FROM question_position WHERE question_id IN (SELECT id FROM question_bank WHERE owner_id = 1004);

-- 2. 删除测试用户的 question_bank
DELETE FROM question_bank WHERE owner_id = 1004;

-- 3. 删除测试用户的 interview 关联的 questions_detail
DELETE FROM questions_detail WHERE url IN (SELECT url FROM interview WHERE owner_id = 1004);

-- 4. 删除测试用户的 interview
DELETE FROM interview WHERE owner_id = 1004;

-- 5. 删除测试用户的 LLM 配置
DELETE FROM user_llm_config WHERE user_id = 1004;

-- 6. 删除测试用户
DELETE FROM users WHERE id = 1004;
```

## 创建测试账号

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d '{"username":"testuser","password":"Test1234!"}'

# 如果不存在则注册：
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d '{"username":"testuser","password":"Test1234!"}'
```

## 复制 admin LLM 配置到测试用户

```sql
INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout, updated_at)
SELECT <新user_id>, api_key, base_url, model, timeout, datetime('now')
FROM user_llm_config WHERE user_id = 1;
```

## 测试用面经文本

### 1. 通义实验室面经（阿里，多轮，8+题）
```
【阿里通义实验室 大模型面经】
部门与岗位：阿里集团 - 通义实验室 - 大语言模型
一面：Qwen 的模型结构是怎么样的，相比于LLaMA，DeepSeek 有什么区别；
对于超长上下文业界一般是怎么做的；大模型的 MoE 结构相比于 Dense 结构训练的难点；
怎么缓解大模型的幻觉问题；讲一下 RLHF 的流程，PPO 和 DPO 算法；
代码：Transformer Encoder；代码：152.乘积最大子数组
二面：DeepSeek 做的好的有哪几个点，讲讲DeepSeekMoE 和MLA；
LoRA 是什么原理；DeepSpeed ZeRO-1/2/3 优化；FP16 BF16 区别；FlashAttention
三面：Qwen目前还存在哪些问题；大模型的上限在哪里
```

### 2. 百度文心一言 Agent 面经（3轮）
```
【百度文心一言团队 大模型Agent面经】
部门与岗位：百度TPG - 文心一言团队 - 大模型算法岗
一面：大模型位置编码优缺点；RLHF/PPO/DPO；超长上下文；智能体组件；场景题
二面：CV和NLP大一统；数据清洗配比；幻觉问题；复读问题；工具调用；Agent构成
三面：当前大模型问题；设计一个Agent
```

### 3. 跨库去重测试文本
```
RAG在文档数量比较少的时候，和全文检索相比有什么区别和优势
```
应匹配公共题 5930: "rag在文档比较少的情况下，和用全文检索的区别在哪"

```
讲讲不同的RAG分块策略有哪些
```
应匹配公共题 5942: "讲讲不同的RAG 的分块策略？"
