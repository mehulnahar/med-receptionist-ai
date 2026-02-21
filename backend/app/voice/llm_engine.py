"""
Claude LLM conversation engine for voice calls.

Handles multi-turn conversations with streaming, tool use,
prompt caching, and practice-specific customization.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Tool definitions for Claude
RECEPTIONIST_TOOLS = [
    {
        "name": "check_available_slots",
        "description": "Check available appointment slots for a specific date. Use when patient wants to book an appointment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "appointment_type": {"type": "string", "description": "Type: NEW_PATIENT_COMPLETE, WC_INITIAL, FOLLOW_UP, WORKERS_COMP_FOLLOW_UP, NO_FAULT_FOLLOW_UP, GHI_OUT_OF_NETWORK"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book an appointment for a patient after collecting all required information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": {"type": "string", "description": "DOB in YYYY-MM-DD format"},
                "phone": {"type": "string", "description": "Phone in E.164 format"},
                "date": {"type": "string", "description": "Appointment date YYYY-MM-DD"},
                "time": {"type": "string", "description": "Appointment time HH:MM"},
                "appointment_type": {"type": "string"},
                "insurance_carrier": {"type": "string"},
                "member_id": {"type": "string"},
                "address": {"type": "string"},
                "referring_physician": {"type": "string"},
                "is_new_patient": {"type": "boolean"},
                "accident_type": {"type": "string", "enum": ["none", "workers_comp", "no_fault"]},
                "accident_date": {"type": "string"},
            },
            "required": ["first_name", "last_name", "date_of_birth", "date", "time", "appointment_type"],
        },
    },
    {
        "name": "lookup_patient",
        "description": "Look up an existing patient by name and date of birth.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": {"type": "string"},
            },
            "required": ["first_name", "last_name", "date_of_birth"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel an existing appointment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": {"type": "string"},
            },
            "required": ["first_name", "last_name", "date_of_birth"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": "Reschedule an existing appointment to a new date/time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": {"type": "string"},
                "new_date": {"type": "string"},
                "new_time": {"type": "string"},
            },
            "required": ["first_name", "last_name", "date_of_birth", "new_date", "new_time"],
        },
    },
    {
        "name": "verify_insurance",
        "description": "Verify patient insurance eligibility in real-time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "carrier_name": {"type": "string"},
                "member_id": {"type": "string"},
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": {"type": "string"},
            },
            "required": ["carrier_name", "member_id", "first_name", "last_name", "date_of_birth"],
        },
    },
    {
        "name": "transfer_to_staff",
        "description": "Transfer the call to a human staff member. Use for: billing questions, Greek-speaking callers, complex issues the AI cannot resolve, or when the caller requests a real person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for transfer"},
            },
            "required": ["reason"],
        },
    },
]


def build_system_prompt(
    clinic_name: str,
    doctor_name: str = "",
    address: str = "",
    phone: str = "",
    hours: str = "",
    language: str = "en",
    custom_instructions: str = "",
) -> str:
    """Build the medical receptionist system prompt for Claude."""
    if language == "es":
        return _build_spanish_prompt(clinic_name, doctor_name, address, phone, hours, custom_instructions)

    prompt = f"""You are a warm, professional medical receptionist for {clinic_name}. Your name is the AI Receptionist.

IDENTITY & TONE:
- You are helpful, empathetic, and efficient
- Speak naturally, use the patient's name when you know it
- Show empathy for anxious or distressed patients
- Be patient with elderly callers or those who speak slowly
- Never rush the caller

SCOPE — WHAT YOU CAN DO:
- Schedule, reschedule, and cancel appointments
- Look up existing patient records by name and date of birth
- Verify insurance eligibility
- Provide clinic hours, address, and general information
- Take prescription refill requests (route to staff)
- Take messages for the doctor or staff

SCOPE — WHAT YOU MUST NEVER DO:
- NEVER provide medical advice, diagnoses, or treatment recommendations
- NEVER suggest medications or dosages
- NEVER interpret test results or symptoms
- If asked for medical advice, say: "I'm not able to provide medical advice. Let me connect you with our medical staff who can help you."

