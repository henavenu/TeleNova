"""TeleNova — LangGraph state."""
from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class CareState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    customer_id: str
    session_id: str
    intent: str          # billing | provisioning | sim_porting | retention | account_recovery | fallback
    # Account Recovery Board poll loop (coordinator ↔ reviewer nodes via Command(goto))
    council_round: int
    council_idx: int
