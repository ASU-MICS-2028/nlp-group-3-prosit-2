# PROSIT 2: Non-Developer Friendly API Platform

ICS554 Natural Language Processing · Ashesi MSc Intelligent Computing Systems · Group 3

A non-developer describes a backend in plain words. A team of AI agents builds, tests and runs the API.

```
User ──► Requirements ──► Architect ──► [User approves spec] ──► Coder ◄──► Tester ──► Running API + docs
```

**Rule:** agree on how the parts talk to each other first, then build separately. No one waits on anyone.

---

## What is an agent?

A plain LLM only takes text in and gives text out. An **agent** is an LLM placed in a loop where it can take actions and see the results:

| Part | What it is |
| --- | --- |
| Goal | What the agent is trying to get done |
| LLM | Decides the next step |
| Tools | Functions it can call (write a file, run tests, search docs) |
| Memory | What it has done and seen so far |
| Stop rule | When it's finished, or when it gives up |

### How it works

The agent repeats a **Thought → Action → Observation** loop (ReAct):

```python
history = [goal]
for step in range(MAX_STEPS):
    thought, action = llm(history)       # decide what to do next
    if action.name == "finish":
        break
    observation = run_tool(action)       # do it, get the result
    history += [thought, action, observation]
```

Example from our coder agent:

```
Thought:     The spec needs a Patient model. I'll create it.
Action:      write_file("models.py", ...)
Observation: File saved.
Thought:     Now run the tests.
Action:      run_tests()
Observation: 2 failed: POST /appointments returns 500.
Thought:     The date field isn't parsed. Fix the schema.
...
```

The LLM never runs code itself. It asks for a tool call, our code runs it, and the result goes back into the next prompt.

### How it ties into our project

Our platform is four agents, each running its own loop, coordinated by an orchestrator.

| Agent | Goal | Tools | Done when |
| --- | --- | --- | --- |
| Requirements | Understand what the user wants | Ask user a question | Requirements summary is complete |
| Architect | Turn requirements into a spec | Validate spec against schema | User approves the spec |
| Coder | Build the API from the spec | Write/read file, run server, read logs, search pattern library (RAG) | Code runs and matches the spec |
| Tester | Find bugs | Write tests, run tests | All tests pass, or max fix attempts reached |

- **Orchestrator:** decides which agent runs next and passes the project state between them.
- **Shared memory:** the project spec. Every agent reads and updates it.
- **Human-in-the-loop:** the user approves the spec before any code is written.
- **Self-reflection:** the tester's failure reports send the coder back into its loop.
- **MCP:** tools are described in a standard format, and the finished API is exposed so a frontend agent (e.g. Lovable) can use it.

---

## Day 1: agree together

1. **Spec format:** one JSON/Pydantic structure for data, endpoints and permissions.
2. **Agent format:** every agent takes project state in, returns updated state + a log.
3. **Tool format:** name, inputs, output. MCP-compatible.
4. **Golden example:** a hand-written clinic appointment project (chat, spec, FastAPI code, tests). Everyone uses it as fake input to build their part independently.

## Roles

| Role | Member | Builds | Section A topics owned | Starts from |
| --- | --- | --- | --- | --- |
| 1. Interface & Requirements | | Chat UI, requirements agent, spec approval screen, "try it" panel | Human-in-the-loop, prompt engineering & CoT, memory, alignment | Golden chat + spec |
| 2. Orchestrator & Architect | | Orchestrator loop, architect agent | Orchestration, multi-agent, agentic AI, reasoning & planning, decomposition | Golden chat |
| 3. Coder & Sandbox | | Coder ReAct loop, tools, Docker sandbox, MCP server | Coding agents, ReAct, tool use, MCP, privacy & security | Golden spec |
| 4. Tester, RAG & Evaluation | | Tester agent, RAG, benchmark, comparisons | Self-reflection, RAG, evaluation | Golden code + tests |

### Role 1: Interface & Requirements

**Set up**
- [ ] Help define the user-facing parts of the spec
- [ ] Write the golden example chat transcript

**Build**
- [ ] Pick a simple UI stack (Streamlit or basic React)
- [ ] Chat screen
- [ ] Requirements agent prompt: plain language, one question at a time
- [ ] Output a requirements summary in the agreed format
- [ ] Short-term memory: chat history + summary when long
- [ ] Guardrails: stay on topic, flag unsafe requests
- [ ] Spec approval screen: plain-English view with Approve / Request change
- [ ] "Try it" panel for testing the finished API

