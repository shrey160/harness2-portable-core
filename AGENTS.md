# Credential privacy

The user explicitly requested that agents not read `.env` after credentials are entered. Treat this restriction as active now.

- Do not open, read, search, hash, display, or copy `.env` or other `.env.*` secret files. `.env.example` is the only exception.
- Exclude secret files from directory-wide content searches, evidence exports, source synchronization, image builds, and archives.
- Applications may load credentials at runtime, but never print or log credential values, dump the environment, or expose keys through errors or artifacts.
- Ask for variable names or configuration locations when needed, never the secret value in chat.

# Current scope

Prioritize execution-core reliability and evidence. Frontend work is deferred at the user's direction. Keep synthetic/offline validation distinct from real model and tool-loop validation. Leave the sibling harness2_capability_lab folder unchanged.
