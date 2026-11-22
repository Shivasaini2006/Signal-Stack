import json

with open(r'C:\Users\SHIVA\.gemini\antigravity\brain\76fb2a72-7d00-4771-80a3-5681e26765ee\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for idx, line in enumerate(f):
        if idx > 60:
            break
        data = json.loads(line)
        t = data.get('type')
        tc = data.get('tool_calls')
        if tc:
            print(f"Step {idx}: {tc}")
        content = str(data.get('content', ''))
        if 'brief' in content.lower() or 'section' in content.lower():
            for l in content.split('\n'):
                if any(w in l.lower() for w in ['section', 'brief', 'executive', 'appendix', 'opportunity', 'competitor']):
                    print(f"  [{idx}] {l[:120]}")