EMERGENCY PROTOCOL:
- If the caller mentions: chest pain, heart attack, difficulty breathing, stroke, emergency, 911, dying, severe pain, unconscious, overdose, suicide — IMMEDIATELY say "This sounds like an emergency. Please call 911 immediately. I'm also transferring you to our staff right now." Then use the transfer_to_staff tool.

DATA SECURITY:
- Never repeat full insurance ID numbers — at most confirm the last 4 digits
- Never repeat full dates of birth out loud — confirm by year only
- Never provide information about other patients
- Always verify identity (name + DOB) before accessing records

CLINIC INFORMATION:
- Clinic: {clinic_name}
{f'- Doctor: {doctor_name}' if doctor_name else ''}
{f'- Address: {address}' if address else ''}
{f'- Phone: {phone}' if phone else ''}
{f'- Hours: {hours}' if hours else ''}

CONVERSATION FLOW:
1. Greet the caller warmly: "Thank you for calling {clinic_name}. How can I help you today?"
2. Determine their need (new appointment, existing patient, cancel, reschedule, other)
3. Collect required information with confirmation loops
4. Complete the action using your tools
5. Confirm the result and ask if there's anything else

{f'ADDITIONAL INSTRUCTIONS: {custom_instructions}' if custom_instructions else ''}"""
    return prompt


def _build_spanish_prompt(
    clinic_name: str,
    doctor_name: str,
    address: str,
    phone: str,
    hours: str,
    custom_instructions: str,
) -> str:
    """Build Spanish version of the system prompt."""
    return f"""Eres una recepcionista medica profesional y amable para {clinic_name}. Tu nombre es la Recepcionista de IA.

IDENTIDAD Y TONO:
- Eres servicial, empatica y eficiente
- Habla naturalmente, usa el nombre del paciente cuando lo sepas
- Muestra empatia con pacientes ansiosos o angustiados

ALCANCE — LO QUE PUEDES HACER:
- Programar, reprogramar y cancelar citas
- Buscar registros de pacientes existentes
- Verificar elegibilidad de seguros
- Proporcionar horarios, direccion e informacion general de la clinica

ALCANCE — LO QUE NUNCA DEBES HACER:
- NUNCA proporcionar consejos medicos, diagnosticos o recomendaciones de tratamiento
- Si preguntan por consejo medico, di: "No puedo proporcionar consejo medico. Permitame conectarlo con nuestro personal medico."

PROTOCOLO DE EMERGENCIA:
- Si el paciente menciona emergencia, dolor de pecho, no puede respirar — INMEDIATAMENTE transfiere a personal.

INFORMACION DE LA CLINICA:
- Clinica: {clinic_name}
{f'- Doctor: {doctor_name}' if doctor_name else ''}
{f'- Direccion: {address}' if address else ''}
{f'- Telefono: {phone}' if phone else ''}
{f'- Horario: {hours}' if hours else ''}

