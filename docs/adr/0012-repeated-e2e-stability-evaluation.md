# ADR-0012: 随机性模拟面试采用重复 E2E 聚合评测

**Status:** accepted

使用 LLM Candidate Simulator 的模拟面试不以单次 E2E 结果作为稳定结论。在相同评测目标版本、Evaluation Release 和 Benchmark Case 下建立 E2E Replication Group，重复运行后报告均值、中位数、离散程度、置信范围和关键失败率；硬门禁与质量分开处理，避免一次偶然失败或高分掩盖系统性问题。
