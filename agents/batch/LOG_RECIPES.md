# DNA Batch Telemetry Recipes

## Extract all logs for a specific batch
```bash
grep "JSON_LOG:" | grep "<correlation_id>" | jq .
```

## Check for deduplication hits
```bash
grep "JSON_LOG:" | jq 'select(.step == "dedupe" and .outcome == "dedupe_hit")'
```

## Find parsing errors
```bash
grep "JSON_LOG:" | jq 'select(.step == "parse" and .outcome == "error")'
```

## Verify commit success
```bash
grep "JSON_LOG:" | jq 'select(.step == "batch_commit" and .outcome == "success")'
```
