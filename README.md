# Community Water Access Scheduler (CWAS)

A Python-based scheduling system for managing fair access to shared water sources in communities. CWAS helps distribute limited water equitably, reduce conflicts, and ensure transparent financial tracking.

---

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [System Architecture](#system-architecture)
- [Database Schema](#database-schema)
- [User Roles](#user-roles)
- [Configuration](#configuration)
- [Testing](#testing)
- [Contributing](#contributing)
- [Security Features](#security-features)
- [Performance Considerations](#performance-considerations)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Authors](#authors)
- [Acknowledgments](#acknowledgments)
- [References](#references)

---

## Overview

CWAS is designed for communities where multiple households rely on shared resources such as wells, boreholes, and communal taps.  

It provides:
- **Fair Scheduling** — priority-based booking that ensures equitable access  
- **Financial Management** — household account balances and payment tracking  
- **Administrative Oversight** — coordinator and admin control panels  
- **Offline Operation** — runs fully without internet dependency  

### Problem Statement

1 in 4 people worldwide has no access to safe drinking water [(Keim, 2025)](https://www.unicef.ch/en/current/news/2025-08-26/1-4-people-worldwide-still-has-no-access-safe-drinking-water).  
In shared-resource communities, weak management often leads to:
- Long queues and waiting times  
- Household conflicts  
- Wasted capacity  
- Poor financial transparency  

---

## Features

### Authentication & User Management
- Multi-role login (Household, Coordinator, Administrator)  
- PBKDF2-HMAC-SHA256 password hashing with salt  
- Email validation & account verification  
- Role-based access control  

### Household Management
- Register households with priority levels  
- Wallet balance management  
- View booking history and receipts  
- Update profiles  

### Water Source Management
- Add and configure sources dynamically  
- Manage operating hours and capacity  
- Adjust pricing and access rules  
- Schedule maintenance  

### Booking System
- Guided time-slot selection  
- Real-time availability checks  
- Balance-based payment validation  
- Coordinator approval workflow  

### Financial Management
- Account balances and transactions  
- Auto-generated receipts  
- Revenue reporting and audit trail  
- CSV exports  

### Reporting & Analytics
- Daily usage summaries  
- Revenue reports  
- Household activity reports  
- Source performance  

### Notifications
- Booking status updates  
- Maintenance alerts  
- Read/unread tracking  

---

## Installation

### Prerequisites
- Python **3.7+**  

### Clone Repository
```
git clone https://github.com/banituze/cwas.git
cd cwas
````

### Install Dependencies

```
# Uses only Python standard library
python --version  # Ensure Python 3.7+
```

### Database Initialization

The database initializes automatically on first run.

---

## Usage

### Quick Start

```
python cwas.py
```

### First-Time Setup

1. Run `python cwas.py`
2. Register as **System Administrator** with verification code: `cwas2025`
3. Create water sources and generate time slots
4. Register coordinators
5. Register households and begin booking

### Default Verification Codes

* Admin: `cwas2025`
* Coordinator: `cwas2005`

---

## System Architecture

### Monolithic Design

CWAS is implemented as a single Python file (`cwas.py`):

```
cwas.py
├── Utilities (clear_screen, hashing, validation)
├── DatabaseManager (connection, schema setup)
├── AuthenticationManager (registration, login)
└── WaterSchedulerApp (menus, bookings, reports, admin ops)
```

### Key Components

* Core utilities & security functions
* Database schema & connection manager
* Authentication & user management
* Main CLI logic with role-based menus

---

## Database Schema

**Tables (auto-created):**

* `users` — authentication & roles
* `households` — family details & balances
* `water_sources` — configuration & pricing
* `time_slots` — slots & availability
* `bookings` — reservations & status
* `receipts` — transactions
* `notifications` — messages

## User Roles

### Household

* Make bookings
* View history and receipts
* Manage balance and profile
* Receive notifications

### Coordinator

* Approve/deny bookings
* Manage sources and slots
* Generate reports
* Send notifications

### Administrator

* Manage all users
* Adjust pricing and settings
* Perform database maintenance
* Access full reports and backups

---

## Configuration

Default values (editable in `cwas.py`):

* Water pricing: `$0.05 per 100L`
* Slot duration: `1 hour`
* Household starting balance: `$50.00`
* Verification codes: `cwas2025` (admin), `cwas2005` (coordinator)

---

## Testing

### Manual Testing Checklist

* Authentication flow (register, login, role menus)
* Booking workflow (household booking + coordinator approval)
* Finance operations (add funds, booking charges, receipts)
* Reports (daily usage and revenue summaries)

---

## Contributing

1. Fork repository
2. Create branch: `git checkout -b feature-name`
3. Make and test changes in `cwas.py`
4. Commit: `git commit -m 'Add feature'`
5. Push: `git push origin feature-name`
6. Open pull request

**Guidelines:**

* Follow PEP 8
* Use docstrings
* Parameterize SQL queries
* Test features manually

---

## Security Features

* PBKDF2-HMAC-SHA256 password hashing with salt
* Parameterized SQL queries
* Role-based menu enforcement
* Transaction logging & audit trail

---

## Performance Considerations

* Optimized queries with constraints
* Works offline (no internet needed)
* Handles 100–1000 households
* Lightweight single-file implementation

---

## Troubleshooting

* **Database Locked** — ensure only one instance is running; check permissions
* **Import Errors** — verify Python 3.7+
* **Authentication Failures** — confirm verification codes and user status

For unresolved issues, open a GitHub issue with details.

---

## License

This project is licensed under the MIT License — see the [LICENSE](https://github.com/banituze/cwas/blob/master/LICENSE) file for details.

---

## Authors

* [**Winebald Banituze**](https://github.com/banituze) 
* [**Arjuna Caleb Gyan**](https://github.com/AR-JUNA) 
* [**Olais Julius Laizer**](https://github.com/Olais11) 
* [**Sylvie Umutoni Rutaganira**](http://github.com/Umutoni2) 

## Acknowledgments

* African Leadership College of Higher Education
* Faculty mentors and peer collaborators
* Research on water access and digital payment systems

---

## References

Keim, J. (2025). *1 in 4 people worldwide has no access to safe drinking water.* unicef.ch.  
https://www.unicef.ch/en/current/news/2025-08-26/1-4-people-worldwide-still-has-no-access-safe-drinking-water
