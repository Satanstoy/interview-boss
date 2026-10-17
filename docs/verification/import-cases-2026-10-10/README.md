# 蔚来 Agent 一面导入回归

用户提供 CSV 中的「蔚来 AI Agent 开发一面」包含 11 道题。线上任务 `403bdfb2-0939-4083-aaea-1e6fd58c5624`、面经 `5031`：提取、标签与聚类完成，9 道新题/2 道匹配；全部新题答案最终生成完成。

## 已修复

- 面经公共直导与审核默认保留公司/轮次；审核 UI 预填真实值；显式 null/空串仍删除。来源 URL 与 JD 公司/薪资沿用显式确认。已更新 contracts §3.1。
- 上传与审核共用 URL 校验，拦截 Markdown `](` 残片、缺失主机、空白、反斜线和账号密码 URL；前端提交前同样校验。
- 聚类匹配、新题内部聚类、二次验证提示词以考察对象/范围/约束为准，禁止仅按主题或子集/超集合并。默认启用候选匹配的高置信二次验证；完全相同文本仍使用零调用匹配。非精确匹配可能多一次模型调用。

## 手工 case

导入页面粘贴 txt 全文，类型选面经，测试时选「仅自己可见」。测试公共元信息时再选分享并检查审核预览。

| 文件 | 检查目标 |
| --- | --- |
| `01-nio-original.txt` | 公司蔚来、轮次一面，11 条题目完整提取 |
| `02-nearby-but-distinct.txt` | 构造样本；6 道题应保留各自考察范围，不能按共有关键词过度合并 |
| `03-missing-metadata.txt` | 构造样本；不得编造公司/轮次；tuple 含 list 的追问不能丢失 |

匹配对 fixture：`backend/tests/fixtures/import_cases/nio_agent_first_round.json`，包含 10 对正负样本。真实模型 `mimo-v2.6-flash`、temperature=0，在相同输入下，匹配提示词修改前 7/10，修改后 10/10；正例为 4 个等价改述，负例 6 个。原先错误匹配包括通用鉴权→金融放款、Tool Calling/Skill→MCP 综合题、项目介绍→重构题。

`matcher-before.json`、`matcher-after.json` 保存逐对原始输出与耗时。评估只调用匹配提示词，不写线上题库；这些数字不是完整上传流水线或全量题库质量指标。默认二次验证另由离线测试验证路由与拒绝行为。

复现（使用已配置的模型环境，产生模型调用）：

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/evaluate_import_pair_cases.py backend/tests/fixtures/import_cases/nio_agent_first_round.json
```

## 验证

- 后端相关元信息、URL、审核、恢复、聚类回归：123 passed，1 条已有 Pydantic warning。
- Node URL 测试：2 passed。
- Playwright 两个审核 spec：5 passed；最后文案修改后投影 spec 重跑 2 passed。
- 前端生产构建成功（4.01 秒）；已有 bundle 大小提示。
- 审查未发现阻断项，暂存内容密钥扫描无泄露。

## 此 case 额外暴露但未修复

1. Python list/tuple 和 ==/is 基础题被打成「算法手撕」：分类正确、标签不准确，需检查标签候选及回退策略。
2. 部分答案生成和连接重试耗时较长；已完成聚类时根任务仍显示 running。可增加「已入库/聚类完成，答案生成中」展示与阶段耗时指标。本次九个新题到 17:35:44（UTC+8）全部完成。
3. 第一题生成答案把 tuple 可哈希一概而论，而包含 list 的 tuple 不可哈希；缺元信息手工 case 特意增加该追问，后续可加入答案事实校验。

本轮不修改历史审核投影或线上面经 5031，不自动修正既有错误聚类关系。修复尚未部署，线上仍是先前审查版本；新行为在部署后生效。基线未跟踪文件及依赖缓存符号链接保留，不纳入提交。
