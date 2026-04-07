# Running an Agent Locally with a Model Served on vLLM on OpenShift AI

This guide covers the changes required to go from everything running locally (agent \+ model on your laptop) to agent running locally, model served on a cluster via vLLM \+ KServe on OpenShift AI. 

## 1\. Deploy the Model on OpenShift AI

Two Custom Resources from **two different CRDs** work together:

- **ServingRuntime** (serving.kserve.io/v1alpha1) — defines how to run vLLM (container image, args, ports). Created once per inference engine. OpenShift AI ships several pre-installed.  
- **InferenceService** (serving.kserve.io/v1beta1) — defines which model to deploy (storage, GPU count, memory). Created once per model, references a ServingRuntime.

### ServingRuntime CR

The ServingRuntime carries **all server-level vLLM args**, including tool calling, chat template, and memory management:

Specifically, \--enable-auto-tool-choice and \--tool-call-parser need to be enabled in the ServingRuntime Custom Resource because they control how the vLLM HTTP server parses the model's raw text output into structured tool\_calls in the OpenAI-compatible API response.

```
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: vllm-runtime
spec:
  containers:
    - name: kserve-container
      image: quay.io/modh/vllm #pin to version you need
      args:
        # --- Core (required) ---
        - --port=8080                              # KServe expects this port
        - --model=/mnt/models                      # KServe mounts weights here
        - --served-model-name={{.Name}}            # matches InferenceService name

        # --- Tool calling (required for agentic use cases) ---
        - --enable-auto-tool-choice                # enables tool call detection
        - --tool-call-parser=llama3_json            # model-specific

        # --- Memory management (adjust per GPU) ---
        - --max-model-len=16384                    # caps context window to reduce KV cache VRAM
        - --gpu-memory-utilization=0.9             # fraction of VRAM vLLM will use (default 0.9)

        # --- Multi-GPU (if needed) ---
        # - --tensor-parallel-size=4               # split model across N GPUs

        # --- Optional ---
        # - --chat-template=/path/to/template.jinja  # only if model lacks built-in chat templates (see below)
        # - --tool-parser-plugin=/path/to/plugin.py  # for custom parsers (e.g., Nemotron)
      ports:
        - containerPort: 8080
          protocol: TCP
  supportedModelFormats:
    - name: vLLM
      autoSelect: true
```

#### 

Note: In this case, I also used ' \--tool-call-parser=llama3\_json' \- each model will use different parsers. For example, Mistral-Small-4-119B-2603 will expect 'mistral', 'openai/gpt-oss-120b’ will expect ‘openai\`.

#### Memory Management Args

\--max-model-len and \--gpu-memory-utilization are also **server-level flags** because they control how much VRAM the vLLM process allocates, not what the model weights contain.

Why \--max-model-len matters: The model may support 131K tokens (baked into weights), but the KV cache for the full context window may exceed GPU memory. This flag caps the context window, reducing KV cache allocation. Typically,   
KV cache VRAM \= tokens × 2 × layers × kv\_heads × head\_dim × bytes\_per\_param

When to adjust:  
\- If vLLM crashes with \`Free memory on device ... less than desired GPU memory utilization\` → lower \`--max-model-len\`  
\- If still OOM → lower \`--gpu-memory-utilization\`   
\- The error message includes exact VRAM numbers — use them to calculate the right \`--max-model-len\`

Chat Template:

The chat template (Jinja2) formats conversations into the token format the model expects. Most instruct models embed it in \`tokenizer\_config.json\` and vLLM auto-loads it — no \`--chat-template\` flag needed.

How to verify vLLM auto-loaded it (after deploying):

oc logs $(oc get pods \-l serving.kserve.io/inferenceservice=\<isvc-name\> \-o name) \\  
  | grep \-i "chat.template\\|jinja\\|tokenizer\_config"

vLLM prints one of:

- "Using default chat template from tokenizer\_config.json" — auto-loaded, no action needed  
- "Using supplied chat template" — loaded from \--chat-template flag  
- A warning if no template was found — tool calls will likely fail


### Apply the InferenceService CR

The InferenceService carries **per-model concerns** — which runtime, where the weights are, how much GPU:

```
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-3-3-70b
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      runtime: vllm-runtime                          # ← references the ServingRuntime
      storageUri: pvc://llama-70b-pvc                 # or s3://bucket/path
      resources:
        requests:
          cpu: "2"
          memory: "48Gi"
          nvidia.com/gpu: "4"
        limits:
          cpu: "4"
          memory: "96Gi"
          nvidia.com/gpu: "4"
```

## 2\. Expose the Model Externally

When deploying vllm with KServe using RawDeployment, it creates a **headless Service** (clusterIP: None). To expose the model externally, I needed to expose an OpenShift Route. But, OpenShift Routes cannot point to headless Services, so I needed a workaround to create a ClusterIP service. Using the product dashboard will let you do this too.

3. Update app code to point to vllm \+ KServe on OAI

This was one of the bigger changes that I’ve captured here \- initially using Claude & Anthropic’s Agent SDK and changed it to langgraph/pure python agents for this exercise.

