# Running the local models

Secure mode runs two models at once - a fast model for coordination and live follow-ups, and a
reasoning model for analysis. Both must stay resident.

## Ollama settings

    OLLAMA_KEEP_ALIVE=-1          # never unload; both models stay resident
    OLLAMA_MAX_LOADED_MODELS=2    # at least 2, or they evict each other
    OLLAMA_NUM_PARALLEL=4         # concurrent requests per model

`OLLAMA_MAX_LOADED_MODELS` is the one that silently defeats the others. At its default of 1 the
two models evict each other on every alternation regardless of keep-alive and regardless of free
memory, which presents as the models being slow rather than as a configuration fault.

Keep-alive matters because interviewees arrive at lunchtimes with hours of silence between. At the
5 minute default the fast model is cold-loaded repeatedly, and a multi-gigabyte load in front of a
waiting interviewee is exactly the latency the press budget then skips - so a configuration fault
would be masked as a model limitation.

## Context sizes

Ollama's default `num_ctx` is 4096 and it truncates **silently**, oldest tokens first, which are
the instructions. Measured against a live project:

| Artefact | Approx tokens |
|---|---|
| value_chain_tree | 2,900 |
| value_chain_registry | 3,482 |
| value_chain_model | 12,230 |

An agent's system prompt plus task plus one `value_chain_model` read already exceeds 4096. Start at
`num_ctx 16384` for the reasoning model and `8192` for the fast model, then raise from `ollama ps`,
which prints each loaded model's real footprint.

At Q4_K_M a 4B fast model needs roughly 3 GB and a 27B reasoning model roughly 17 GB before KV
cache. On 24 GB that is workable but not comfortable, which is why the sizes above start
conservative.

## Do not set a stop sequence

CrewAI passes its own stop sequence and its tool-calling loop depends on it. A `PARAMETER stop` in
a Modelfile truncates the loop mid-cycle in ways that look like the model failing to use tools.
