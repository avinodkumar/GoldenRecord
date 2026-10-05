# ADR 0001 · Fabric-native delivery with a local, tested core

**Status:** Accepted · 2026-09-30

## Context

The brief prescribes the Microsoft Fabric stack. Fabric notebooks are hard to unit-test and need paid
capacity, and Fabric access for the team may take a day or more to arrive.

## Decision

Business logic (standardization, rules, matching, survivorship, evaluation) lives in the `goldenrecord`
Python package, tested locally with pytest and packaged as a wheel for the Fabric Environment. Fabric
notebooks are thin wrappers that handle Spark I/O and call AI Functions.

## Consequences

- The team can build and test from Day 1 without Fabric.
- One implementation of each rule; the local run and Fabric produce the same results.
- The wheel must be rebuilt and republished to the Environment after logic changes.
- AI Functions exist only in Fabric; locally the grey zone is decided by the deterministic score.
