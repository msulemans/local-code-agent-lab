# Compatibility Review After Both Registered Candidates

Date: 2026-08-09 (Australia/Sydney)

## Verdict

Neither registered candidate passes. Do not select either one as the agent
model, rerun a failed configuration, relax a resource gate, or silently repair
model arguments.

| Candidate | Useful evidence | Blocking evidence |
|---|---|---|
| Qwen2.5-Coder 7B Q4_K_M | Zero swap on its clean complete run; fast 4K/16K probes; reasoning 3/4 | Native schema 0/12; decisions 1/16 |
| Qwen3-Coder 30B-A3B Q4_K_M | First observed response was a native schema-valid tool call | 2.53 GiB swap growth after one prompt from a clean zero-swap baseline |

False-looking gates after an early stop are unevaluated unless their numerator
and denominator show a complete sample. Candidate 2 therefore has no completed
quality score.

## Strict adapter counterfactual

`scripts/analyze_content_tool_adapter.py` replays candidate 1's immutable v2
responses without inference. It accepts only a single JSON object containing
exactly `name` and `arguments`; prose, Markdown fences, extra keys, and wrong
types are rejected. It never edits the source run.

| Gate | Original | Strict adapter | Required |
|---|---:|---:|---:|
| Schema-valid tool calls | 0/12 | 10/12 | 11/12 |
| Correct action decisions | 1/16 | 6/16 | 14/16 |
| Correct reasoning answers | 3/4 | 3/4 | 3/4 |

The adapter is technically safe enough to parse, but insufficient to promote
the model. Adding defaults, rewriting paths, deleting unknown arguments, or
changing punctuation would be semantic repair. That would transfer decisions
from the model into an invisible adapter and invalidate the purpose of the
compatibility benchmark.

## Candidate-extension direction

The next experiment must be a separately registered extension, not a third row
quietly added to the completed two-candidate plan. The leading option is the
official `qwen3.5:9b-q4_K_M` Ollama artifact:

- 9.65B parameters and approximately 6.6 GB published artifact size;
- native tool support in the official Ollama listing;
- positioned for coding and agent tasks, though it is a general Qwen3.5 model
  rather than a dedicated `Qwen3-Coder` checkpoint;
- materially closer to the stable 7B footprint than the failed 18.6 GB model
  layer.

`qwen3:8b` is the fallback control: approximately 5.2 GB with native tool
support, but it is older and also not code-specialized.

The separate `model-compatibility-extension-v1` contract now freezes the
extension ID, exact tag and digest prefix,
upstream revision, unchanged prompt/scorer hashes, acquisition evidence, new
run ID, and the same resource stop rules. Candidate 1 and candidate 2 remain
controls. The extension candidate is now downloaded and independently
hash-verified, but no inference has run.

## Reproduce the offline result

```bash
python3.11 scripts/analyze_content_tool_adapter.py
```

This command reads existing evidence only and sends no Ollama request.
