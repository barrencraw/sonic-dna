# Log Recipes for DNA Batch Chain

## Filtering for a specific Correlation ID
```bash
grep "JSON_LOG:" app.log | grep "<correlation_id>" | jq '.data'
```

## Checking for Thermal Refusals
```bash
grep "MSG_REFUSAL" app.log
```

## Monitoring Latency
```bash
grep "JSON_LOG:" app.log | jq '.data | {step, latency_ms}'
```

## Ledger State Summary
```bash
jq '.ledger | length' data/ledger.json
```
