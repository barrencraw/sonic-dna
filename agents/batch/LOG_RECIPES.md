# DNA Batch Chain Log Recipes

## Filtering for Structured Logs
Use `grep` to extract all structured telemetry entries:
```bash
grep "JSON_LOG:" app.log
```

## Parsing with jq
To see a pretty-printed version of all telemetry:
```bash
grep "JSON_LOG:" app.log | sed 's/JSON_LOG: //' | jq .
```

## Finding Errors
Filter for items where the outcome was an error:
```bash
grep "JSON_LOG:" app.log | sed 's/JSON_LOG: //' | jq 'select(.outcome | contains("error"))'
```

## Calculating Average Latency
Use `jq` to extract latency and calculate averages:
```bash
grep "JSON_LOG:" app.log | sed 's/JSON_LOG: //' | jq -s 'map(.latency_ms | select(. != null)) | add / length'
```

## Tracking a Single Correlation ID
If you have a `correlation_id` from `main.py` or a crash report:
```bash
grep "YOUR_CORRELATION_ID" app.log | jq .
```
