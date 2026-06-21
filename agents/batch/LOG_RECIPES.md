# Log Recipes: DNA Batch Processing

Standardized telemetry logs use the `JSON_LOG:` prefix for easy filtering and analysis.

## 1. Extract All JSON Logs
```bash
grep "JSON_LOG:" app_output.log | sed 's/JSON_LOG: //'
```

## 2. Check for Batch Errors
```bash
grep "JSON_LOG:" app_output.log | grep '"outcome": "error'
```

## 3. Filter by Correlation ID
Useful for tracing a single batch execution:
```bash
grep "YOUR_CORRELATION_ID" app_output.log
```

## 4. Analyze Latency with jq
If `jq` is installed, you can calculate the total latency of successful batches:
```bash
grep "JSON_LOG:" app_output.log | sed 's/JSON_LOG: //' | jq -r 'select(.step=="batch_complete" and .outcome=="success") | .latency_ms'
```

## 5. Find Processing Bottlenecks
Find individual items that took longer than 100ms:
```bash
grep "JSON_LOG:" app_output.log | sed 's/JSON_LOG: //' | jq 'select(.step=="item_process" and .latency_ms > 100)'
```

## 6. Count Deduplication Hits
```bash
grep "JSON_LOG:" app_output.log | grep '"outcome": "skipped"' | wc -l
```
