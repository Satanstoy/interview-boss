"""Tests for cluster config externalization in core/config.py."""

from __future__ import annotations

import importlib
from unittest import mock

import pytest


def _reload_config(**env_overrides):
    import app.core.config as mod

    with mock.patch.dict("os.environ", env_overrides, clear=False):
        importlib.reload(mod)
        yield mod
    importlib.reload(mod)


class TestClusterConfig:
    def test_defaults_match_existing_hardcoded_values(self):
        for cfg in _reload_config():
            assert cfg.CLUSTER_BATCH_SIZE == 40
            assert cfg.CLUSTER_MAX_CONCURRENCY == 8
            assert cfg.CLUSTER_PREFILTER_TOP_K == 30
            assert cfg.CLUSTER_RECENT_DAYS == 7
            assert cfg.CLUSTER_VALIDATION_BATCH == 20
            assert cfg.CLUSTER_DIRECT_ACCEPT == 0.92
            assert cfg.CLUSTER_VALIDATION_ACCEPT == 0.8
            assert cfg.CLUSTER_MIN_SIMILARITY == 0.6
            assert cfg.CLUSTER_V2_SIM_THRESHOLD == 0.6
            assert cfg.CLUSTER_V2_FAISS_TOP_K == 10
            assert cfg.CLUSTER_COMPACTION_CONCURRENCY == 8
            assert cfg.CLUSTER_CAT2_BATCH == 5
            assert cfg.CLUSTER_PHASE2_BATCH == 20

    def test_env_overrides_defaults(self):
        for cfg in _reload_config(
            CLUSTER_BATCH_SIZE="100",
            CLUSTER_MAX_CONCURRENCY="16",
            CLUSTER_PREFILTER_TOP_K="50",
            CLUSTER_DIRECT_ACCEPT_CONF="0.85",
            CLUSTER_MIN_SIMILARITY="0.7",
        ):
            assert cfg.CLUSTER_BATCH_SIZE == 100
            assert cfg.CLUSTER_MAX_CONCURRENCY == 16
            assert cfg.CLUSTER_PREFILTER_TOP_K == 50
            assert cfg.CLUSTER_DIRECT_ACCEPT == 0.85
            assert cfg.CLUSTER_MIN_SIMILARITY == 0.7

    def test_float_config_parsed_as_float(self):
        for cfg in _reload_config(CLUSTER_VALIDATION_ACCEPT="0.66"):
            assert isinstance(cfg.CLUSTER_VALIDATION_ACCEPT, float)
            assert cfg.CLUSTER_VALIDATION_ACCEPT == 0.66

    def test_int_config_parsed_as_int(self):
        for cfg in _reload_config(CLUSTER_V2_FAISS_TOP_K="25"):
            assert isinstance(cfg.CLUSTER_V2_FAISS_TOP_K, int)
            assert cfg.CLUSTER_V2_FAISS_TOP_K == 25
