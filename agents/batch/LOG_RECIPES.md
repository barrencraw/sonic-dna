# DNA Batch Log Recipes

## Analyze Errors
```bash
grep "JSON_LOG" output.log | jq 'select(.outcome == "error")'
```

## Check Batch Latency
```bash
grep "JSON_LOG" output.log | jq 'select(.step == "batch_start" or .step == "batch_end") | {timestamp, correlation_id, step}'
```

## Trace a Specific Correlation ID
```bash
grep "YOUR_CORRELATION_ID" output.log | grep "JSON_LOG" | jq '.'
```

## Count Processed vs Skipped Items
```bash
grep "JSON_LOG" output.log | jq -s 'group_by(.outcome) | map({outcome: .[0].outcome, count: length})'
```
