# Employee Attendance & Analytics API

A robust backend service built with **Python**, **FastAPI**, and **MongoDB (Motor)** for tracking employee attendance, enforcing operational business rules, handling manual administrative corrections with secure audit trails, and generating workforce metrics via MongoDB aggregation pipelines.

---

## Features

* **Punch-In & Punch-Out Operations:** Record shift starts and ends with built-in validation rules (e.g., prevents duplicate active check-ins).
* **Manual Corrections & Audit Trail:** Allows administrators to modify past punch times with a mandatory reason, automatically logging the previous state, new state, timestamp, and admin ID.
* **Aggregated Analytics:** Uses native MongoDB aggregation pipelines to calculate total shifts, total hours worked, and averages per employee and department.
* **Async Performance:** Powered by FastAPI and Motor for non-blocking asynchronous database operations.

---

## Project Structure

```text
employee_attendance_project/
│
├── app/
│   ├── __init__.py
│   └── main.py
│
├── requirements.txt
└── README.md
