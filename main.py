"""
Customer Support AI Agent — Starter Code
==========================================
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

app = BedrockAgentCoreApp()


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"

GATEWAY_URL = "https://customersupportgateway-g7f0zg4y4a.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "EOVVNSYLJ3"
REGION      = "us-east-1"
MEMORY_ID   = "CustomerSupportMemory-u35T8r7vrn"

model_id = "global.amazon.nova-2-lite-v1:0"

model = BedrockModel(model_id=model_id)

memory_client = MemoryClient(region_name=REGION)

_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


SYSTEM_PROMPT = """You are an intelligent customer support assistant for an e-commerce platform.

You handle complex, multi-step customer service workflows — order tracking, returns processing, product 
recommendations, and loyalty rewards calculations — all while maintaining conversation context across sessions.

You have access to tools via the AgentCore Gateway:
- order_tracker          : handles order and customer lookups
- refund_processor       : handles refunds and return labels

You have PERSISTENT MEMORY: you remember each customer's preferences, and interests across multiple conversations.

MEMORY-AWARE BEHAVIOUR
- When a "Customer Context" block appears at the start of the user's message,
  it contains facts and preferences retrieved from past conversations.
- Use this context to personalise your recommendations naturally.
- Reference past context: "Based on your last order, I think you might like..."

You have access to the calculate_loyalty_discount tool, which runs exact arithmetic inside
a secure, isolated Python sandbox via the AgentCore Code Interpreter.

USE calculate_loyalty_discount WHENEVER a customer asks about discount.
Never estimate or guess numbers yourself. When asked about discounts, always run calculate_loyalty_discount to compute the final result. Present the final result clearly as a string with a brief explanation.

When a customer asks about a destination, navigate to the url that is provided in the user input:
"""

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    strategies = mem_client.get_memory_strategies(memory_id)
    return { strategy["type"]: strategy["namespaces"][0] for strategy in strategies }


class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(self.memory_client, self.memory_id)


    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        messages = event.agent.messages
        if (
            not messages
            or messages[-1]["role"] != "user"
            or "toolResult" in messages[-1]["content"][0]
        ):
            return

        user_query = messages[-1]["content"][0]["text"]

        try:
            all_context = []
            for strategy_type, namespace in self.namespaces.items():
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=namespace.format(actorId=self.actor_id),
                    query=user_query,
                    top_k=5,
                )
                for memory in memories:
                    if isinstance(memory, dict):
                        text = memory.get("content", {}).get("text", "").strip()
                        if text:
                            all_context.append(f"[{strategy_type}] {text}")

            if all_context:
                memories = "\n".join(all_context)
                original_message = messages[-1]["content"][0]["text"]
                messages[-1]["content"][0]["text"] = (
                    f"Customer Context:\n{memories}\n\n{original_message}"
                )
                logger.info("Retrieved %d memory items for actor %s", len(all_context), self.actor_id)

        except Exception as exc:
            logger.error("Failed to retrieve customer context: %s", exc)

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
    
        try:
            messages = event.agent.messages
            customer_query = agent_response = None

            for msg in reversed(messages):
                if msg["role"] == "assistant" and not agent_response:
                    content = msg["content"]
                    if isinstance(content, list):
                        agent_response = content[0].get("text", "")
                    else:
                        agent_response = str(content)
                elif (
                    msg["role"] == "user"
                    and not customer_query
                    and "toolResult" not in msg["content"][0]
                ):
                    customer_query = msg["content"][0]["text"]
                    break

            if customer_query and agent_response:
                self.memory_client.create_event(
                    memory_id=self.memory_id,
                    actor_id=self.actor_id,
                    session_id=self.session_id,
                    messages=[
                        (customer_query, "USER"),
                        (agent_response, "ASSISTANT"),
                    ],
                )
                logger.info("Saved interaction to memory for actor %s", self.actor_id)

        except Exception as exc:
            logger.error("Failed to save interaction: %s", exc)

    def register_hooks(self, registry: HookRegistry) -> None:
        """Register both memory callbacks."""
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)


@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    if not KB_ID:
        return "Knowledge base not configured."

    resp = _bedrock_runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
    )
    results = resp.get("retrievalResults", [])
    if not results:
        return f"No information found for: {query}"
    
    chunks = [r["content"]["text"] for r in results]
    return "\n---\n".join(chunks)


@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    code = f"""
earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

loyalty_points = {loyalty_points}
tier = "{tier}"
order_total = {order_total}
product_category = "{product_category}"

max_points_redeemable = int(order_total * 0.50 * 100)
points_redeemed = min(loyalty_points, max_points_redeemable)
points_redeemed_rounded = (points_redeemed // 500) * 500  # round down to nearest 500
points_value = points_redeemed_rounded / 100

subtotal_after_points = order_total - points_value
tier_rate = tier_rates.get(tier, 0.00)
tier_discount = subtotal_after_points * tier_rate

final_total = subtotal_after_points - tier_discount
total_savings = points_value + tier_discount
points_earned = int(subtotal_after_points * earn_rates.get(product_category, 1))
remaining_points = loyalty_points - points_redeemed_rounded + points_earned

import json
result = {{
    "points_redeemed": points_redeemed_rounded,
    "tier_discount": round(tier_discount, 2),
    "final_total": round(final_total, 2),
    "total_savings": round(total_savings, 2),
    "points_earned": points_earned,
    "remaining_points": remaining_points
}}
print(json.dumps(result))
"""

    try:
        with code_session(REGION) as session:
            response = session.invoke("executeCode", {
                "code": code,
                "language": "python",
                "clearContext": True
            })
            for event in response["stream"]:
                if "result" in event:
                    return json.dumps(event["result"])

    except Exception as e:
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_rate = tier_rates.get(tier, 0.00)
        tier_discount = order_total * tier_rate
        final_total = order_total - tier_discount

        import json
        result = {
            "points_redeemed": 0,
            "tier_discount": round(tier_discount, 2),
            "final_total": round(final_total, 2),
            "total_savings": round(tier_discount, 2),
            "points_earned": 0,
            "remaining_points": loyalty_points,
            "fallback": True
        }
        return json.dumps(result)

@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """

    user_input = payload.get("prompt", "Hi!")
    actor_id     = payload.get("customer_id", "actor_id")
    session_id = payload.get("session_id", str(uuid.uuid4()))

    memory_hook = MemoryHook(actor_id=actor_id, session_id=session_id, memory_client=memory_client, memory_id=MEMORY_ID)
    agent_core_browser = AgentCoreBrowser(session_timeout=600)

    client = MCPClient(
        lambda: streamable_http_client(url=GATEWAY_URL)
    )
    with client:
        tools = client.list_tools_sync()
        logger.info("Tool names: %s", [t.tool_name for t in tools])
        logger.info("Discovered %d tools from Gateway", len(tools))

        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=[agent_core_browser.browser, search_knowledge_base, calculate_loyalty_discount, tools],
            state={"session_id": session_id, "actor_id": actor_id},
            hooks=[memory_hook],
        )
        response = agent(user_input)
    return response
    
# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()
