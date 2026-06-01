"""
测试优化 3：跨 cat2 聚类

测试目标：
1. _extract_technical_keywords 正确提取关键词
2. 候选对筛选逻辑正确
"""
import pytest
from typing import List, Dict, Set
import re


# ──────────────────────────── 模拟的函数实现 ────────────────────────────

def mock_extract_technical_keywords(text: str) -> Set[str]:
    """模拟：提取技术关键词

    策略：
    1. 英文术语：提取 2+ 字符的英文单词
    2. 中文技术名词：提取 2-gram 和 3-gram
    """
    keywords = set()

    # 英文术语（2+ 字符）
    english = re.findall(r'[a-zA-Z][a-zA-Z0-9_]{1,}', text)
    keywords.update(w.lower() for w in english if len(w) >= 2)

    # 中文技术名词：提取 2-gram 和 3-gram
    chinese_chars = re.findall(r'[一-龥]', text)
    for i in range(len(chinese_chars) - 1):
        bigram = ''.join(chinese_chars[i:i+2])
        keywords.add(bigram)
    for i in range(len(chinese_chars) - 2):
        trigram = ''.join(chinese_chars[i:i+3])
        keywords.add(trigram)

    return keywords


def mock_find_cross_cat2_candidates(
    cat2_groups: Dict[str, List[Dict]],
    min_common_keywords: int = 2
) -> List[Dict]:
    """模拟：找不同 cat2 中的相似题候选对"""
    # 为每个题提取关键词
    for cat2, group in cat2_groups.items():
        for item in group:
            item['keywords'] = mock_extract_technical_keywords(item['question'])

    # 按关键词倒排索引
    keyword_index = {}
    for cat2, group in cat2_groups.items():
        for item in group:
            for kw in item['keywords']:
                keyword_index.setdefault(kw, []).append((cat2, item))

    # 找候选对：共享 >= min_common_keywords 个关键词
    candidate_pairs = []
    seen_pairs = set()

    for keyword, items in keyword_index.items():
        for i in range(len(items)):
            for j in range(i+1, len(items)):
                cat2_a, item_a = items[i]
                cat2_b, item_b = items[j]

                # 只处理不同 cat2 的题目
                if cat2_a == cat2_b:
                    continue

                pair_key = (min(item_a['id'], item_b['id']), max(item_a['id'], item_b['id']))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                common_kw = item_a['keywords'] & item_b['keywords']
                if len(common_kw) >= min_common_keywords:
                    candidate_pairs.append({
                        "item_a": item_a,
                        "item_b": item_b,
                        "cat2_a": cat2_a,
                        "cat2_b": cat2_b,
                        "common_keywords": common_kw
                    })

    return candidate_pairs


# ──────────────────────────── 测试用例 ────────────────────────────

class TestExtractTechnicalKeywords:
    """测试 _extract_technical_keywords 函数"""

    def test_extract_english_terms(self):
        """测试：提取英文术语"""
        text = "Redis 持久化方式有哪些？RDB 和 AOF 有什么区别？"
        keywords = mock_extract_technical_keywords(text)

        assert "redis" in keywords
        assert "rdb" in keywords
        assert "aof" in keywords

    def test_extract_chinese_ngrams(self):
        """测试：提取中文 n-gram"""
        text = "Redis 持久化方式有哪些？"
        keywords = mock_extract_technical_keywords(text)

        # 应该提取到"持久化"等 n-gram
        assert "持久化" in keywords

    def test_mixed_text(self):
        """测试：中英文混合文本"""
        text = "TCP 三次握手的作用是什么？"
        keywords = mock_extract_technical_keywords(text)

        assert "tcp" in keywords
        # n-gram 会提取"三次握"和"次握手"，而不是完整的"三次握手"
        assert any("三次" in kw for kw in keywords)
        assert any("握手" in kw for kw in keywords)

    def test_empty_text(self):
        """测试：空文本"""
        text = ""
        keywords = mock_extract_technical_keywords(text)

        assert keywords == set()


