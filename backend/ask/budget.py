"""Per-question budgets, checked before every model call and SQL attempt."""

from __future__ import annotations

from dataclasses import dataclass

MIN_OUTPUT_TOKENS = 600  # below this a reasoning model returns nothing useful


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class Budget:
    max_calls: int
    max_tokens: int
    max_sql: int
    calls: int = 0
    tokens: int = 0
    sql: int = 0

    def reserve_call(self, prompt_chars: int, want_output: int) -> int:
        """Count the call and return the output tokens it may use, or raise if the budget can't cover it."""
        if self.calls >= self.max_calls:
            raise BudgetExhausted(f"The limit of {self.max_calls} model calls per question was reached.")
        room = self.max_tokens - self.tokens - (prompt_chars // 3 + 1)  # conservative prompt estimate
        if room < MIN_OUTPUT_TOKENS:
            raise BudgetExhausted(f"The limit of {self.max_tokens:,} model tokens per question was reached.")
        self.calls += 1
        return min(want_output, room)

    def spend(self, tokens: int) -> None:
        self.tokens += tokens

    def reserve_sql(self) -> None:
        if self.sql >= self.max_sql:
            raise BudgetExhausted(f"The limit of {self.max_sql} SQL attempts per question was reached.")
        self.sql += 1
