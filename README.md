# public_health

`/ SERVER` · Backend Systems

## Behind every request, a system in motion.

The backend powering `public_health` — connecting household identity, pickup workflows, persistent state, and real-time communication.

Built around the mechanics of a connected application: well-defined interfaces, authenticated access, and state that flows between services and clients.

---

### System architecture

**01 / Interface**

FastAPI exposes REST endpoints for communication between the mobile application and backend services.

**02 / Identity**

JWT-based authentication manages access to protected operations and authenticated sessions.

**03 / Persistence**

Firebase stores application data and pickup-related state, providing continuity across operations.

**04 / Real-time events**

WebSocket connections deliver pickup status updates to connected clients as the system evolves.

---

### The stack

`Python` · `FastAPI` · `Firebase` · `JWT` · `WebSockets`

---

### Beyond the endpoints

An API is only the entry point.

The real engineering lies in how authentication, persistence, and asynchronous communication work together — especially when multiple clients depend on the same evolving state.

This project is where I explore those boundaries through implementation, debugging, and iteration.

---

`BACKEND ENGINEERING` / `SYSTEM DESIGN` / `REAL-TIME COMMUNICATION`

*Every moving part has a place.*
