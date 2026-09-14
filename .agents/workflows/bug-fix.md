# Bug fix

1. Reproduce the bug locally with a targeted script or test case.
2. Isolate the root cause using systematic debugging rather than addressing surface symptoms.
3. Add a reproducible regression test under `tests/`.
4. Implement the minimal fix addressing the root defect.
5. Run the complete test suite: `pytest -v tests`.
6. Confirm no edge-case regressions or unhandled loop/collision conditions.
