# 面经导入 case 修复与验证计划

用户要求：公司和面试轮次不应被隐藏；用蔚来 Agent 一面及衍生 case 暴露流程问题。

1. 在 `backend/tests/services/test_submit_public_commit_fence.py` 和 `test_public_contributions_materialize.py` 复现公共入库清空元信息；运行失败测试，再修复 `persist_public.py` 和公共审核投影。面经默认继承公司/轮次，显式 null 仍删除；来源 URL 和 JD 薪资仍按原规则处理。
2. 在 `backend/tests/pipeline/test_submit_url_validation.py` 增加 Markdown 残片、缺失域名、空白 URL；先确认失败，再收紧后端 `core/validation.py` 与前端 `utils/validate.js`，不自动猜测修复链接。
3. 在聚类验证测试中复现高置信错误匹配绕过验证，启用默认二次验证；添加原始 11 题和正负匹配对 fixture，使用真实配置在只读评估中检查实际提示词表现，不写线上题库。
4. 跑相关回归、前端校验、代码审查，记录未解决问题；只提交本任务文件并同步现有分支，不合并主线。
