import json
import re

with open(r'C:\Users\SHIVA\.gemini\antigravity\brain\76fb2a72-7d00-4771-80a3-5681e26765ee\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        data = json.loads(line)
        content = json.dumps(data)
        for term in ["executive summary", "source appendix", "10 sections", "section 3 of the assignment", "strategic moves", "regulatory"]:
            if term in content.lower():
                print(f"Match for '{term}' at line {idx}")