**Connect**
- [ ] Connect to the orchestrator (with Role 2)
- [ ] Show build progress to the user

**Evaluate**
- [ ] Usability test with 3–5 non-developers (SUS scores)
- [ ] Count clarifying turns per scenario
- [ ] Section B: interface and human-in-the-loop

### Role 2: Orchestrator & Architect

**Set up**
- [ ] Lead the project state and agent format
- [ ] Write the golden example spec

**Build**
- [ ] Orchestrator: requirements → architect → approval → coder ↔ tester → deploy
- [ ] Stop rules: max fix attempts and fallback
- [ ] Log every step (agent, input, output, tokens, time)
- [ ] Architect agent: requirements → spec via structured output
- [ ] Validate specs against the schema
- [ ] Split the spec into build tasks for the coder
- [ ] Handle "request change" from the approval screen
- [ ] Single-agent mode for comparison

**Connect**
- [ ] Wire all agents (with Roles 1 and 3)
- [ ] Full pipeline run on the golden example

**Evaluate**
- [ ] Compare generated specs with reference specs
- [ ] Hand logs to Role 4
- [ ] Architecture diagram for Section B and slides

### Role 3: Coder & Sandbox

**Set up**
- [ ] Write the golden example FastAPI code
- [ ] Repo structure and base Docker image

**Build**
- [ ] Sandbox: Docker container with time/memory limits, returns logs
- [ ] Tools: write file, read file, run server, run tests, read logs
- [ ] Tool descriptions in MCP-compatible format
- [ ] Coder ReAct loop with step limit
- [ ] Coder prompt with safe defaults (auth on writes, input checks, secrets in env vars)
- [ ] Check generated OpenAPI matches the spec
- [ ] MCP server exposing the finished API spec
- [ ] Document security risks and mitigations

**Connect**
- [ ] Coder ↔ tester loop (with Role 4)
- [ ] Connect to orchestrator (with Role 2)

**Evaluate**
- [ ] Security checklist per scenario
- [ ] Build success rate
- [ ] Section B: coder, sandbox, security

### Role 4: Tester, RAG & Evaluation

**Set up**
- [ ] Write the golden example tests
- [ ] Write 15–30 benchmark scenarios
- [ ] Write hidden tests for each scenario

**Build**
- [ ] Tester agent: tests from spec, runs them, explains failures
- [ ] Agree failure-report format with Role 3
- [ ] RAG: pattern library + FastAPI docs, chunked and embedded
- [ ] Search tool for the coder
- [ ] Spec checking with Schemathesis
- [ ] Evaluation script that saves results to CSV
- [ ] Base vs instruction-tuned model experiment

**Connect**
- [ ] Tester ↔ coder loop (with Role 3)

**Evaluate**
- [ ] Run the benchmark on the full system
- [ ] Comparisons: no tester, single agent, no RAG
- [ ] Results tables and charts
- [ ] Section B: evaluation

### Everyone

- [ ] Teach your theory topic (below)
- [ ] Review a teammate's code each week
- [ ] Present at the weekly teach-back
- [ ] Write your own Section A
- [ ] Present your part in the presentation
- [ ] Be able to explain the whole system for the viva

## Theory topics (taught, not built)

| Topic | Teaches |
| --- | --- |
| Instruction tuning | Role 1 |
| Preference-based learning (incl. DPO) | Role 2 |
| RLHF | Role 3 |
| LLM alignment | Role 4 |

## Working rules

- **Review ring:** 1 → 2 → 3 → 4 → 1, then switch halfway (1 → 3, 2 → 4, 3 → 1, 4 → 2).
- **Weekly teach-back:** 10 minutes per owner, others ask viva-style questions.
- **Pair** when connecting two parts.
- **Section A** is individual, in your own words. **Section B** is shared.

## Order of work

1. **Set up** (all four): Day 1 agreements and golden example.
2. **Build alone:** each part runs on its own using the golden example.
3. **Connect:** pairs first, then the full pipeline.
4. **Evaluate:** benchmark, comparisons, usability test, write-up.

## Checklist

- [x] Create the GitHub repo
- [ ] Assign roles
- [ ] Confirm deadline and set dates
- [ ] Day 1 agreements
- [ ] Golden example
- [ ] Each part runs alone
- [ ] Full pipeline runs end to end
- [ ] Results ready
- [ ] Section B and slides done (repo link on page 1 of both)