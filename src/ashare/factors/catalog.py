from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FactorDef:
    name: str
    category: str
    description: str = ""
    formula: str = ""
    data_dependency: str = "ohlcv"
    frequency: str = "daily"
    lookback: int = 0
    availability_time: str = "T_close"
    direction: str = "high"  # high | low | neutral
    missing_value_policy: str = "nan"
    available: bool = True
    active: bool = True


@dataclass
class FactorCatalog:
    version: str
    factors: dict[str, FactorDef] = field(default_factory=dict)
    leader_weights: dict[str, float] = field(default_factory=dict)
    normalization: dict[str, Any] = field(default_factory=dict)

    def available_names(self) -> list[str]:
        return [n for n, f in self.factors.items() if f.available and f.active]

    def by_category(self, category: str) -> list[str]:
        return [n for n, f in self.factors.items() if f.category == category and f.available]


def catalog_from_yaml(data: dict[str, Any]) -> FactorCatalog:
    factors: dict[str, FactorDef] = {}
    for raw in data.get("factors") or []:
        name = str(raw["name"])
        factors[name] = FactorDef(
            name=name,
            category=str(raw.get("category") or "misc"),
            description=str(raw.get("description") or ""),
            formula=str(raw.get("formula") or ""),
            data_dependency=str(raw.get("data_dependency") or "ohlcv"),
            frequency=str(raw.get("frequency") or "daily"),
            lookback=int(raw.get("lookback") or 0),
            availability_time=str(raw.get("availability_time") or "T_close"),
            direction=str(raw.get("direction") or "high"),
            missing_value_policy=str(raw.get("missing_value_policy") or "nan"),
            available=bool(raw.get("available", True)),
            active=bool(raw.get("active", True)),
        )
    lw = {k: float(v) for k, v in (data.get("leader_weights") or {}).items()}
    s = sum(lw.values()) or 1.0
    lw = {k: v / s for k, v in lw.items()}
    return FactorCatalog(
        version=str(data.get("factor_version") or "factor_v1"),
        factors=factors,
        leader_weights=lw,
        normalization=dict(data.get("normalization") or {}),
    )
