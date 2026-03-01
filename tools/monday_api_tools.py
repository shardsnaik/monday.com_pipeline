"""
Monday.com API Tool Layer
All queries are live - no caching, no preload
"""

import requests
from typing import Optional
from datetime import datetime, date
import time

MONDAY_API_URL = "https://api.monday.com/v2"

class MondayAPITools:
    def __init__(self, api_key: str, deals_board_id: str, work_orders_board_id: str):
        self.api_key = api_key
        self.deals_board_id = deals_board_id
        self.work_orders_board_id = work_orders_board_id
        self.headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            "API-Version": "2024-01"
        }

    def _execute_query(self, query: str, variables: dict = None) -> dict:
        """Execute a raw GraphQL query against Monday API"""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(
            MONDAY_API_URL,
            json=payload,
            headers=self.headers,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise Exception(f"Monday API Error: {data['errors']}")

        return data

    def get_deals(self) -> tuple[list, dict]:
        """
        Fetch live deals data from Monday board.
        Returns: (items, trace_info)
        """
        query = """
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            name
            items_page(limit: 500) {
              items {
                id
                name
                column_values {
                  column { title }
                  text
                  value
                }
              }
            }
          }
        }
        """
        start = time.time()
        data = self._execute_query(query, {"boardId": self.deals_board_id})
        elapsed = time.time() - start

        items = data["data"]["boards"][0]["items_page"]["items"]
        board_name = data["data"]["boards"][0]["name"]

        trace = {
            "tool": "get_deals()",
            "api_endpoint": f"boards(ids={self.deals_board_id})",
            "board_name": board_name,
            "records_retrieved": len(items),
            "latency_ms": round(elapsed * 1000),
            "timestamp": datetime.now().isoformat()
        }

        return items, trace

    def get_work_orders(self) -> tuple[list, dict]:
        """
        Fetch live work orders data from Monday board.
        Returns: (items, trace_info)
        """
        query = """
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            name
            items_page(limit: 500) {
              items {
                id
                name
                column_values {
                  column { title }
                  text
                  value
                }
              }
            }
          }
        }
        """
        start = time.time()
        data = self._execute_query(query, {"boardId": self.work_orders_board_id})
        elapsed = time.time() - start

        items = data["data"]["boards"][0]["items_page"]["items"]
        board_name = data["data"]["boards"][0]["name"]

        trace = {
            "tool": "get_work_orders()",
            "api_endpoint": f"boards(ids={self.work_orders_board_id})",
            "board_name": board_name,
            "records_retrieved": len(items),
            "latency_ms": round(elapsed * 1000),
            "timestamp": datetime.now().isoformat()
        }

        return items, trace

    def get_board_columns(self, board_id: str) -> list:
        """Fetch column metadata for a board"""
        query = """
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            columns {
              id
              title
              type
            }
          }
        }
        """
        data = self._execute_query(query, {"boardId": board_id})
        return data["data"]["boards"][0]["columns"]