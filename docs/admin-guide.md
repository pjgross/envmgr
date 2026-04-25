# EnvManager Admin Guide

## About this guide

This guide is for **Master Admins** standing up new tenants and **Tenant Admins** configuring and operating EnvManager day-to-day. It covers tenant provisioning, user and role management, modelling your platform (systems, subsystems, environments, infrastructure), configuring change kinds and gates, release templates, API keys and webhooks, tenant settings, and import/export. End-user workflows — booking environments, raising change requests, driving releases, reading builds and deployments — live in [`user-guide.md`](user-guide.md). The guide matches the post-Phase-4 product state.

## Table of contents

1. [Introduction](#1-introduction)
2. [Provisioning a new tenant](#2-provisioning-a-new-tenant-master-admin-only)
3. [Onboarding your tenant](#3-onboarding-your-tenant)
4. [Managing users and roles](#4-managing-users-and-roles)
5. [Modelling your platform: systems and subsystems](#5-modelling-your-platform-systems-and-subsystems)
6. [Modelling environments](#6-modelling-environments)
7. [Modelling infrastructure (hosts)](#7-modelling-infrastructure-hosts)
8. [Configuring change kinds and gates](#8-configuring-change-kinds-and-gates)
9. [Release templates](#9-release-templates)
10. [API keys and webhooks](#10-api-keys-and-webhooks)
11. [Tenant settings](#11-tenant-settings)
12. [Import/export](#12-importexport)
13. [Appendix: role permission matrix](#13-appendix-role-permission-matrix)

## 1. Introduction

EnvManager is a multi-tenant test-environment management platform. It maintains an inventory of systems, subsystems, and the environments they run in. It tracks who has booked which environment and when. It records change requests against environments and the gates they must pass. It coordinates releases that group changes for promotion. It ingests CI/CD build and deployment events so each environment shows what is currently deployed.

This guide is for two audiences. **Master Admins** provision new tenants — that one-time task is covered in chapter 2 only. **Tenant Admins** configure and operate a tenant day-to-day, and chapters 3 onward are written for them. End users — anyone booking environments, raising changes, or reading deployment status — should read [`user-guide.md`](user-guide.md) instead.

### The role model

Roles are tenant-scoped: each user has exactly one role within a tenant, and Admin is the senior tenant role. The Master Admin flag is separate from the role and grants cross-tenant access for provisioning and support.

| Role | Typical responsibility |
|------|------------------------|
| Master Admin | Cross-tenant operator who provisions tenants and seeds the first Tenant Admin. |
| Admin | Tenant owner — manages users, models the platform, and configures tenant settings. |
| Release Manager | Plans releases, drives release execution, and signs off gates. |
| Test Manager | Books environments for test campaigns and manages test-related changes. |
| Developer | Raises change requests and reads build and deployment status. |
| Viewer | Read-only access to inventory, bookings, changes, and deployments. |

See ch. 13 (Appendix: role permission matrix) for the full route × role × {read, write} matrix.

### Related documentation

- [`user-guide.md`](user-guide.md) — for end users in an already-provisioned tenant.
- [`../CLAUDE.md`](../CLAUDE.md) — for engineers working on EnvManager itself.
- [`prod architecture.md`](prod%20architecture.md) — for the production architecture.
- The Swagger API reference at `http://localhost:8000/docs` — authoritative for API contracts.

## 2. Provisioning a new tenant *(Master Admin only)*

*To be drafted in Task 3.*

## 3. Onboarding your tenant

*To be drafted in Task 4.*

## 4. Managing users and roles

*To be drafted in Task 5.*

## 5. Modelling your platform: systems and subsystems

*To be drafted in Task 6.*

## 6. Modelling environments

*To be drafted in Task 7.*

## 7. Modelling infrastructure (hosts)

*To be drafted in Task 8.*

## 8. Configuring change kinds and gates

*To be drafted in Task 9.*

## 9. Release templates

*To be drafted in Task 10.*

## 10. API keys and webhooks

*To be drafted in Task 11.*

## 11. Tenant settings

*To be drafted in Task 12.*

## 12. Import/export

*To be drafted in Task 13.*

## 13. Appendix: role permission matrix

*To be drafted in Task 14.*

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
