# agent/traced_agent.py

from langfuse import get_client
from agent.pipeline import process_ticket

langfuse = get_client()

async def run_traced_investigation(ticket: dict) -> str:
    ticket_text = " | ".join([ticket.get("title", ""), ticket.get("description", "")])

    with langfuse.start_as_current_observation(
        as_type="span",
        name="ticket-investigation",
        input=ticket,
        # ✅ Pass tags and metadata directly here — no separate propagate_attributes call needed
        metadata={
            "ticket_id": ticket.get("id", ""),
            "priority": ticket.get("priority", "unknown"),
            "service": ticket.get("service", "unknown")
        }
    ) as span:

        result = await process_ticket(ticket.get("id", ""), ticket_text)

        span.update(output=result)

    # Flush so traces are sent before the script exits
    langfuse.flush()

    return result