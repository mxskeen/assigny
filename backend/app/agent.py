from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from mcp import ClientSession, StdioServerParameters, stdio_client

from .config import get_settings

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentMessage(BaseModel):
	message: str
	session_id: str


class AgentResponse(BaseModel):
	text: str
	session_id: str


SESSION_HISTORY: Dict[str, List[dict]] = {}


async def _call_with_gemini(message: str, history: List[dict], available_tools: list[dict[str, Any]], session: ClientSession) -> str:
	# Simple tool-calling protocol: ask model to return a JSON with {action, tool_name, args} or {final}
	import google.generativeai as genai
	settings = get_settings()
	genai.configure(api_key=settings.GEMINI_API_KEY)
	model = genai.GenerativeModel(settings.GEMINI_MODEL)

	prompt = (
		"You are a medical appointment assistant. If you need to call a tool, return only a JSON object "
		"like {\"action\":\"tool\", \"tool_name\":\"<name>\", \"args\":{...}}. "
		"If you can answer without tools, return {\"final\":\"<answer>\"}. Tools available: "
		+ ", ".join([t["name"] for t in available_tools])
	)
	chat = model.start_chat(history=[])
	_first = chat.send_message(prompt + "\nUser: " + message)
	try:
		import json
		candidate = _first.text.strip()
		plan = json.loads(candidate)
	except Exception:
		return _first.text

	if plan.get("action") == "tool":
		tool_name = plan.get("tool_name")
		args = plan.get("args", {})
		result = await session.call_tool(tool_name, args)
		# Ask Gemini to summarize the result back to user
		_second = chat.send_message(f"Tool {tool_name} result: {result.content}. Please respond in plain text.")
		return _second.text
	return plan.get("final") or "Done."


async def _call_mcp(message: str, session_id: str) -> str:
	settings = get_settings()
	server_params = StdioServerParameters(command="python", args=["-m", "app.mcp_server"], env=None)
	async with stdio_client(server_params) as (stdio, write):
		async with ClientSession(stdio, write) as mcp_session:
			await mcp_session.initialize()
			tools = await mcp_session.list_tools()
			available_tools = [
				{"name": t.name, "description": t.description, "input_schema": t.inputSchema}
				for t in tools.tools
			]
			history = SESSION_HISTORY.get(session_id, [])
			text = await _call_with_gemini(message, history, available_tools, mcp_session)
			SESSION_HISTORY[session_id] = [*history, {"role": "user", "content": message}, {"role": "assistant", "content": text}]
			return text


@router.post("/chat", response_model=AgentResponse)
async def chat(msg: AgentMessage) -> AgentResponse:
	text = await _call_mcp(msg.message, session_id=msg.session_id)
	return AgentResponse(text=text, session_id=msg.session_id) 