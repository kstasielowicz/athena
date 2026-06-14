# ATHENA — Strength & Calisthenics Intelligence Ecosystem (MVP)

ATHENA is an advanced, data-driven training, biometric logging, and athletic lifestyle tracking platform engineered specifically for strength lifters, streetlifting competitors, and calisthenics practitioners. 

Named after the ancient Greek goddess of wisdom and systematic execution, the platform’s core philosophy is to transition athletes away from blind, uncalculated training habits. Instead, ATHENA provides users with data-driven logic, calculated recovery indices, and gamified mastery frameworks.

This repository contains a fully functional, full-stack Minimum Viable Product (MVP) built using **Python, Flask, and SQLite3**, wrapped in a responsive frontend layout designed to prevent performance bottlenecks and visual instabilities.

---

## 🧭 Technical Architecture & Data Workflow

The application operates on a strict separation of concerns, ensuring high data density and fast processing speeds.


### 1. Frontend Execution Shell (`/templates`)
* **Reusable Templating (Jinja2):** Core navigation sidebars, athlete dashboards, and global headers are split into isolated server-side snippets to maximize code reusability and component structure.
* **Layout Shift Prevention:** Structured using a flexible, modern **Full-Width Stacked Row** grid layout. Content expansions and technical details expand down vertically, ensuring complete visual stability across mobile viewports and desktop monitors.
* **Async Event Handling (Vanilla JS):** Uses highly targeted client-side event listeners to process dynamic elements, micro-interactions, and instant content updates without forcing costly full-page browser refreshes.

### 2. Backend Processing Core & Database
* **Flask Runtime (Python):** Handles application routing rules, form payload data parsing, parameters verification, and sports-science algorithms.
* **SQLite3 Relational Database:** Manages historical logs, calculated strength progressions, user states, and unlocked badges across clean, structured database tables.

---

## 🖥️ System Blueprint & Module Breakdown

The application is structured around specific functional views, each handling a dedicated part of the athlete’s data profile:

### 1. Athlete Core & Gamification Matrix
* **Dashboard (`dashboard.html`):** The central hub displaying the **ATHENA Score** (a dynamic 0-100% daily readiness metric calculated by balancing recent workouts against lifestyle logs), weekly summary cards, and active **Daily Missions (Quests)**.
* **Athlete Profile (`athlete_profile.html`):** Works like an RPG character sheet. Tracks unified profile levels, **Experience Points (XP)**, and maps athletic data into five live character attributes: *Strength, Skill, Recovery, Consistency, and Power*. Includes personalization fields for weight, height, and manual liftoff metrics.
* **Goals & Challenges (`goals.html`):** A practical setup where users define numeric targets and metrics. The system dynamically monitors inputs and generates live progress bars and permanently unlocks rare/epic achievement badges for consistency.

### 2. Training Telemetry & Skill Systems
* **Workouts Module (`workouts.html`):** The master log displaying historical workout timelines sorted by date. Features a **Hevy API Import Simulation**—a blueprint routing script prepared to automatically map and ingest training payloads from the external *Hevy* fitness application.
* **Exercise Library (`exercises.html`):** A custom database repository where users can edit movements, create custom compound exercises, define target muscles, and track weight progression or volume charts.
* **Skill Trees 2.0 (`skills.html`):** A dedicated calisthenics skill-tree management system. It breaks down complex movements (like *Muscle Ups* or *Human Flags*) into precise, step-by-step **Progression Nodes**. Features an **Evidence Upload Form** directly inside the layout to back up unlocked nodes with image proof and execution notes.

### 3. Analytics, Intelligence & Business Strategy
* **RIS Lab (`ris_lab.html`):** An index computer executing the 2025 *Relative Index for Streetlifting* metrics. It calculates an athlete's true strength relative to their size by comparing total payload outputs against non-linear bodyweight expected curves. Supports **ALL-4** and **UPPER** test configurations and saves data to a local timeline.
* **Recovery Center (`recovery_center.html`):** Tracks daily biometric parameters including sleep hours, baseline energy, stress markers, and muscle soreness logs to update the global dashboard algorithms.
* **Athlete Intelligence (`intelligence.html`):** An educational knowledge base running dynamic sports-science pills. Tapping on concepts like *RPE/RIR Intensity Scales* or *Deload Frameworks* instantly injects coaching definitions using client-side JavaScript.
* **Coaching Marketplace (`coaching_locked.html`):** A premium, locked monetization preview. It maps out a future decentralized commercial roadmap where independent trainers can join the platform and distribute custom programs via 3 subscription tiers (**Tier 1, 2, and 3**).
* **Architecture Info (`architecture_info.html`):** System manual detailing frontend/backend specifications alongside the **Product Identity & Mythology Genesis** that outlines why the application was named ATHENA.

---

## 🔄 The Data Lifecycle Loop

Every transactional event inside the application utilizes a specific, closed data lifecycle loop:

1. **Capture:** The athlete submits inputs via a responsive frontend HTML5 form or an interactive JavaScript grid element.
2. **Transmit:** Web triggers bundle variables into an HTTP POST payload directed to the backend endpoints.
3. **Compute:** The Flask controller captures the payload, executes corresponding algorithms (such as the RIS index calculation, Brzycki equation, or XP level curve checks), and formats a parameterized SQL call.
4. **Persist:** The system performs a transactional write, committing the data into the local SQLite3 database file.
5. **Update:** The Jinja2 templating engine handles server-side rendering, dynamically updating the tracking bars and visual numbers on the user's interface with zero visual friction.

---

## 🚀 Future Development Roadmap
* **Production API Hooks:** Transitioning the *Hevy Import* system from a sandboxed demo script into a production OAuth2 API connection.
* **Drag-and-Drop Program Builder:** Activating the interactive routine builder templates to support customizable, multi-week workout calendar generation.
* **Multi-Tenant Relational Schema:** Expanding database foreign keys to map separate athlete records directly to verified personal trainer rosters.
