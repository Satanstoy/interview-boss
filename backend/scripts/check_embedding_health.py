#!/usr/bin/env python3
"""
Embedding 服务健康检查脚本。

用法：
  docker compose exec backend uv run python backend/scripts/check_embedding_health.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("check_embedding_health")


def main() -> None:
    logger.info("🔍 Embedding 服务健康检查")
    logger.info("=" * 60)

    # 1. 环境变量
    logger.info("\n1. 环境变量")
    for var in ["EMBEDDING_BACKEND", "EMBEDDING_MODEL_DIR", "EMBEDDING_OFFLINE"]:
        val = os.environ.get(var, "(未设置)")
        logger.info(f"  {var} = {val}")

    # 2. 模型文件
    logger.info("\n2. 模型文件")
    model_dir = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models/bge-small-zh-v1.5")
    onnx_path = os.path.join(model_dir, "onnx", "model_quantized.onnx")
    tokenizer_path = os.path.join(model_dir, "tokenizer.json")
    logger.info(
        f"  ONNX 文件: {onnx_path}  {'✅ 存在' if os.path.exists(onnx_path) else '❌ 缺失'}"
    )
    logger.info(
        f"  Tokenizer: {tokenizer_path}  {'✅ 存在' if os.path.exists(tokenizer_path) else '❌ 缺失'}"
    )

    # 3. encode_texts 测试
    logger.info("\n3. encode_texts 编码测试")
    try:
        from app.services.embedding_service import encode_texts
        import numpy as np

        texts = ["测试文本1", "测试文本2"]
        vectors = encode_texts(texts)
        logger.info(f"  输入文本数: {len(texts)}")
        logger.info(f"  输出 shape: {vectors.shape}")
        logger.info(f"  数据类型:   {vectors.dtype}")
        norms = np.linalg.norm(vectors, axis=1)
        logger.info(f"  向量 L2 norm: {[f'{n:.6f}' for n in norms]}")
        logger.info(
            f"  归一化:     {'✅ 是' if all(abs(n - 1.0) < 0.01 for n in norms) else '❌ 否'}"
        )
        if np.any(vectors != 0):
            logger.info("  ✅ 向量非零，编码正常")
        else:
            logger.info("  ❌ 向量全零，编码异常")
    except Exception as e:
        logger.info(f"  ❌ 编码失败: {e}")

    # 4. 覆盖率
    logger.info("\n4. question_bank embedding 覆盖率")
    try:
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved'"
            ).fetchone()[0]
            with_emb = conn.execute(
                "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved' AND embedding IS NOT NULL"
            ).fetchone()[0]
        pct = (with_emb / total * 100) if total > 0 else 0
        logger.info(f"  总题目数:     {total}")
        logger.info(f"  有 embedding: {with_emb}")
        logger.info(f"  覆盖率:       {pct:.1f}%")
        logger.info(f"  {'✅' if pct >= 99 else '⚠️'} 覆盖率 {pct:.1f}%")
    except Exception as e:
        logger.info(f"  ❌ 查询失败: {e}")

    logger.info("\n" + "=" * 60)
    logger.info("✅ 检查完成")


if __name__ == "__main__":
    main()
