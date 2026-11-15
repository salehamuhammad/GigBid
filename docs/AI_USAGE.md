# AI assistance

OpenAI Codex inspected the assignment and workspace, changed the evaluation runners, added the degraded-mode Playwright case, corrected trace redaction and added Docker build exclusions. The developer should review these changes and be able to explain the evaluation design and approval flow in the viva.

During verification, Codex caught an invalid retrieval setup. A run switched to the local NumPy backend while retaining index metadata produced for Qdrant. Dense retrieval returned no results. The valid benchmark uses the existing BGE vectors in Qdrant, and the mixed-backend diagnostic is excluded from the reported results.
