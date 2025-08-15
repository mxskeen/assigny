from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from openai import OpenAI

from mcp import ClientSession, StdioServerParameters, stdio_client

from .config import get_settings

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentMessage(BaseModel):
    message: str
    session_id: str
    user_type: Optional[str] = None


class AgentResponse(BaseModel):
    text: str
    session_id: str


# Store conversation history by session ID
SESSION_HISTORY: Dict[str, List[dict]] = {}


def extract_tool_plan(text: str) -> Dict[str, Any] | None:
    """Extract JSON tool plan from LLM response with robust parsing."""
    import json
    
    if not text or not text.strip():
        return None
    
    text = text.strip()
    
    # Try direct JSON parsing
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    
    # Try extracting JSON from text with brace balancing
    start = text.find("{")
    if start == -1:
        return None
        
    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start=start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
        if i - start > 10000:  # Prevent infinite loops
            break
    
    if end != -1:
        candidate = text[start:end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    
    return None


def normalize_tool_arguments(tool_name: str, args: Any) -> Dict[str, Any]:
    """Normalize tool arguments to match expected schemas."""
    if not isinstance(args, dict):
        if tool_name == "resolve_date_tool":
            return {"text": str(args)}
        if tool_name == "sql_read_tool":
            return {"sql": str(args)}
        if tool_name in ("book_appointment_tool", "register_patient_tool", "cancel_appointments_by_date_tool"):
            return {"data": {"raw": str(args)}}
        if tool_name == "check_doctor_availability":
            return {"query": {"text": str(args)}}
        return {"query": {"raw": str(args)}}
    
    # Handle specific tool requirements
    if tool_name == "resolve_date_tool":
        text = args.get("text") or args.get("date_string") or args.get("date") or args.get("query")
        if not text or not isinstance(text, str):
            text = ""
        return {"text": text}
    
    if tool_name == "sql_read_tool":
        sql_query = args.get("sql") or args.get("query")
        result = {"sql": sql_query or ""}
        if "params" in args:
            result["params"] = args["params"]
        if "row_limit" in args:
            result["row_limit"] = args["row_limit"]
        return result
    
    if tool_name in ("list_appointments_tool", "patients_by_reason_tool", "appointment_stats_tool", "check_doctor_availability"):
        payload = args.get("query") if isinstance(args.get("query"), dict) else args
        
        # Handle date parameter mapping
        if tool_name == "appointment_stats_tool" and "date" in payload and "for_date" not in payload:
            payload = {**payload, "for_date": payload.get("date")}
            payload.pop("date", None)
        
        # Handle condition parameter mapping
        if tool_name == "patients_by_reason_tool":
            if "condition_like" in payload and "reason_like" not in payload:
                payload = {**payload, "reason_like": payload.get("condition_like")}
                payload.pop("condition_like", None)
        
        return {"query": payload}
    
    if tool_name in ("book_appointment_tool", "register_patient_tool", "cancel_appointments_by_date_tool"):
        if "data" in args and isinstance(args["data"], dict):
            return args
        return {"data": args}
    
    return args


def format_tool_response(tool_name: str, content: str) -> str:
    """Format tool responses for user-friendly display."""
    try:
        if tool_name == "check_doctor_availability":
            return format_availability_response(content)
        elif tool_name == "appointment_stats_tool":
            return format_stats_response(content)
        elif tool_name == "list_appointments_tool":
            return format_appointments_list(content)
        elif tool_name == "patients_by_reason_tool":
            return format_patients_by_reason(content)
        elif tool_name in ("register_patient_tool", "book_appointment_tool"):
            return format_success_response(content)
        else:
            return content
    except Exception:
        return content


def format_availability_response(content: str) -> str:
    """Format doctor availability into user-friendly format."""
    import json
    from datetime import datetime
    
    try:
        data = json.loads(content)
        doctor_name = data.get("doctor_name", "the doctor")
        slots = data.get("available_slots", [])
        
        if not slots:
            return f"No available slots found for {doctor_name} in the next 3 weeks."
        
        lines = []
        for slot in slots[:6]:  # Limit to 6 slots
            try:
                # Handle ISO datetime format: "2025-08-16T09:00:00+00:00-2025-08-16T09:30:00+00:00"
                # Find the split point by looking for the pattern "T...+00:00-"
                split_pattern = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00)-(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00)"
                import re
                match = re.match(split_pattern, slot)
                
                if match:
                    start_iso = match.group(1)
                    end_iso = match.group(2)
                    
                    # Parse the ISO datetime strings
                    start_dt = datetime.fromisoformat(start_iso.replace('+00:00', '+00:00'))
                    end_dt = datetime.fromisoformat(end_iso.replace('+00:00', '+00:00'))
                    
                    date_str = start_dt.strftime("%Y-%m-%d")
                    start_time = start_dt.strftime("%H:%M")
                    end_time = end_dt.strftime("%H:%M")
                    lines.append(f"- {date_str} {start_time}–{end_time}")
                else:
                    # Fallback for other formats
                    lines.append(f"- {slot}")
            except Exception as e:
                print(f"Error parsing slot {slot}: {e}")
                lines.append(f"- {slot}")
        
        result = f"{doctor_name}'s next available slots:\n" + "\n".join(lines)
        if len(slots) > 6:
            result += f"\n…and {len(slots) - 6} more"
        result += "\nWhich time works for you?"
        
        return result
    except Exception as e:
        print(f"Error formatting availability: {e}")
        return content


