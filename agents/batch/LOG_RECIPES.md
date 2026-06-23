# DNA Batch Log Recipes

## Find all logs for a specific correlation ID
```bash
grep "335cda98-49f9-4034-9a20-988fd6f123d4" toSequence_parsed.json | jq .
```
*(Note: Logs are currently printed to stdout, redirection to a file is recommended in production)*

## Check for any errors in the batch process
```bash
grep "JSON_LOG:" | grep '"outcome": "error"'
```

## Calculate average latency for DNA parsing
```bash
grep "JSON_LOG:" | grep '"step": "dna_parse"' | jq '.latency_ms' | awk '{ sum += $1; n++ } END { if (n > 0) print sum / n; else print 0 }'
```
