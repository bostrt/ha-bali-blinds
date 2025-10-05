"""Data models for Bali Blinds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import BaliAPI
    from .coordinator import BaliBlindCoordinator


@dataclass
class BaliBlindData:
    """Data for the Bali Blinds integration."""

    api: BaliAPI
    gateway_id: str
    coordinator: BaliBlindCoordinator
