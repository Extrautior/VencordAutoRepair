# Model delegation evidence

The configured tool advertised `deepseek/deepseek-v4-flash`, routed through
opencodex to DeepSeek. Every implementation worker was spawned with this explicit
model override. The primary agent independently read each worker's recorded
`turn_context.model` session metadata; all five reported this exact route.
The tool does not independently expose or attest a provider sub-version named
"V4.1". No other subagent model was substituted.

| Worker session | Ownership |
| --- | --- |
| 01a1e038-5e06-78e2-bb6d-36e94c91f450 | Runtime, entry point, startup registration and tests |
| 01a1e038-5ea0-7700-9e68-923075212fdf | Configuration GUI |
| 01a1e038-5ee7-7b40-883a-688150b53b91 | Build, icon, installer and Actions workflow |
| 01a1e03a-7144-7651-8301-6956a81a52df | Repair reliability tests and binary smoke script |
| 01a1e03b-0a90-7350-b1f5-62b822eb78ea | README, release notes and startup design |

Workers used disjoint write scopes in the development checkout. Reports were
reviewed by the primary agent. Runtime and build workers eventually exhausted
HTTP 429 retries. The primary agent completed remaining integration fixes,
security review, installer lifecycle checks, source review and final builds.
No replacement model was spawned and no numerical token/cost saving is claimed.

The installer configuration follow-up used worker
`01a1e056-ccdf-72a1-86fc-810d64d67ad6` with the same explicit route. Its recorded
`turn_context.model` was independently verified as
`deepseek/deepseek-v4-flash`. The primary agent verified startup execution and
installer lifecycle behavior.
