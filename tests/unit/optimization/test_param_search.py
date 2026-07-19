from optimization.param_search import GridSearch, RandomSearch


def test_grid_search_evaluates_full_cartesian_product() -> None:
    param_space = {"a": [1, 2], "b": [10, 20, 30]}
    calls = []

    def evaluate(params):
        calls.append(params)
        return params["a"] + params["b"]

    results = GridSearch().search(param_space, evaluate)

    assert len(calls) == 6  # 2 * 3
    assert len(results) == 6


def test_grid_search_sorts_best_score_first() -> None:
    param_space = {"x": [1, 2, 3]}
    results = GridSearch().search(param_space, lambda p: float(p["x"]))
    assert [p["x"] for p, _ in results] == [3, 2, 1]


def test_random_search_respects_n_iter() -> None:
    param_space = {"x": list(range(100))}
    results = RandomSearch(n_iter=5, seed=1).search(param_space, lambda p: float(p["x"]))
    assert len(results) == 5


def test_random_search_is_deterministic_with_seed() -> None:
    param_space = {"x": list(range(100)), "y": ["a", "b", "c"]}
    calls_a = []
    RandomSearch(n_iter=10, seed=42).search(param_space, lambda p: (calls_a.append(p), 0.0)[1])
    calls_b = []
    RandomSearch(n_iter=10, seed=42).search(param_space, lambda p: (calls_b.append(p), 0.0)[1])
    assert calls_a == calls_b


def test_random_search_sorts_best_score_first() -> None:
    param_space = {"x": list(range(20))}
    results = RandomSearch(n_iter=10, seed=3).search(param_space, lambda p: float(p["x"]))
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)
