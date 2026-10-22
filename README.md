# PROSIT 2: Non-Developer Friendly API Development Platform

**ICS554 Natural Language Processing** · Master's in Intelligent Computing Systems, Ashesi University · Group 3

A tool where a non-developer describes a backend in plain words, and a team of AI agents builds, tests and runs the API for them. Built around Mesora's principle that frontends and backends should be independent and communicate through a well-defined API.

---

## What we're building

The system has four agents that pass work along a line:

1. **Requirements agent** chats with the user and asks clarifying questions.
2. **Architect agent** turns the answers into a project spec (the data, the endpoints, who can do what). The user approves it.
3. **Coder agent** writes the FastAPI code from the approved spec.
4. **Tester agent** tests the code and sends failures back to the coder to fix.

```
User ──► Requirements ──► Architect ──► [User approves spec] ──► Coder ◄──► Tester ──► Running API + OpenAPI docs
```

**The one big rule:** we agree on how the parts talk to each other first, then everyone builds their part separately. Nobody should have to wait for someone else's code to start working.

## Day 1: what we agree on together

Before anyone codes, all four of us agree on:

1. **The project spec format.** One shared data structure (JSON/Pydantic) listing the data, endpoints and permissions. Every agent reads and updates this.
2. **The agent format.** Every agent takes the current project state in and gives an updated state plus a log of what it did out. Same shape for all four.
3. **The tool format.** How a tool is described and called: its name, its inputs, its output. Kept MCP-compatible.
4. **One golden example.** A hand-written fake project, a clinic appointment system: the chat, the spec, working FastAPI code and a test suite.

The golden example is what stops us from blocking each other. Each person uses the parts of it they need as fake input, so they can build and test their piece straight away.

## The four roles

Each person owns one part of the system and becomes the expert on the Section A topics that part uses. Add your name next to your role.

| Role | Member | What you build | Section A topics you own | What you start from |
| --- | --- | --- | --- | --- |
| **1. Interface & Requirements** | | Chat screen, requirements agent, plain-language spec approval screen, "try it" panel | Human-in-the-loop, prompt engineering & chain-of-thought, memory, alignment (guardrails) | Golden example's chat and spec |
| **2. Orchestrator & Architect** | | Control loop that decides which agent runs next, and the architect agent that writes the spec | Orchestration, multi-agent systems, agentic AI, reasoning & planning, decomposition | Golden example's chat |
| **3. Coder & Sandbox** | | Coder agent's ReAct loop, its tools (write file, run server, read logs), Docker sandbox, MCP server for frontend handoff | Coding agents, ReAct / perceive-plan-act, tool use, MCP, privacy & security | Golden example's spec |
| **4. Tester, RAG & Evaluation** | | Tester agent and its feedback to the coder, RAG over code patterns and docs, benchmark and comparison runs | Self-reflection, RAG, evaluation | Golden example's code and tests |

Role 3 should keep the sandbox very simple at first: one container, run the code, capture the logs. Everyone needs it later, so it must not become a bottleneck.

## Role breakdowns

Each role's tasks are grouped by the four steps in [Order of work](#order-of-work). Tick them off as you go.

### Role 1: Interface & Requirements

**Step 1: Agree and set up**

- [ ] Help define the spec format, especially the parts the user will see
- [ ] Write the golden example's chat transcript (user describing the clinic system, agent asking questions)

**Step 2: Build alone**

- [ ] Pick a simple UI stack (e.g. Streamlit or a basic React page) and agree it with the group
- [ ] Build the chat screen that sends messages to the backend and shows replies
- [ ] Write the requirements agent's prompt: plain language, one clarifying question at a time, no jargon
- [ ] Define when it stops: it outputs a requirements summary in the agreed format
- [ ] Add short-term memory: keep the chat history, and summarise it when it gets long
- [ ] Add guardrails: stay on topic, flag unsafe requests (e.g. storing passwords in plain text)
- [ ] Build the spec approval screen: data, endpoints and permissions shown in plain English, with Approve and Request change buttons
- [ ] Build the "try it" panel so a user can test the finished API with simple actions
- [ ] Test everything using the golden example as fake input

**Step 3: Connect the parts**

- [ ] Connect the UI and requirements agent to the orchestrator (pair with Role 2)
- [ ] Show the user which agent is working and what stage the build is at

**Step 4: Evaluate and write up**

- [ ] Run the usability test with 3–5 non-developers and collect SUS scores and notes
- [ ] Record how many clarifying turns each benchmark scenario needed
- [ ] Write the Section B part on the interface and human-in-the-loop design
- [ ] Plan the live demo flow for the presentation

### Role 2: Orchestrator & Architect

**Step 1: Agree and set up**

- [ ] Lead the agreement on the project state and agent formats
- [ ] Write the golden example's spec

**Step 2: Build alone**

- [ ] Build the orchestrator loop: requirements → architect → user approval → coder ↔ tester → deploy
- [ ] Add stop rules: a maximum number of fix attempts, and what happens when it's reached
- [ ] Log every step (agent, input, output, tokens, time) so Role 4 can measure it
- [ ] Build the architect agent: turns the requirements summary into a spec using structured output
- [ ] Check every spec against the agreed schema and reject invalid ones
- [ ] Break the approved spec into small build tasks for the coder (one per entity or endpoint group)
- [ ] Handle "request change" from the approval screen by updating the spec
- [ ] Build a single-agent mode (one agent does everything) for the comparison test

