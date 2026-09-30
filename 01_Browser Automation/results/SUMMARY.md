# Browser Automation Benchmark Summary

Total Runs Recorded: 29

| Timestamp           | Candidate      | Model                | Task                     | Success   |   Duration (s) | TTFA (s)   |   Steps |   Tokens (Total) | Error                          |
|---------------------|----------------|----------------------|--------------------------|-----------|----------------|------------|---------|------------------|--------------------------------|
| 2026-09-30 15:34:01 | browser-use    | groq/openai/gpt-oss- | form_auth_and_state      | PASS      |          39.12 | 35.38      |       6 |                0 |                                |
| 2026-09-30 15:35:05 | browser-use    | groq/openai/gpt-oss- | form_auth_and_state      | PASS      |          30.73 | 26.96      |       6 |                0 |                                |
| 2026-09-30 15:41:50 | browser-use    | groq/openai/gpt-oss- | form_auth_and_state      | PASS      |          32.03 | 28.29      |       6 |                0 |                                |
| 2026-09-30 15:43:23 | browser-use    | groq/openai/gpt-oss- | ecommerce_filter_extract | FAIL      |          29.95 | N/A        |       0 |                0 | Task did not reach completion  |
| 2026-09-30 17:09:01 | browser-use    | deepinfra/Qwen/Qwen2 | ecommerce_filter_extract | PASS      |         334.75 | 27.62      |       7 |                0 |                                |
| 2026-09-30 18:16:09 | browser-use    | cerebras/gpt-oss-120 | form_auth_and_state      | PASS      |          16.17 | 10.65      |       2 |                0 |                                |
| 2026-09-30 18:17:15 | playwright-mcp | default              | form_auth_and_state      | PASS      |          14.18 | 12.75      |       1 |                0 |                                |
| 2026-09-30 18:19:27 | stagehand      | cerebras/gpt-oss-120 | form_auth_and_state      | PASS      |          77.68 | 5.78       |       5 |            6,574 |                                |
| 2026-09-30 18:33:27 | playwright-mcp | default              | form_auth_and_state      | FAIL      |           7.86 | N/A        |       0 |                0 | unhandled errors in a TaskGrou |
| 2026-09-30 18:34:43 | playwright-mcp | default              | form_auth_and_state      | FAIL      |           7.84 | N/A        |       0 |                0 | AttributeError: 'Tool' object  |
| 2026-09-30 18:37:05 | playwright-mcp | default              | form_auth_and_state      | FAIL      |          71.29 | 8.41       |       8 |           26,967 | Did not call task_complete wit |
| 2026-09-30 18:41:08 | playwright-mcp | default              | form_auth_and_state      | FAIL      |          72.94 | 8.38       |       7 |           28,496 | Did not call task_complete wit |
| 2026-09-30 18:46:18 | playwright-mcp | default              | form_auth_and_state      | FAIL      |         132.45 | 8.49       |      14 |           55,983 | Did not call task_complete wit |
| 2026-09-30 18:49:19 | browser-use    | cerebras/gpt-oss-120 | ecommerce_filter_extract | PASS      |          70.15 | 10.04      |       5 |                0 |                                |
| 2026-09-30 18:49:34 | browser-use    | cerebras/gpt-oss-120 | form_auth_and_state      | PASS      |          14.2  | 8.34       |       3 |                0 |                                |
| 2026-09-30 18:53:08 | browser-use    | cerebras/gpt-oss-120 | media_spa_navigation     | PASS      |         214.48 | 14.67      |       5 |                0 |                                |
| 2026-09-30 18:55:27 | browser-use    | cerebras/gpt-oss-120 | github_repo_traversal    | PASS      |         138.49 | 69.61      |       3 |                0 |                                |
| 2026-09-30 18:58:39 | playwright-mcp | default              | ecommerce_filter_extract | PASS      |         191.97 | 6.99       |      12 |           71,753 |                                |
| 2026-09-30 19:00:40 | playwright-mcp | default              | form_auth_and_state      | PASS      |         121.05 | 3.96       |       8 |           36,938 |                                |
| 2026-09-30 19:03:01 | playwright-mcp | default              | media_spa_navigation     | PASS      |         140.81 | 3.95       |       8 |           63,390 |                                |
| 2026-09-30 19:04:14 | playwright-mcp | default              | github_repo_traversal    | PASS      |          73.59 | 4.45       |       6 |           33,899 |                                |
| 2026-09-30 19:05:29 | stagehand      | cerebras/gpt-oss-120 | ecommerce_filter_extract | PASS      |          70.64 | 4.51       |       4 |           15,050 |                                |
| 2026-09-30 19:06:40 | stagehand      | cerebras/gpt-oss-120 | form_auth_and_state      | PASS      |          70.9  | 5.73       |       5 |            6,539 |                                |
| 2026-09-30 19:07:02 | stagehand      | cerebras/gpt-oss-120 | media_spa_navigation     | FAIL      |          21.86 | 7.03       |       5 |           20,542 |                                |
| 2026-09-30 19:08:12 | stagehand      | cerebras/gpt-oss-120 | github_repo_traversal    | FAIL      |          69.53 | N/A        |       1 |                0 | Failed after 3 attempts. Last  |
| 2026-09-30 19:32:10 | browser-use    | cerebras/gpt-oss-120 | media_spa_navigation     | PASS      |         159.81 | 16.95      |       5 |                0 |                                |
| 2026-09-30 20:13:43 | browser-use    | cerebras/gpt-oss-120 | media_spa_navigation     | PASS      |         167.78 | 15.97      |       6 |                0 |                                |
| 2026-09-30 20:34:26 | browser-use    | deepinfra/openai/gpt | media_spa_navigation     | PASS      |          67.22 | 22.90      |      10 |                0 |                                |
| 2026-09-30 20:59:07 | browser-use    | deepinfra/openai/gpt | media_spa_navigation     | PASS      |         248.14 | 35.00      |       8 |                0 |                                |
