# Log Recipes: DNA Batch Chain

Telemetry for the DNA Batch chain is prefixed with `JSON_LOG:`. You can use the following `grep` and `jq` recipes to analyze the results.

## Filter by Chain
```bash
grep "dna_batch_chain" | sed 's/JSON_LOG: //' | jq .
```

## Find Failures
```bash
grep "dna_batch_chain" | grep -v "success" | sed 's/JSON_LOG: //' | jq .
```

## Calculate Total Latency for a Batch
```bash
grep "<correlation_id>" | grep "process_item" | sed 's/JSON_LOG: //' | jq -s 'map(.latency_ms) | add'
```

## Extract Parsed Sequences
```bash
grep "process_item" | sed 's/JSON_LOG: //' | jq -r '.dna_sequence + " -> " + .outcome'
```
