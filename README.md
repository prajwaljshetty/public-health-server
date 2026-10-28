# public_health

`/ SERVER` &nbsp;·&nbsp; Backend systems

## Behind every request, a system in motion.

The backend powering `public_health` — connecting household identity, pickup operations, persistent state, and real-time communication.

Built around the mechanics that make a connected application work: defined interfaces, controlled access, and state that moves between clients.

---

### System architecture

**01 / Interface**

FastAPI exposes the REST endpoints through which the mobile application interacts with backend services.

**02 / Identity**

Access and refresh tokens support authenticated sessions and access to protected operations.

**03 / State**

Firebase provides persistence for application data and pickup-related state.

**04 / Events**

WebSocket connections carry pickup status updates to connected clients.

---

### Technology

`Python` / `FastAPI` / `Firebase` / `JWT` / `WebSockets`

---

### Beyond the endpoints

An API is only one part of the system.

The engineering challenge lies in how authentication, persistence, and asynchronous communication interact — especially when multiple clients depend on the same evolving state.

This project explores those boundaries through implementation, debugging, and iteration.

---

<text color="secondary" size="sm">SYSTEMS ENGINEERING / BACKEND DEVELOPMENT</text>

*Every moving part has a place.*

