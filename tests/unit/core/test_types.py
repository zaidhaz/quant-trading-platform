from core.types import Symbol


def test_direct_construction_normalizes_case() -> None:
    lower = Symbol(base="btc", quote="usdt")
    upper = Symbol(base="BTC", quote="USDT")

    assert lower == upper
    assert lower.canonical == "BTC/USDT"
    assert lower.native() == "BTCUSDT"


def test_mixed_case_construction_normalizes() -> None:
    assert Symbol(base="Btc", quote="uSdT").canonical == "BTC/USDT"


def test_hash_is_consistent_across_case(tmp_path) -> None:
    # Symbol is used as a dict/cache key throughout (ParquetStore paths, feature
    # cache, position tracking) — case differences must not fragment identity.
    d = {Symbol(base="btc", quote="usdt"): "a"}
    assert d[Symbol(base="BTC", quote="USDT")] == "a"


def test_parse_still_normalizes_as_before() -> None:
    assert Symbol.parse("btc/usdt").canonical == "BTC/USDT"
    assert Symbol.parse("btcusdt").canonical == "BTC/USDT"
