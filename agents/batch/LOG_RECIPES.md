# DNA Batch Log Recipes

Structured logs are prefixed with `JSON_LOG:`. You can pipe the output of `main.py` or `utils/dna_ui.py` to these recipes.

## Extract all JSON logs
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //'
```

## Parse and pretty-print with jq
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq .
```

## Filter by Correlation ID
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq 'select(.correlation_id == "YOUR_UUID")'
```

## Calculate total latency for a batch
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq -s 'map(select(.latency_ms != null)) | map(.latency_ms) | add'
```

## List all refused items (Thermal Overload)
```bash
grep "JSON_LOG:" | sed 's/JSON_LOG: //' | jq 'select(.outcome == "refusal")'
```
