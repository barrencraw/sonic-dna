# DNA Batch Parsing Log Recipes

## Monitoring Batch Progress
To see the status of each item in a batch:
```bash
grep "JSON_LOG:" main_output.log | jq 'select(.step == "item_process")'
```

## Finding Errors
To find all parsing errors:
```bash
grep "JSON_LOG:" main_output.log | jq 'select(.outcome | startswith("error"))'
```

## Calculating Total Latency
To see the total time for a batch:
```bash
grep "JSON_LOG:" main_output.log | jq 'select(.step == "end") | {correlation_id, latency_ms}'
```

## Deduplication Hits
To see how many items were skipped due to idempotency:
```bash
grep "JSON_LOG:" main_output.log | jq 'select(.outcome == "skipped")' | wc -l
```