**Step 3: Connect the parts**

- [ ] Wire all four agents together (pair with Roles 1 and 3)
- [ ] Run the full pipeline end to end on the golden example

**Step 4: Evaluate and write up**

- [ ] Compare the architect's specs with the reference specs for the benchmark scenarios
- [ ] Give Role 4 the logs for token, time and step counts
- [ ] Draw the architecture diagram for Section B and the slides

### Role 3: Coder & Sandbox

**Step 1: Agree and set up**

- [ ] Write the golden example's FastAPI code
- [ ] Set up the repo folder structure and a base Docker image

**Step 2: Build alone**

- [ ] Build the sandbox: a Docker container that runs generated code and returns the logs, with time and memory limits
- [ ] Build the tools: write file, read file, run server, run tests, read logs
- [ ] Describe each tool in the agreed MCP-compatible format
- [ ] Build the coder's ReAct loop: thought → tool call → observation, with a step limit
- [ ] Write the coder prompt: build exactly what the approved spec says, with safe defaults (login on write endpoints, input checks, secrets in environment variables)
- [ ] Check that the generated API's OpenAPI output matches the approved spec
- [ ] Build the MCP server that lets a frontend agent read the finished API's spec
- [ ] Write down the security risks (prompt injection, secrets, unsafe code) and how we handle each

**Step 3: Connect the parts**

- [ ] Connect the coder and tester feedback loop (pair with Role 4)
- [ ] Connect the coder to the orchestrator (pair with Role 2)

**Step 4: Evaluate and write up**

- [ ] Run the security checklist on each benchmark scenario
- [ ] Report the build success rate
- [ ] Write the Section B part on the coder, sandbox and security

### Role 4: Tester, RAG & Evaluation

**Step 1: Agree and set up**

- [ ] Write the golden example's test suite
- [ ] Write 15–30 benchmark scenarios as plain-language requests (clinic, library, church register, small shop)
- [ ] Write a hidden test suite for each scenario

**Step 2: Build alone**

- [ ] Build the tester agent: writes tests from the spec, runs them in the sandbox, and explains failures to the coder
- [ ] Agree the failure-report format with Role 3
- [ ] Build RAG: collect code patterns (login, pagination, relationships) and FastAPI docs, split them into chunks, embed and search them
- [ ] Give the coder a search tool for that pattern library
- [ ] Set up spec checking with Schemathesis
- [ ] Build the evaluation script: runs every scenario and saves the results to a CSV
- [ ] Run the base vs instruction-tuned model experiment

**Step 3: Connect the parts**

- [ ] Connect the tester and coder loop (pair with Role 3)

**Step 4: Evaluate and write up**

- [ ] Run the benchmark on the full system
- [ ] Run the comparisons: no tester, single agent, no RAG
- [ ] Make the results tables and charts
- [ ] Write the Section B evaluation part

### Everyone

- [ ] Teach your theory topic in a 20-minute session
- [ ] Review your teammate's code (review ring)
- [ ] Present your part at each weekly teach-back
- [ ] Write your own Section A
- [ ] Present your part in the 10-minute presentation
- [ ] Be able to explain every part of the system for the viva

## Theory-only topics

Some Section A topics are about how the model was trained, so we won't build them. Each person reads up on one and teaches it to the group in a 20-minute session.

| Topic | Who teaches it |
| --- | --- |
| Instruction tuning | Role 1 |
| Preference-based learning (incl. DPO) | Role 2 |
| RLHF | Role 3 |
| LLM alignment | Role 4 |

Role 4 also runs one small experiment: send the same request to a base model and an instruction-tuned model, and show the difference.

## How everyone learns everything

The viva is individual, so each of us must be able to explain the whole system.

- **Review ring.** 1 reviews 2, 2 reviews 3, 3 reviews 4, 4 reviews 1. Halfway through, switch: 1 reviews 3, 2 reviews 4, 3 reviews 1, 4 reviews 2.
- **Weekly teach-back.** Each owner explains their part in 10 minutes; the others ask viva-style questions ("why does the loop stop here?", "what happens if a tool call fails?").
- **Pair when connecting parts.** When two parts are joined, both owners work on it together.
- **Section A stays individual.** Share reading lists and notes, but each person writes Section A in their own words. Section B is the same for all of us.

## Order of work

1. **Agree and set up (all four, 1–2 sessions).** Agree on the Day 1 items and write the golden example.
2. **Build alone.** Each part runs on its own from the command line using the golden example as input. Role 4 writes the benchmark scenarios and hidden tests here, since they depend on no one.
3. **Connect the parts.** First in pairs (requirements → architect, coder ↔ tester), then the full pipeline from chat to running API.
4. **Evaluate and write up.** Run the benchmark, run the comparisons (with/without tester, one agent vs many, with/without RAG), and test with 3–5 non-developers. Results go into Section B and the presentation.

## Checklist

- [x] Create the GitHub repo
- [ ] Everyone picks a role and adds their name to the roles table
- [ ] Confirm the deadline and set dates for each step
- [ ] Agree on the spec, agent and tool formats
- [ ] Write the golden example (clinic appointment system)
- [ ] Book the theory teach-back sessions
- [ ] Set a weekly teach-back time
- [ ] Each part runs on its own
- [ ] Full pipeline runs end to end
- [ ] Benchmark and comparison results ready
- [ ] Section B written, slides done (repo link on page 1 of both the report and slides)
