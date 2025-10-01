import httpx
from mcp.server.fastmcp import FastMCP
import logging
import os
import base64
from typing import Optional, Dict, Union, Any, List
from enum import IntEnum, Enum
import re
from pydantic import BaseModel, Field

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize FastMCP server
mcp = FastMCP("freshdesk-mcp")

FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")

if not FRESHDESK_API_KEY or not FRESHDESK_DOMAIN:
    logging.error(
        "Please set FRESHDESK_API_KEY and FRESHDESK_DOMAIN environment variables"
    )
    exit(1)


def parse_link_header(link_header: str) -> Dict[str, Optional[int]]:
    """Parse the Link header to extract pagination information.

    Args:
        link_header: The Link header string from the response

    Returns:
        Dictionary containing next and prev page numbers
    """
    pagination = {"next": None, "prev": None}

    if not link_header:
        return pagination

    # Split multiple links if present
    links = link_header.split(",")

    for link in links:
        # Extract URL and rel
        match = re.search(r'<(.+?)>;\s*rel="(.+?)"', link)
        if match:
            url, rel = match.groups()
            # Extract page number from URL
            page_match = re.search(r"page=(\d+)", url)
            if page_match:
                page_num = int(page_match.group(1))
                pagination[rel] = page_num

    return pagination


# enums of ticket properties
class TicketSource(IntEnum):
    EMAIL = 1
    PORTAL = 2
    PHONE = 3
    CHAT = 7
    FEEDBACK_WIDGET = 9
    OUTBOUND_EMAIL = 10


class TicketStatus(IntEnum):
    OPEN = 2
    PENDING = 3
    RESOLVED = 4
    CLOSED = 5


class TicketPriority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class AgentTicketScope(IntEnum):
    GLOBAL_ACCESS = 1
    GROUP_ACCESS = 2
    RESTRICTED_ACCESS = 3


class UnassignedForOptions(str, Enum):
    THIRTY_MIN = "30m"
    ONE_HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    EIGHT_HOURS = "8h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "1d"
    TWO_DAYS = "2d"
    THREE_DAYS = "3d"


class GroupCreate(BaseModel):
    name: str = Field(..., description="Name of the group")
    description: Optional[str] = Field(None, description="Description of the group")
    agent_ids: Optional[List[int]] = Field(
        default=None, description="Array of agent user ids"
    )
    auto_ticket_assign: Optional[int] = Field(
        default=0, ge=0, le=1, description="Automatic ticket assignment type (0 or 1)"
    )
    escalate_to: Optional[int] = Field(
        None,
        description="User ID to whom escalation email is sent if ticket is unassigned",
    )
    unassigned_for: Optional[UnassignedForOptions] = Field(
        default=UnassignedForOptions.THIRTY_MIN,
        description="Time after which escalation email will be sent",
    )


class ContactFieldCreate(BaseModel):
    label: str = Field(
        ..., description="Display name for the field (as seen by agents)"
    )
    label_for_customers: str = Field(
        ..., description="Display name for the field (as seen by customers)"
    )
    type: str = Field(
        ...,
        description="Type of the field",
        pattern="^(custom_text|custom_paragraph|custom_checkbox|custom_number|custom_dropdown|custom_phone_number|custom_url|custom_date)$",
    )
    editable_in_signup: bool = Field(
        default=False,
        description="Set to true if the field can be updated by customers during signup",
    )
    position: int = Field(default=1, description="Position of the company field")
    required_for_agents: bool = Field(
        default=False, description="Set to true if the field is mandatory for agents"
    )
    customers_can_edit: bool = Field(
        default=False,
        description="Set to true if the customer can edit the fields in the customer portal",
    )
    required_for_customers: bool = Field(
        default=False,
        description="Set to true if the field is mandatory in the customer portal",
    )
    displayed_for_customers: bool = Field(
        default=False,
        description="Set to true if the customers can see the field in the customer portal",
    )
    choices: Optional[List[Dict[str, Union[str, int]]]] = Field(
        default=None,
        description="Array of objects in format {'value': 'Choice text', 'position': 1} for dropdown choices",
    )


class CannedResponseCreate(BaseModel):
    title: str = Field(..., description="Title of the canned response")
    content_html: str = Field(
        ..., description="HTML version of the canned response content"
    )
    folder_id: int = Field(
        ..., description="Folder where the canned response gets added"
    )
    visibility: int = Field(
        ...,
        description="Visibility of the canned response (0=all agents, 1=personal, 2=select groups)",
        ge=0,
        le=2,
    )
    group_ids: Optional[List[int]] = Field(
        None,
        description="Groups for which the canned response is visible. Required if visibility=2",
    )


@mcp.tool()
async def get_latest_tickets() -> Dict[str, Any]:
    """Get tickets from Freshdesk with pagination support."""
    # Validate input parameters
    page = 1
    per_page = 3

    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets"

    params = {"page": page, "per_page": per_page}

    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()

            # Parse pagination from Link header
            link_header = response.headers.get("Link", "")
            pagination_info = parse_link_header(link_header)

            tickets = response.json()

            return {
                "tickets": tickets,
                "pagination": {
                    "current_page": page,
                    "next_page": pagination_info.get("next"),
                    "prev_page": pagination_info.get("prev"),
                    "per_page": per_page,
                },
            }

        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to fetch tickets: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}


@mcp.tool()
async def reply_to_ticket(ticket_id: int, update_string: str) -> Dict[str, Any]:
    """Create a reply to a ticket in Freshdesk."""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/reply"
    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}"
    }
    data = {"body": update_string}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data)
        return response.json()


@mcp.tool()
async def resolve_ticket(ticket_id: int, resolution_string: str) -> Dict[str, Any]:
    """Update a ticket and set its status to resolved in Freshdesk."""

    reply_url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}/reply"
    resolve_url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}"

    headers = {
        "Authorization": f"Basic {base64.b64encode(f'{FRESHDESK_API_KEY}:X'.encode()).decode()}",
        "Content-Type": "application/json",
    }

    reply_data = {"body": resolution_string}
    resolve_data = {"status": TicketStatus.RESOLVED}

    async with httpx.AsyncClient() as client:
        try:
            reply_response = await client.post(
                reply_url, headers=headers, json=reply_data
            )
            reply_response.raise_for_status()

            resolve_response = await client.put(
                resolve_url, headers=headers, json=resolve_data
            )
            resolve_response.raise_for_status()

            return resolve_response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"Failed to resolve ticket: {str(e)}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}


def main():
    logging.info("Starting Freshdesk MCP server")
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8000
    try:
        mcp.run(transport="sse")
    except KeyboardInterrupt:
        logging.info("Received interrupt signal, shutting down gracefully...")
    except SystemExit:
        logging.info("Received system exit signal, shutting down gracefully...")
    finally:
        logging.info("Freshdesk MCP server stopped")


if __name__ == "__main__":
    main()
