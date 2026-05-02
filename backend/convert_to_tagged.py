import os
import csv
import json
import sys
import time
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
INTERVIEW_CSV = os.path.join(DATA_DIR, "interview.csv")
TAGGED_CSV = os.path.join(DATA_DIR, "interview_questions.csv")

TAGGED_HEADERS = [
    "来源链接", "公司", "面试轮次", "题目",
    "一级大类", "二级子类", "考点标签", "难度标签"
]

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

# 强调输出格式：引入 ID 强对应机制，减少输出 Token，提升稳定性
TAGGING_PROMPT = """你是一名面试题结构化分类专家。请将下列每道面试题精确分配到分类体系中，并按要求输出JSON。

## 分类体系（严格遵循层级）
- **A. 项目经验与设计**
   A1. 项目介绍与背景
   A2. 系统架构设计
   A3. 难点攻关与优化
   A4. 反思与改进
- **B. Agent与LLM应用**
   B1. Agent架构设计
   B2. 记忆管理
   B3. 检索增强生成/RAG
   B4. 工具调用与集成
   B5. Prompt工程
   B6. 推理与规划范式
   B7. 上下文管理
   B8. 监控与评估
- **C. 基础工程能力**
   C1. 编程语言基础
   C2. 框架与中间件
   C3. 数据库基础
   C4. 操作系统与网络
- **D. 分布式系统与高并发**
   D1. 分布式一致性
   D2. 高并发策略
   D3. 链路与排障
- **E. 算法与数据结构**
   E1. 算法手撕与数据结构
- **F. 模型训练与评估**
   F1. 微调与评估
- **其他** (仅当确实无法归入以上任何一类时使用)

## 考点标签（可多选，从下方选择，用逗号分隔）
Agent架构设计, 记忆管理, RAG设计, 工具调用, Prompt工程, ReAct/推理范式, 上下文管理, 微调/SFT, 模型评估, Java并发, Redis, Spring/AOP, 分布式事务, 高并发限流, MySQL, Linux/网络, 算法手撕, 系统设计, AI Coding, 模型选型

## 难度标签（单选）
- L1-基础：考察基础知识、八股文，无需复杂推理
- L2-中等：需要结合项目场景、融会贯通
- L3-困难：需要深度系统设计或复杂算法手撕

## 规则
1. 一级大类与二级子类必须匹配，例如选了一级大类 A，则二级子类必须是 A1-A4 之一。
2. 考点标签应选择与题目直接相关的技术领域，不要与二级子类简单重复。
3. 如果题目包含多个子问题，请拆分后作为独立题目分别标注。
4. 返回的结果中必须包含输入的 `id` 字段。

## Few-Shot 示例
输入题目列表：[{"id": 0, "题目": "请介绍你做过的一个项目，并说明其中遇到的难难点"}]
输出：
{"questions": [{"id": 0, "题目": "请介绍你做过的一个项目，并说明其中遇到的难点", "一级大类": "A.项目经验与设计", "二级子类": "A3.难点攻关与优化", "考点标签": "系统设计", "难度标签": "L2-中等"}]}

输入题目列表：[{"id": 0, "题目": "Redis持久化机制有哪些？"}, {"id": 1, "题目": "如何设计一个分布式锁？"}]
输出：
{"questions": [
  {"id": 0, "题目": "Redis持久化机制有哪些？", "一级大类": "C.基础工程能力", "二级子类": "C2.框架与中间件", "考点标签": "Redis", "难度标签": "L1-基础"},
  {"id": 1, "题目": "如何设计一个分布式锁？", "一级大类": "D.分布式系统与高并发", "二级子类": "D2.高并发策略", "考点标签": "分布式事务, Redis", "难度标签": "L2-中等"}]}

## 任务
现在请为以下题目列表标记：
{questions}
"""

BATCH_SIZE = 15
MAX_RETRIES = 3 # 适当增加重试次数


def parse_to_standard(item: dict) -> dict:
    """安全提取字段，防止各种 None 导致的异常"""
    cat1 = str(item.get("一级大类") or item.get("大类") or item.get("primary_category") or "")
    cat2 = str(item.get("二级子类") or item.get("子类") or item.get("secondary_category") or "")
    
    tags = item.get("考点标签") or item.get("考点") or item.get("tags") or ""
    if isinstance(tags, list):
        tags = ",".join(str(t) for t in tags)
    else:
        tags = str(tags)
        
    diff = str(item.get("难度标签") or item.get("难度") or item.get("difficulty") or "")
    
    return {
        "一级大类": cat1.strip(),
        "二级子类": cat2.strip(),
        "考点标签": tags.strip(),
        "难度标签": diff.strip()
    }


def extract_questions_from_json(parsed) -> list:
    """万能解析器"""
    if isinstance(parsed, list): return parsed
    if not isinstance(parsed, dict): return []
    if "questions" in parsed and isinstance(parsed["questions"], list): return parsed["questions"]
    for key in ["items", "data", "results", "list"]:
        if key in parsed and isinstance(parsed[key], list): return parsed[key]
    if any(k in parsed for k in ["id", "一级大类", "primary_category"]): return [parsed]
    return []


