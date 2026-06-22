# Notice

This repository is intentionally focused on the runtime path used by the app:

- `cpp_2048_agent.cpp`
- `cpp_2048_agent.exe`
- `live_agent.py`
- `replay_agent.py`

Old experiment traces, trained models, external references, and unused Python
agents are intentionally excluded because `live_agent.py` does not read them.
The live path calls only:

```text
cpp_2048_agent.exe --choose-board <16 tile values>
```

Development notes and dependency audits are kept in the repository documents.
