# EnvManager User Guide

## About this guide

This guide is for **Release Managers, Test Managers, Developers, and Viewers** using EnvManager day-to-day inside an already-provisioned tenant. It covers logging in, the dashboard, core concepts, browsing systems and environments, booking environments, raising change requests, working with releases, reading builds and deployments, topology and dependency views, and a small cookbook of common workflows. Platform setup tasks — provisioning tenants, managing users, modelling systems and environments, configuring change kinds, release templates, API keys, and import/export — live in [`admin-guide.md`](admin-guide.md).

## Table of contents

1. [Introduction](#1-introduction)
2. [Logging in and the dashboard](#2-logging-in-and-the-dashboard)
3. [Concepts in 5 minutes](#3-concepts-in-5-minutes)
4. [Browsing systems and environments](#4-browsing-systems-and-environments)
5. [Booking environments](#5-booking-environments)
6. [Raising change requests](#6-raising-change-requests)
7. [Working with releases](#7-working-with-releases)
8. [Builds and deployments](#8-builds-and-deployments)
9. [Topology and dependency views](#9-topology-and-dependency-views)
10. [Tips and common workflows](#10-tips-and-common-workflows)
11. [Appendix: status lifecycles cheat sheet](#11-appendix-status-lifecycles-cheat-sheet)

## 1. Introduction

EnvManager keeps track of the systems, environments, and release work going on across your tenant. From the UI you'll browse the systems and environments your team owns, book environments through a calendar, raise *change requests* and group them into *releases*, and watch a feed of CI builds and deployments as they land. The view is single-tenant: you only see data belonging to the tenant you're signed into.

**Who this guide is for.** Day-to-day end users — **Release Managers** planning and shipping releases, **Test Managers** booking environments for test cycles, **Developers** raising change requests and watching deployments, and **Viewers** reading status and history. Most actions in the UI are open to anyone signed into your tenant; senior responsibilities (managing other users, configuring tenant-level settings) sit with **Admin**. For anything setup-related, see [`admin-guide.md`](admin-guide.md).

**How to read this guide.** Three orientation pointers:

- For the big picture, read [ch. 3 (Concepts in 5 minutes)](#3-concepts-in-5-minutes) first — it diagrams how the entities fit together.
- For day-to-day workflows, [ch. 5 (Booking environments)](#5-booking-environments) and [ch. 7 (Working with releases)](#7-working-with-releases) are the meatiest chapters.
- For quick recipes, [ch. 10 (Tips and common workflows)](#10-tips-and-common-workflows) has cookbook-style scenarios.

If you're standing up a new tenant or modelling your platform, see [`admin-guide.md`](admin-guide.md). If you're working on EnvManager itself, see [`../CLAUDE.md`](../CLAUDE.md).

## 2. Logging in and the dashboard

*To be drafted in Task 16.*

## 3. Concepts in 5 minutes

*To be drafted in Task 17.*

## 4. Browsing systems and environments

*To be drafted in Task 18.*

## 5. Booking environments

*To be drafted in Task 19.*

## 6. Raising change requests

*To be drafted in Task 20.*

## 7. Working with releases

*To be drafted in Task 21.*

## 8. Builds and deployments

*To be drafted in Task 22.*

## 9. Topology and dependency views

*To be drafted in Task 23.*

## 10. Tips and common workflows

*To be drafted in Task 24.*

## 11. Appendix: status lifecycles cheat sheet

*To be drafted in Task 25.*

---

> **Conventions:** Routes shown in code (`/releases/:id`); UI labels in *italics*; API endpoints in code blocks with method (`POST /api/v1/webhooks/deployment`); role badges on chapter headings; "Not yet available" callouts use blockquote with `> **Not yet available:**` prefix.
