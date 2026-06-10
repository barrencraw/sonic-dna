# LOG RECIPES: DNA Batch Processing

## Filter for JSON Logs
To extract all structured logs from the output:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //'
```

## Analyze with jq
To see the outcome of all items in a specific batch:
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq -s '.[] | select(.step=="item_processed") | {idempotency_key, outcome}'
```

## Check for Batch Success
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq -s '.[] | select(.step=="batch_end") | {correlation_id, outcome, new_processed}'
```
