# public_health / server

**The system behind the service.**

The backend layer of `public_health` — built to manage household identity, coordinate pickup workflows, and propagate operational changes to connected clients.

A focused exploration of API design, authentication, persistence, and real-time communication.

---

### Architecture

**01 — Interface**

REST APIs built with FastAPI define how the mobile application interacts with backend services.

**02 — Identity**

Access and refresh tokens support authenticated sessions and protected operations.

**03 — State**

Firebase provides the persistence layer for application data and pickup-related state.

**04 — Events**

WebSocket connections deliver real-time updates to clients as pickup information changes.

---

### Stack

`Python` / `FastAPI` / `Firebase` / `JWT` / `WebSockets`

---

### Engineering focus

API contracts. Authentication boundaries. Asynchronous communication. State synchronization.

The goal is to understand not just how endpoints work individually, but how the pieces behave together when multiple clients depend on the same evolving state.

---

<text color="secondary" size="sm">PUBLIC HEALTH SYSTEMS · BACKEND ENGINEERING</text>

*Built for coordination. Designed with intent.*