def format_stats_response(content: str) -> str:
    """Format appointment statistics into readable summary."""
    import json
    
    try:
        data = json.loads(content)
        total = data.get("total_appointments", 0)
        completed = data.get("completed", 0)
        canceled = data.get("canceled", 0)
        by_condition = data.get("by_condition") or {}
        
        # Check if this was a Slack notification request
        if data.get("slack_sent"):
            return "Appointment summary has been sent to Slack successfully!"
        
        parts = [
            f"Total appointments: {total}",
            f"Completed: {completed}",
            f"Canceled: {canceled}"
        ]
        
        if by_condition:
            condition_summary = ", ".join(f"{k}: {v}" for k, v in by_condition.items())
            parts.append(f"By reason: {condition_summary}")
        
        return "; ".join(parts)
    except Exception:
        return content


def format_appointments_list(content: str) -> str:
    """Format appointments list for display."""
    import json
    from datetime import datetime
    
    try:
        data = json.loads(content)
        appointments = data.get("appointments", [])
        
        if not appointments:
            return "No appointments found."
        
        lines = []
        for appt in appointments[:10]:  # Limit to 10 appointments
            start_time = datetime.fromisoformat(appt["start_at"]).strftime("%H:%M")
            end_time = datetime.fromisoformat(appt["end_at"]).strftime("%H:%M")
            doctor = appt.get("doctor_name", "Unknown Doctor")
            patient = appt.get("patient_name", "Unknown Patient")
            description = appt.get("description") or "No reason"
            appt_id = appt.get("appointment_id", "N/A")
            
            lines.append(f"- {doctor} — {patient} ({start_time}–{end_time}) — {description} [#{appt_id}]")
        
        result = "Appointments:\n" + "\n".join(lines)
        if len(appointments) > 10:
            result += f"\n…and {len(appointments) - 10} more"
        
        return result
    except Exception:
        return content


def format_patients_by_reason(content: str) -> str:
    """Format patients by reason response."""
    import json
    from datetime import datetime
    
    try:
        data = json.loads(content)
        patients = data.get("patients", [])
        
        if not patients:
            return "No matching patients found."
        
        lines = []
        for patient in patients[:10]:  # Limit to 10 patients
            name = patient.get("patient_name", "Unknown")
            email = patient.get("patient_email", "")
            appt_id = patient.get("appointment_id", "N/A")
            start_time = datetime.fromisoformat(patient["start_at"]).strftime("%H:%M")
            end_time = datetime.fromisoformat(patient["end_at"]).strftime("%H:%M")
            
            lines.append(f"- {name} ({email}) — appt #{appt_id} {start_time}–{end_time}")
        
        result = "Patients by reason:\n" + "\n".join(lines)
        if len(patients) > 10:
            result += f"\n…and {len(patients) - 10} more"
        
        return result
    except Exception:
        return content


def format_success_response(content: str) -> str:
    """Format success responses from booking/registration tools."""
    import json
    
    try:
        data = json.loads(content)
        if data.get("error"):
            return data["error"]
        return data.get("message", "Operation completed successfully.")
    except Exception:
        return content


def extract_content_text(content: Any) -> str:
    """Extract text content from MCP tool responses."""
    def extract_single(item: Any) -> str:
        # Handle MCP TextContent objects
        if hasattr(item, "text") and isinstance(item.text, str):
            return item.text
        # Handle dict with text key
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
        # Handle dict objects
        if isinstance(item, dict):
            import json
            return json.dumps(item)
        return str(item)
    
    if isinstance(content, list):
        return "\n".join(extract_single(item) for item in content)
    return extract_single(content)


