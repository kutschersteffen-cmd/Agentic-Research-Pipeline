# Load report

Simulated run: each company takes 0.5 s, with no network, no API key and no LLM calls. It measures orchestration overhead only, not real cost or time, and the token and cost figures are synthetic. `max_concurrent_llm_calls` stays at its default of 8. For real numbers run `arp scale load --live --universe <universe.csv> --schema <schema.json> --concurrency 4,8,16 --issuers 200`.

| Run | Status | Concurrency | Issuers | Failed | Review | Duration (s) | Tokens in/out | Cost (USD) | USD / 1,000 | Min / 1,000 | Issuers / min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| load_test_fcdf30ff737f | completed | 4 | 200 | 0 | 0 | 25.3 | 1200000/160000 | 6.00 | 30.00 | 2.11 | 474.7 |
| load_test_0cd6d0158f49 | completed | 8 | 200 | 0 | 0 | 12.7 | 1200000/160000 | 6.00 | 30.00 | 1.06 | 942.5 |
| load_test_fa5b588419d6 | completed | 16 | 200 | 0 | 0 | 6.7 | 1200000/160000 | 6.00 | 30.00 | 0.56 | 1792.6 |
