# Log Recipes: DNA Batch Processing

Use these recipes to monitor and debug the DNA batch processing chain.

## Filter by Correlation ID
Find all logs associated with a specific batch run:
```bash
grep "CORRELATION_ID" data/output/batch.log | jq .
```

## Find Failures
List all items that failed to parse:
```bash
grep "JSON_LOG" | jq 'select(.outcome == "error")'
```

## Monitor Thermal Fatigue
Check the system heat and lockout events:
```bash
grep "SYSTEM_FATIGUE_LOCKOUT" data/output/batch.log
```

## Performance Triage
Find items with high latency (e.g., > 100ms):
```bash
grep "JSON_LOG" | jq 'select(.latency_ms > 100)'
```

## Terminal State Summary
Count occurrences of each terminal state in the current logs:
```bash
grep "JSON_LOG" | sed 's/JSON_LOG: //' | jq -r .outcome | sort | uniq -c
```
