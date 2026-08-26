from __future__ import annotations

from typing import Any

from collection.collector import CollectionService
from core.db import db
from screening.screener import ScreeningService


class ClosedLoopPipeline:
    def __init__(self) -> None:
        self.collector = CollectionService()
        self.screener = ScreeningService()

    def collect_and_screen(self, payload: dict[str, Any]) -> dict[str, Any]:
        collection_result = self.collector.collect(payload)
        with db() as conn:
            screening_result = self.screener.run(conn)
        return {
            "collection": collection_result,
            "screening": screening_result,
            "next_step": "select a hot video and product image to create a replication job",
        }