def call_api_with_retry(messages, retries=MAX_RETRIES):
    """调用 API，失败时带有指数退避重试机制"""
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=45  # 防止网络死锁
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt < retries:
                wait_time = 2 ** attempt
                print(f"    [警告] API 调用失败 (等待 {wait_time}s 后重试 {attempt+1}/{retries}): {e}")
                time.sleep(wait_time)
            else:
                print(f"    [错误] API 彻底失败: {e}")
                raise e


def tag_questions_batch(questions: list) -> list:
    """调用 AI 打标签，并使用 ID 强映射保证输出与输入严格对应"""
    # 构造带 ID 的请求数据
    input_data = [{"id": idx, "题目": q} for idx, q in enumerate(questions)]
    q_json = json.dumps(input_data, ensure_ascii=False)
    user_msg = TAGGING_PROMPT.replace("{questions}", q_json)
    
    messages = [
        {"role": "system", "content": "你是一个严格输出 JSON 的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便一一对应。"},
        {"role": "user", "content": user_msg}
    ]
    
    try:
        content = call_api_with_retry(messages)
        # 去除 Markdown 格式包裹
        if content.startswith("```"):
            content = re.sub(r'^```(json)?\n', '', content)
            content = re.sub(r'\n```$', '', content)

        parsed = json.loads(content)
        raw_items = extract_questions_from_json(parsed)
        
        # 建立 ID -> 标签字典的映射
        result_map = {}
        for item in raw_items:
            if isinstance(item, dict) and "id" in item:
                try:
                    item_id = int(item["id"])
                    result_map[item_id] = parse_to_standard(item)
                except (ValueError, TypeError):
                    pass
        
        # 组装结果，确保数量不变且能成功处理
        standardized = []
        for idx, q in enumerate(questions):
            if idx in result_map:
                standard_item = result_map[idx]
                standard_item["题目"] = q  # 强制保留原始问题文本，防止大模型魔改
                standardized.append(standard_item)
            else:
                standardized.append({
                    "题目": q,
                    "一级大类": "未分类(API漏标)",
                    "二级子类": "未分类",
                    "考点标签": "",
                    "难度标签": "未知"
                })
        return standardized
        
    except Exception as e:
        print(f"    [严重错误] 批次解析失败，跳过: {e}")
        # 如果整体失败，全部赋空避免丢题
        return [{
            "题目": q, "一级大类": "标注失败", "二级子类": "-", 
            "考点标签": "-", "难度标签": "-"
        } for q in questions]


def split_questions(raw_text: str) -> list:
    """拆分题目清单文本为单个题目列表，兼容各种奇葩序号"""
    if not raw_text or not str(raw_text).strip():
        return []
    questions = []
    for line in str(raw_text).split('\n'):
        line = line.strip()
        if not line:
            continue
        # 正则匹配形如 "1.", "1、", "1)", "(1)", "1- " 等格式的前缀并移除
        cleaned = re.sub(r'^(\(?\d+[\.\)\]、\-]\s*)', '', line)
        if cleaned:
            questions.append(cleaned)
    return questions


def write_to_csv_safe(file_path, rows):
    """安全追加写入CSV，解决运行中途被 Excel 占用导致崩溃的问题"""
    while True:
        try:
            # 统一使用 utf-8-sig 防止 Excel 乱码
            with open(file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            break
        except PermissionError:
            print(f"\n⚠️ 写入被拒绝！请检查文件 [{os.path.basename(file_path)}] 是否正被 Excel 等软件打开。")
            input("请关闭该文件后，按 【Enter】 键继续执行...")
        except Exception as e:
            print(f"\n❌ 写入 CSV 时发生意外错误: {e}")
            break


def main():
    if not os.path.exists(INTERVIEW_CSV):
        print(f"未找到原始数据文件: {INTERVIEW_CSV}")
        sys.exit(1)

    with open(INTERVIEW_CSV, mode='r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TAGGED_CSV):
        with open(TAGGED_CSV, mode='w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow(TAGGED_HEADERS)

    total_new = 0

    for idx, row in enumerate(rows):
        url = row.get("来源链接", "未提供链接")
        company = row.get("公司", "未提供")
        round_ = row.get("面试轮次", "未提供")
        q_text = row.get("具体题目清单", "")
        
        questions = split_questions(q_text)
        if not questions:
            continue

        print(f"\n[{idx+1}/{len(rows)}] 处理面经 ({company} - {round_}): 共 {len(questions)} 题")

        all_items = []
        for i in range(0, len(questions), BATCH_SIZE):
            batch = questions[i:i + BATCH_SIZE]
            print(f"  -> 请求 API 标注 ({i+1} 至 {min(i+BATCH_SIZE, len(questions))}) ...")
            
            items = tag_questions_batch(batch)
            all_items.extend(items)
            
            # 准备写入行数据
            write_rows = [
                [url, company, round_, item["题目"], item["一级大类"], 
                 item["二级子类"], item["考点标签"], item["难度标签"]] 
                for item in items
            ]
            
            write_to_csv_safe(TAGGED_CSV, write_rows)
            time.sleep(0.5)

        total_new += len(all_items)
        print(f"  ✅ 本场面经完成，成功入库 {len(all_items)} 道题")

    print(f"\n🎉 全部处理完毕！共新增/覆盖 {total_new} 条题目记录。文件已保存至：{TAGGED_CSV}")


if __name__ == "__main__":
    main()