def replace_relative_date(text: str, resolved_date: str, keyword: str) -> str:
    """Replace relative date terms with resolved dates."""
    pattern = re.compile(rf"\b{keyword}(?:['']s)?\b", re.IGNORECASE)
    return pattern.sub(resolved_date, text)


def is_tomorrow_variant(text: str) -> bool:
    """Check if text contains tomorrow variants."""
    lower_text = text.lower()
    tomorrow_variants = ["tomorrow", "tommor", "tmrw", "tmr"]
    return any(variant in lower_text for variant in tomorrow_variants)


async def resolve_relative_dates(message: str, mcp_session: ClientSession) -> str:
    """Resolve relative date references in user messages."""
    try:
        if not message or not isinstance(message, str):
            return message or ""
        
        lower_message = message.lower()
        keyword = None
        
        # Check for weekday patterns
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for day in weekdays:
            if f"next {day}" in lower_message:
                keyword = f"next {day}"
                break
            elif day in lower_message:
                keyword = day
                break
        
        # Check for simple time references
        if not keyword:
            if is_tomorrow_variant(lower_message):
                keyword = "tomorrow"
            elif "yesterday" in lower_message:
                keyword = "yesterday"
            elif "today" in lower_message:
                keyword = "today"
        
        if not keyword:
            return message
        
        # Validate keyword before calling tool
        if not isinstance(keyword, str) or not keyword.strip():
            return message
        
        keyword = keyword.strip()
        if not keyword:
            return message
        
        try:
            result = await mcp_session.call_tool("resolve_date_tool", {"text": keyword})
            content = result.content
            
            from json import loads
            data_text = content[0].text if isinstance(content, list) and hasattr(content[0], "text") else str(content)
            data = loads(data_text)
            
            resolved_date = data.get("date")
            if resolved_date:
                return replace_relative_date(message, resolved_date, keyword)
        
        except Exception as e:
            print(f"Error in date resolution: {e}, keyword: {repr(keyword)}")
            return message
    
    except Exception as e:
        print(f"Unexpected error in resolve_relative_dates: {e}, message: {repr(message)}")
        return message or ""
    
    return message


