# PROJET.HR

PROJET.HR is an AI-assisted recruitment automation project designed to streamline parts of the job discovery and application workflow.

This public repository is a curated showcase version of the project. It highlights the main architecture, automation logic, and backend interface without exposing the full internal system, private data, or confidential configuration.

## What The Project Does

The goal of PROJET.HR is to support a semi-automated application pipeline by combining:

- job source retrieval
- ATS-aware application logic
- backend workflow orchestration
- configurable platform handling
- AI-assisted field interpretation and answer generation

In practice, the system is designed to:
- discover job opportunities from selected sources
- organize application-related data
- route jobs through different ATS flows
- help automate repetitive form-filling tasks and the whole application process for users
- provide a backend interface for monitoring and control

## Why I Built It

I built this project to explore how AI and browser automation can be applied to real recruitment workflows. The project sits at the intersection of:

- automation engineering
- backend architecture
- ATS workflow design
- applied AI for structured task execution

## Repository Scope

This repository is intended as a technical and product showcase.

Some internal modules, private datasets, credentials, personal documents, and platform-specific implementation details are intentionally excluded or simplified in the public version.

## Main Files

### `backend.py`
Main backend service for the project.

This file represents the orchestration layer of the application. It manages backend routes, state, scheduling behavior, and the connection between the user-facing control layer and the automation workflows.

### `backend.js`
Frontend interaction layer for the backend dashboard.

This file helps power the interface behavior and shows how the backend can be controlled from a browser-based UI.

### `generalats.py`
Core generic ATS automation logic.

This is one of the most important technical files in the project. It contains the reusable logic used to interpret and interact with application forms across different ATS environments, including field detection, intent mapping, and AI-assisted answering flows.

(For some more complex ATS (application tracking system) like Workday, Successfactor or Greenhouse, I have built a custom file, as they are different and more complex as other ats to deal with. 

### `scanners/generic_career_scanner.py`
Generic job source scanner.

This module demonstrates how the system identifies and processes career pages, extracts job links, and prepares them for downstream application logic.

### `retrieval_sources.py`
Configuration and source-management layer.

This file shows how job sources are structured, normalized, stored, and managed in a reusable way.

### `main.py`
Entry-point and ATS dispatcher.

This file demonstrates the high-level routing logic used to direct a given application URL toward the appropriate automation handler.

### `WHITEPAPER.md`


This file explains the main architecture of my program and how the whole program functions

### `.png`

4 Screenshots of the backend.py program, illustrating how the backend of the platform works.

## Notes

- Some parts of the original project are intentionally omitted for privacy and security reasons.
- This codebase is presented as a demonstration of architecture, experimentation, and applied automation design.

## Status

Active prototype / ongoing development.
