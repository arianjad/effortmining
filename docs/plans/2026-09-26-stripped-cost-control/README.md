# Stripped-mode cost control, 2026-09-26 (Windows)

Six `claude -p` envelopes, run **in parallel**, same prompt (a length-9 string-count task, answer 4920):

    claude -p --effort {low|xhigh} --model opus --setting-sources "" --strict-mcp-config --output-format json "<prompt>"

These are the stripped flags `build_claude_cmd(stripped=True)` emits. Each run wrote ~42.4k
cache-creation tokens, read 0 cache tokens, and cost $0.363–0.403 (`total_cost_usd`). The setup plan's
"~$0.09/run overhead stripped" was not reproduced here. The likely cause is that parallel runs never
read the cache; sequential reps have not been measured yet. Output tokens overlap between tiers (low
1198/1473/3164, xhigh 1415/2096/2534); low-3 answered 4879 (wrong).