def extract_doctor_and_period(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract doctor name and time period from text."""
    doctor_name = None
    time_period = None
    
    # Extract doctor name
    doctor_match = re.search(r"\bdr\.?\s+([a-z][a-z\.'-]*?(?:\s+[a-z][a-z\.'-]*)?)\b", text, flags=re.IGNORECASE)
    if doctor_match:
        captured_name = doctor_match.group(1).strip()
        doctor_name = "Dr. " + " ".join(word.capitalize() for word in captured_name.split())
    
    # Extract time period
    if re.search(r"\bmorning\b", text, flags=re.IGNORECASE):
        time_period = "morning"
    elif re.search(r"\bafternoon\b", text, flags=re.IGNORECASE):
        time_period = "afternoon"
    elif re.search(r"\bevening\b", text, flags=re.IGNORECASE):
        time_period = "evening"
    
    return doctor_name, time_period


async def call_llm_with_tools(message: str, history: List[dict], available_tools: list[dict[str, Any]], 
                             session: ClientSession, user_type: str = "patient") -> str:
    """Call LLM with strict tool usage enforcement."""
    settings = get_settings()
    api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        return "Sorry, LLM service is not configured."
    
    base_url = settings.OPENAI_BASE_URL or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model_name = settings.OPENAI_MODEL or "gpt-4o-mini"
    
    role_context = f"You are assisting a {user_type}. " if user_type else ""
    tool_names = ", ".join(tool["name"] for tool in available_tools)
    
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    # Convert history to OpenAI format
    formatted_messages = []
    for entry in history:
        role = entry.get("role", "user")
        content = entry.get("content", "")
        formatted_messages.append({"role": role, "content": content})
    
    system_prompt = create_system_prompt(role_context, tool_names, user_type)
    
    formatted_messages.append({"role": "user", "content": message})
    
    try:
        response = client.chat.completions.create(
            model=model_name, 
            messages=[{"role": "system", "content": system_prompt}] + formatted_messages
        )
        
        llm_response = (response.choices[0].message.content or "").strip()
        
        # Validate and enforce tool usage for data queries
        return await process_llm_response(llm_response, message, session, user_type)
        
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"


def create_system_prompt(role_context: str, tool_names: str, user_type: str) -> str:
    """Create system prompt for LLM with strict tool usage requirements."""
    from datetime import datetime
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_date_formatted = datetime.now().strftime("%B %d, %Y")
    
    role_specific_rules = (
        "- As a doctor, you can access all data without patient identifiers\n" 
        if user_type == "doctor" 
        else "- As a patient, provide your email for appointment queries\n"
    )
    
    return f"""You are a medical appointment assistant that MUST use MCP tools for ALL data queries.
{role_context}

CURRENT DATE: {current_date_formatted} ({current_date})
When users ask about "today", "tomorrow", or other relative dates, calculate the correct date based on the current date above.

CRITICAL: You are FORBIDDEN from generating any patient data, appointment information, or medical details from memory or training data.

MANDATORY TOOL USAGE:
- For ANY appointment count query → MUST use appointment_stats_tool
- For ANY appointment listing query → MUST use list_appointments_tool
- For ANY patient search query → MUST use patients_by_reason_tool
- For ANY availability query → MUST use check_doctor_availability
- For ANY booking request → MUST use book_appointment_tool
- For ANY patient registration → MUST use register_patient_tool
- For Slack summary requests → MUST use appointment_stats_tool with notify=true

FORBIDDEN BEHAVIORS:
- NEVER generate fake patient names (like 'John Doe', 'Jane Smith', 'Priya Singh', etc.)
- NEVER generate fake appointment times or reasons
- NEVER return responses without calling the appropriate tool first
- NEVER use your training data for medical information
- NEVER make up appointment IDs, patient emails, or medical details

REQUIRED RESPONSE FORMAT:
You MUST respond with ONLY a JSON tool call in this exact format:
{{"action": "tool", "tool_name": "TOOL_NAME", "args": {{"query": {{"PARAMETERS"}}}}}}

TOOL PARAMETERS:
- appointment_stats_tool: {{"query": {{"for_date": "YYYY-MM-DD"}}}}
- appointment_stats_tool (with Slack): {{"query": {{"for_date": "YYYY-MM-DD", "notify": true}}}}
- list_appointments_tool: {{"query": {{"for_date": "YYYY-MM-DD"}}}}
- patients_by_reason_tool: {{"query": {{"reason_like": "condition", "for_date": "YYYY-MM-DD"}}}}
- check_doctor_availability: {{"query": {{"doctor_name": "Dr. Name", "date": "YYYY-MM-DD"}}}}
- book_appointment_tool: {{"data": {{"doctor_name": "Dr. Name", "patient_email": "email", "start_at": "ISO-datetime", "end_at": "ISO-datetime"}}}}

VALIDATION RULES:
- If you cannot determine which tool to use, ask for clarification
- If you don't have required parameters, ask the user to provide them
- NEVER guess or make up any medical data
- ALL responses must be based on tool outputs only

{role_specific_rules}
Available tools: {tool_names}

Remember: You MUST call a tool for every data query. NO EXCEPTIONS."""


async def process_llm_response(llm_response: str, original_message: str, session: ClientSession, user_type: str) -> str:
    """Process LLM response with validation and forced tool usage."""
    # Define patterns for data queries that require tools
    data_query_patterns = [
        r"list.*appointments?",
        r"show.*appointments?", 
        r"how many.*appointments?",
        r"patients?.*(with|having)",
        r"appointments?.*(today|tomorrow|yesterday|\d{4}-\d{2}-\d{2})",
        r"available.*slots?",
        r"book.*appointment",
        r"send.*slack|slack.*summary|summary.*slack",
        r"summary.*(for|on).*(today|tomorrow|yesterday|\d{4}-\d{2}-\d{2})"
    ]
    
    is_data_query = any(re.search(pattern, original_message.lower()) for pattern in data_query_patterns)
    
    # Try to extract tool plan from LLM response
    tool_plan = extract_tool_plan(llm_response)
    
    # If it's a data query but no tool was called, force tool usage
    if is_data_query and (not tool_plan or not tool_plan.get("tool_name")):
        return await force_tool_usage(original_message, session)
    
    # Execute tool if plan exists
    if tool_plan and tool_plan.get("tool_name"):
        return await execute_tool_plan(tool_plan, session)
    
    # Return LLM response for non-data queries
    return llm_response


async def force_tool_usage(message: str, session: ClientSession) -> str:
    """Automatically call the correct tool when LLM fails to do so."""
    from datetime import datetime, timedelta
    
    tool_name = None
    tool_args = {}
    
    # Enhanced date extraction
    message_lower = message.lower()
    query_date = None
    
    # Look for specific date patterns
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", message)
    if date_match:
        query_date = date_match.group(1)
    elif "today" in message_lower:
        query_date = datetime.now().strftime("%Y-%m-%d")
    elif "tomorrow" in message_lower:
        query_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "yesterday" in message_lower:
        query_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        # Default to today
        query_date = datetime.now().strftime("%Y-%m-%d")
    
    if re.search(r"how many.*appointments?", message_lower):
        tool_name = "appointment_stats_tool"
        tool_args = {"query": {"for_date": query_date}}
    
    elif re.search(r"list.*appointments?|show.*appointments?", message_lower):
        tool_name = "list_appointments_tool"
        tool_args = {"query": {"for_date": query_date}}
    
    elif re.search(r"patients?.*(with|having)\s+([a-zA-Z\s]+)", message_lower):
        condition_match = re.search(r"patients?.*(with|having)\s+([a-zA-Z\s]+)", message_lower)
        condition = condition_match.group(2).strip() if condition_match else "fever"
        tool_name = "patients_by_reason_tool"
        tool_args = {"query": {"reason_like": condition, "for_date": query_date}}
    
    elif re.search(r"available.*slots?", message_lower):
        doctor_match = re.search(r"dr\.?\s+([a-zA-Z\s]+)", message_lower)
        doctor_name = f"Dr. {doctor_match.group(1).strip().title()}" if doctor_match else "Dr. Ahuja"
        tool_name = "check_doctor_availability"
        tool_args = {"query": {"doctor_name": doctor_name, "date": query_date}}
    
    elif re.search(r"send.*slack|slack.*summary|summary.*slack", message_lower):
        tool_name = "appointment_stats_tool"
        tool_args = {"query": {"for_date": query_date, "notify": True}}
    
    else:
        # Default to appointment stats
        tool_name = "appointment_stats_tool"
        tool_args = {"query": {"for_date": query_date}}
    
    # Execute the forced tool call
    if tool_name:
        try:
            result = await session.call_tool(tool_name, tool_args)
            content = extract_content_text(result.content)
            return format_tool_response(tool_name, content)
        except Exception as e:
            return f"Error calling {tool_name}: {str(e)}"
    
    return "Unable to determine the appropriate tool for your request."


async def execute_tool_plan(plan: Dict[str, Any], session: ClientSession) -> str:
    """Execute a tool plan and format the response."""
    tool_name = plan["tool_name"]
    args = normalize_tool_arguments(tool_name, plan.get("args", {}))
    
    try:
        result = await session.call_tool(tool_name, args)
        content = extract_content_text(result.content)
        formatted_response = format_tool_response(tool_name, content)
        
        # Handle automatic patient registration for booking
        if tool_name == "book_appointment_tool" and "Patient not found" in formatted_response:
            return await handle_patient_registration_and_booking(args, session)
        
        return formatted_response
    except Exception as e:
        return f"Error executing tool {tool_name}: {str(e)}"


async def handle_patient_registration_and_booking(booking_args: Dict[str, Any], session: ClientSession) -> str:
    """Handle automatic patient registration when booking fails due to missing patient."""
    try:
        # Extract patient info from booking args
        data = booking_args.get("data", {})
        patient_email = data.get("patient_email", "")
        
        if not patient_email:
            return "Unable to register patient: email address is required."
        
        # Extract patient name from email with better heuristics
        name_part = patient_email.split("@")[0]
        # Handle various email formats: john.doe, john_doe, johndoe123, etc.
        name_cleaned = name_part.replace(".", " ").replace("_", " ").replace("-", " ")
        # Remove numbers and special characters
        import re
        name_cleaned = re.sub(r'[0-9]+', '', name_cleaned)
        name_cleaned = re.sub(r'[^a-zA-Z\s]', '', name_cleaned)
        
        # Capitalize each word
        patient_name = " ".join(word.capitalize() for word in name_cleaned.split() if word)
        
        # If no name could be extracted, use a default format
        if not patient_name:
            patient_name = f"User {name_part}"
        
        # Register the patient first
        registration_args = {
            "data": {
                "name": patient_name,
                "email": patient_email,
                "primary_condition": data.get("description", "general consultation")
            }
        }
        
        print(f"Auto-registering new patient: {patient_name} ({patient_email})")
        register_result = await session.call_tool("register_patient_tool", registration_args)
        register_content = extract_content_text(register_result.content)
        print(f"Registration result: {register_content}")
        
        # Check if registration was successful (more flexible checking)
        registration_success = any(keyword in register_content.lower() for keyword in [
            "successfully", "registered", "created", "added"
        ])
        
        if registration_success:
            print("Registration successful, attempting to book appointment...")
            # Now retry the booking
            booking_result = await session.call_tool("book_appointment_tool", booking_args)
            booking_content = extract_content_text(booking_result.content)
            formatted_booking = format_tool_response("book_appointment_tool", booking_content)
            
            return f"Welcome! I've registered you as a new patient ({patient_name}) and {formatted_booking.lower()}"
        else:
            return f"Unable to register new patient: {register_content}"
            
    except Exception as e:
        print(f"Exception in handle_patient_registration_and_booking: {e}")
        return f"Error during patient registration and booking: {str(e)}"


async def process_agent_request(message: str, session_id: str, user_type: Optional[str] = None) -> str:
    """Main function to process agent requests with MCP tools."""
    server_params = StdioServerParameters(command="python", args=["-m", "app.mcp_server"], env=None)
    
    async with stdio_client(server_params) as (stdio, write):
        async with ClientSession(stdio, write) as mcp_session:
            await mcp_session.initialize()
            
            tools = await mcp_session.list_tools()
            available_tools = [
                {"name": tool.name, "description": tool.description, "input_schema": tool.inputSchema}
                for tool in tools.tools
            ]
            
            history = SESSION_HISTORY.get(session_id, [])
            
            # Resolve relative dates in the message
            if any(tool.name == "resolve_date_tool" for tool in tools.tools):
                message = await resolve_relative_dates(message, mcp_session)
            
            # Process the message with LLM and tools
            response_text = await call_llm_with_tools(
                message, history, available_tools, mcp_session, user_type or "patient"
            )
            
            # Handle special cases for date resolution chaining
            if response_text.strip().lower().startswith("date resolved to "):
                response_text = await handle_date_resolution_chaining(
                    response_text, message, mcp_session
                )
            
            # Handle fallback tool execution if LLM returned JSON
            fallback_plan = extract_tool_plan(response_text)
            if fallback_plan:
                response_text = await execute_fallback_tool(fallback_plan, mcp_session)
            
            # Update session history
            SESSION_HISTORY[session_id] = [
                *history,
                {"role": "user", "content": message},
                {"role": "assistant", "content": response_text}
            ]
            
            return response_text


async def handle_date_resolution_chaining(response_text: str, original_message: str, mcp_session: ClientSession) -> str:
    """Handle automatic chaining after date resolution."""
    resolved_date = response_text.strip().split()[-1].strip(". ")
    doctor_name, time_period = extract_doctor_and_period(original_message)
    
    if doctor_name:
        try:
            result = await mcp_session.call_tool("check_doctor_availability", {
                "query": {"doctor_name": doctor_name, "date": resolved_date, "part_of_day": time_period}
            })
            content = extract_content_text(result.content)
            return format_availability_response(content)
        except Exception:
            pass
    
    return response_text


async def execute_fallback_tool(plan: Dict[str, Any], mcp_session: ClientSession) -> str:
    """Execute fallback tool when LLM returns JSON instead of calling tool."""
    action = str(plan.get("action", "")).lower()
    
    if action in ("tool", "call_tool") or action.endswith("_tool"):
        tool_name = plan.get("tool_name") or plan.get("action")
        args = normalize_tool_arguments(tool_name, plan.get("args", {}))
        
        try:
            result = await mcp_session.call_tool(tool_name, args)
            content = extract_content_text(result.content)
            return format_tool_response(tool_name, content)
        except Exception as e:
            return f"Error executing fallback tool {tool_name}: {str(e)}"
    
    return "Unable to execute the requested tool."


@router.post("/chat", response_model=AgentResponse)
async def chat(msg: AgentMessage) -> AgentResponse:
    """Handle chat requests from the frontend."""
    response_text = await process_agent_request(
        msg.message, 
        session_id=msg.session_id, 
        user_type=msg.user_type
    )
    return AgentResponse(text=response_text, session_id=msg.session_id) 