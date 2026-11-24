Write the role prompt for an assistant built from these requirements.

REQUIREMENTS:
{{requirements}}

TOPICS THE DOCUMENTS DO NOT COVER (never say or imply the assistant handles them): {{ungrounded}}

Output "role_prompt": 3-5 sentences, second person ("You are ..."), stating the role, the audience, the tone, and the scope. Do NOT include rules about citing or refusing (they are added separately) and do not mention tools.
Output "rules": 2-5 short extra rules that are specific to THIS domain (for example how to treat units, dates, currencies, role-based eligibility, version numbers). Each rule is one sentence. Do not invent facts: no numbers, currencies, names or policies of your own.