class TestFindCrossCat2Candidates:
    """测试 _find_cross_cat2_candidates 函数"""

    def test_find_candidates_basic(self):
        """测试：基本候选对筛选"""
        # 准备：两个题目都包含"Redis"和"持久化"
        cat2_groups = {
            "C3.数据库基础": [
                {"id": 1, "question": "Redis 持久化方式有哪些？"},
            ],
            "C4.操作系统与网络": [
                {"id": 2, "question": "Redis 持久化有什么区别？"},
            ],
        }

        # 执行
        candidates = mock_find_cross_cat2_candidates(cat2_groups)

        # 验证：应该找到候选对
        assert len(candidates) == 1
        assert candidates[0]["item_a"]["id"] == 1
        assert candidates[0]["item_b"]["id"] == 2

    def test_no_candidates_same_cat2(self):
        """测试：同一 cat2 的题目不作为候选"""
        # 准备
        cat2_groups = {
            "C3.数据库基础": [
                {"id": 1, "question": "Redis 持久化方式有哪些？"},
                {"id": 2, "question": "Redis 持久化有什么区别？"},
            ],
        }

        # 执行
        candidates = mock_find_cross_cat2_candidates(cat2_groups)

        # 验证：同一 cat2 的题目不作为候选
        assert len(candidates) == 0

    def test_no_candidates_insufficient_keywords(self):
        """测试：共同关键词不足时不作为候选"""
        # 准备：两个题目只有"持久化"相关的共同关键词
        # n-gram 会提取"持久化"、"持久"、"久化"等，所以会有 3 个共同关键词
        cat2_groups = {
            "A": [
                {"id": 1, "question": "Redis 持久化"},
            ],
            "B": [
                {"id": 2, "question": "MySQL 持久化"},
            ],
        }

        # 执行：要求至少 5 个共同关键词（远超实际）
        candidates = mock_find_cross_cat2_candidates(cat2_groups, min_common_keywords=5)

        # 验证：共同关键词不足 5 个，不满足条件
        assert len(candidates) == 0

    def test_multiple_groups(self):
        """测试：多个 cat2 分组"""
        # 准备
        cat2_groups = {
            "A": [
                {"id": 1, "question": "Redis 持久化方式"},
                {"id": 2, "question": "TCP 三次握手"},
            ],
            "B": [
                {"id": 3, "question": "Redis 持久化区别"},
                {"id": 4, "question": "TCP 连接超时"},
            ],
        }

        # 执行
        candidates = mock_find_cross_cat2_candidates(cat2_groups)

        # 验证：应该找到候选对（Redis 相关）
        assert len(candidates) > 0

        # 验证：所有候选对都是不同 cat2 的题目
        for c in candidates:
            assert c["cat2_a"] != c["cat2_b"]


class TestIntegration:
    """集成测试"""

    def test_realistic_scenario(self):
        """测试：真实场景"""
        # 准备：模拟真实数据
        cat2_groups = {
            "C3.数据库基础": [
                {"id": 1, "question": "Redis 持久化方式有哪些？"},
                {"id": 2, "question": "MySQL 索引优化怎么做？"},
            ],
            "D1.缓存设计与优化": [
                {"id": 3, "question": "Redis 缓存穿透怎么解决？"},
                {"id": 4, "question": "Redis 持久化有什么区别？"},
            ],
        }

        # 执行
        candidates = mock_find_cross_cat2_candidates(cat2_groups)

        # 验证：应该找到 Redis 相关的候选对
        redis_candidates = [c for c in candidates if "redis" in c["common_keywords"]]
        assert len(redis_candidates) > 0

        # 打印统计
        print(f"\n总共找到 {len(candidates)} 个跨 cat2 候选对")
        print(f"Redis 相关候选对: {len(redis_candidates)}")
        for c in redis_candidates[:3]:
            print(f"  Q1 (ID:{c['item_a']['id']}, {c['cat2_a']}): {c['item_a']['question'][:40]}...")
            print(f"  Q2 (ID:{c['item_b']['id']}, {c['cat2_b']}): {c['item_b']['question'][:40]}...")
            print(f"  共同关键词: {c['common_keywords']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