{f'INSTRUCCIONES ADICIONALES: {custom_instructions}' if custom_instructions else ''}"""


@dataclass
class ConversationTurn:
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationSession:
    call_id: str
    practice_id: str
    language: str = "en"
    turns: list[ConversationTurn] = field(default_factory=list)
    system_prompt: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class ClaudeLLMEngine:
    """Claude conversation engine with streaming and tool use."""

    def __init__(self):
        settings = get_settings()
        self.api_key = getattr(settings, "ANTHROPIC_API_KEY", "").strip()
        self.sonnet_model = getattr(settings, "CLAUDE_SONNET_MODEL", "claude-sonnet-4-5-20250929")
        self.haiku_model = getattr(settings, "CLAUDE_HAIKU_MODEL", "claude-haiku-4-5-20251001")
        self._sessions: dict[str, ConversationSession] = {}

    def create_session(
        self,
        call_id: str,
        practice_id: str,
        system_prompt: str,
        language: str = "en",
    ) -> ConversationSession:
        """Create a new conversation session for a call."""
        session = ConversationSession(
            call_id=call_id,
            practice_id=practice_id,
            language=language,
            system_prompt=system_prompt,
        )
        self._sessions[call_id] = session
        logger.info("LLM session created for call %s", call_id)
        return session

    def get_session(self, call_id: str) -> Optional[ConversationSession]:
        return self._sessions.get(call_id)

    def end_session(self, call_id: str) -> Optional[ConversationSession]:
        return self._sessions.pop(call_id, None)

    async def generate_response(
        self,
        call_id: str,
        user_message: str,
        model: str = "sonnet",
        use_tools: bool = True,
    ) -> str:
        """Generate a response (non-streaming) for a user message.

        Returns the assistant's text response.
        """
        session = self._sessions.get(call_id)
        if not session:
            logger.error("No session found for call %s", call_id)
            return "I'm sorry, there was an issue with the call. Please try again."

        session.turns.append(ConversationTurn(role="user", content=user_message))

        model_id = self.sonnet_model if model == "sonnet" else self.haiku_model

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                messages = [
                    {"role": t.role, "content": t.content}
                    for t in session.turns
                ]

                body = {
                    "model": model_id,
                    "max_tokens": 1024,
                    "system": [
                        {
                            "type": "text",
                            "text": session.system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": messages,
                }

                if use_tools:
                    body["tools"] = RECEPTIONIST_TOOLS

                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json=body,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    timeout=httpx.Timeout(30.0, connect=5.0),
                )
                response.raise_for_status()
                data = response.json()

                # Track token usage
                usage = data.get("usage", {})
                session.total_input_tokens += usage.get("input_tokens", 0)
                session.total_output_tokens += usage.get("output_tokens", 0)

                # Extract text content and tool_use blocks
                text_parts = []
                tool_calls = []
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_calls.append(block)

                assistant_text = " ".join(text_parts) if text_parts else ""

                # If Claude requested tool calls, log them for now.
                # Tool execution is handled at the ConversationManager level
                # via the Vapi webhook / booking service integration.
                if tool_calls:
                    for tc in tool_calls:
                        logger.info(
                            "LLM tool_use for call %s: %s(%s)",
                            call_id, tc.get("name"), json.dumps(tc.get("input", {}))[:200],
                        )
                    # If no text but tool calls exist, provide placeholder
                    if not assistant_text:
                        assistant_text = "Let me check that for you, one moment."

                session.turns.append(
                    ConversationTurn(role="assistant", content=assistant_text)
                )

                return assistant_text

        except Exception as e:
            logger.error("Claude API error for call %s: %s", call_id, e)
            return "I apologize, I'm having a brief technical issue. Could you please repeat that?"

    async def generate_stream(
        self,
        call_id: str,
        user_message: str,
        model: str = "sonnet",
    ) -> AsyncIterator[str]:
        """Stream a response token by token.

        Yields text chunks as they arrive from Claude.
        Target: first token in ~200ms.
        """
        session = self._sessions.get(call_id)
        if not session:
            yield "I'm sorry, there was an issue with the call."
            return

        session.turns.append(ConversationTurn(role="user", content=user_message))

        model_id = self.sonnet_model if model == "sonnet" else self.haiku_model

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                messages = [
                    {"role": t.role, "content": t.content}
                    for t in session.turns
                ]

                body = {
                    "model": model_id,
                    "max_tokens": 1024,
                    "stream": True,
                    "system": [
                        {
                            "type": "text",
                            "text": session.system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": messages,
                    "tools": RECEPTIONIST_TOOLS,
                }

                full_text = ""
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    json=body,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    timeout=httpx.Timeout(60.0, connect=5.0),
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                event = json.loads(data_str)
                                if event.get("type") == "content_block_delta":
                                    delta = event.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        text = delta.get("text", "")
                                        full_text += text
                                        yield text
                            except json.JSONDecodeError:
                                continue

                session.turns.append(
                    ConversationTurn(role="assistant", content=full_text)
                )

        except Exception as e:
            logger.error("Claude streaming error for call %s: %s", call_id, e)
            yield "I apologize, I'm having a brief technical issue."


_llm_engine: Optional[ClaudeLLMEngine] = None


def get_llm_engine() -> ClaudeLLMEngine:
    global _llm_engine
    if _llm_engine is None:
        _llm_engine = ClaudeLLMEngine()
    return _llm_engine
