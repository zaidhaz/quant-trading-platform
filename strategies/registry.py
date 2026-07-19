from collections.abc import Callable

from strategies.base_strategy import Strategy

_REGISTRY: dict[str, type[Strategy]] = {}


def register_strategy(name: str) -> Callable[[type[Strategy]], type[Strategy]]:
    def decorator(cls: type[Strategy]) -> type[Strategy]:
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            raise ValueError(f"Strategy name already registered: {name!r}")
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_strategy_class(name: str) -> type[Strategy]:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown strategy: {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def create_strategy(name: str, **params: object) -> Strategy:
    return get_strategy_class(name)(**params)


def registered_strategies() -> list[str]:
    return sorted(_REGISTRY)
