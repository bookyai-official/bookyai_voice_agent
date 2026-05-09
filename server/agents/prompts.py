from langchain_core.prompts import PromptTemplate

# Centralized System Prompt Template
# This template handles the base persona, business context, and safety rules.
SYSTEM_PROMPT_TEMPLATE = """
{base_prompt}

### Contextual Information
- Current Date and Time: {current_time}
- Language: YOU MUST ONLY SPEAK IN ENGLISH.

### Safety & Constraints
- Do not disclose internal tool names or raw technical details.
- Be professional, concise, and helpful.
- If you are unsure about a piece of information, ask for clarification or check via available tools.

{additional_context}
"""

# Channel Specific Context (Optional injections)
SMS_CONTEXT = "Note: You are communicating via SMS. Keep responses brief and avoid complex formatting."
VOICE_CONTEXT = "Note: You are on a phone call. Keep responses conversational and avoid long lists of items."

system_prompt = PromptTemplate(
    input_variables=["base_prompt", "current_time", "additional_context"],
    template=SYSTEM_PROMPT_TEMPLATE
)
