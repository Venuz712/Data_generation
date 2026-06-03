# Role Dialogue Sample Batch

This directory contains the first worker-generated role dialogue sample batch.

- Record count: 20 JSONL files, one dialogue record per file.
- Source SOPs: `output2/`.
- Output target on worker: `/public/home/chenyueguo/code/Data_generation/dialogues_role/`.
- Sync target locally: `/Users/casper/code/Data_generation/dialogues_role/`.
- Generation mode: role-driven dialogue generation before the API-only expert routing change.
- Routing note: `profile.expert_route` is expected to be null in this batch because these samples were generated before `route_expert_role()` was added.

Quick quality snapshot from the local synced copy:

- `[FINAL_ANSWER]` present: 20/20
- Average dialogue turns: 2.4
- Turn range: 2-5
- Legacy address terms `老乡` / `老哥`: 0
- Phrase `为了给您出最准`: 0
- Phrase `专家您好`: 0
- Mechanical SOP reference pattern: 1 observed case

Use this batch as a small qualitative checkpoint, not as the final scalable data-generation run.
