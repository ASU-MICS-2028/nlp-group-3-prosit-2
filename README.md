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