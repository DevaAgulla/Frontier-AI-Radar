/**
 * In-memory store for API routes (dummy backend). Replace with DB in production.
 */

import type { Run, Source, Digest } from "./types";
import { DUMMY_RUNS, DUMMY_SOURCES, DUMMY_DIGESTS } from "./dummy-data";

export const runsStore: Run[] = DUMMY_RUNS.map((r) => ({ ...r }));
export const sourcesStore: Source[] = DUMMY_SOURCES.map((s) => ({ ...s }));
export const digestsStore: Digest[] = DUMMY_DIGESTS.map((d) => ({ ...d }));
