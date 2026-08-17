from app.services.llm_usage import aggregate_cache_usage


def test_aggregate_cache_usage_preserves_unknown_fields_as_none():
    assert aggregate_cache_usage(
        [{
            "input_tokens": 100,
            "output_tokens": 20,
            "cached_input_tokens": 80,
            "cache_read_input_tokens": 80,
        }]
    ) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": None,
        "cached_input_tokens": 80,
        "cache_write_input_tokens": None,
    }


def test_aggregate_cache_usage_keeps_real_zero_values():
    assert aggregate_cache_usage(
        [{
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
        }]
    ) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
    }
