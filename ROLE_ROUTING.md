# Expert role API routing

`generate_dialogue_from_sop.py` assigns the farmer role randomly, but assigns the
expert role through one API routing call per SOP dialogue generation.

## Routing contract

The router sends a compact SOP summary and the available expert role list to the
chat API. The response must be a JSON object:

```json
{
  "expert_role_id": "E02_plant_protection_specialist",
  "reason": "该 SOP 核心是病虫害识别与防治"
}
```

`expert_role_id` must be one of:

- `E01_extension_officer`
- `E02_plant_protection_specialist`
- `E03_cultivation_manager`
- `E04_disaster_response_advisor`

## Failure behavior

There is intentionally no keyword routing and no default role fallback. If the
API response is empty, invalid JSON, or returns a role id outside the allowed
set, the current dialogue sample fails and is not written.

The accepted route is stored in each generated record under
`profile.expert_route`:

```json
{
  "method": "api",
  "expert_role_id": "E02_plant_protection_specialist",
  "reason": "..."
}
```

This keeps role selection auditable without mixing routing logic into the
dialogue generation prompt.
