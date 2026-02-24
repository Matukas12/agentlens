/* ── Analytics — sessionsOverTime returns most recent 90 days (#19) ── */

let mockDb;
jest.mock("../db", () => ({
  getDb: () => {
    if (!mockDb) {
      const Database = require("better-sqlite3");
      mockDb = new Database(":memory:");
      mockDb.pragma("journal_mode = WAL");
      mockDb.pragma("foreign_keys = ON");
      mockDb.exec(`
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY,
          agent_name TEXT NOT NULL DEFAULT 'default-agent',
          started_at TEXT NOT NULL,
          ended_at TEXT,
          metadata TEXT DEFAULT '{}',
          total_tokens_in INTEGER DEFAULT 0,
          total_tokens_out INTEGER DEFAULT 0,
          status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS events (
          event_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          event_type TEXT NOT NULL DEFAULT 'generic',
          timestamp TEXT NOT NULL,
          input_data TEXT,
          output_data TEXT,
          model TEXT,
          tokens_in INTEGER DEFAULT 0,
          tokens_out INTEGER DEFAULT 0,
          tool_call TEXT,
          decision_trace TEXT,
          duration_ms REAL,
          FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
      `);
    }
    return mockDb;
  },
}));

const express = require("express");
const request = require("supertest");
const analyticsRouter = require("../routes/analytics");

function createApp() {
  const app = express();
  app.use(express.json());
  app.use("/analytics", analyticsRouter);
  return app;
}

// Helper: insert a session on a given date
function insertSession(id, date) {
  mockDb.prepare(
    `INSERT INTO sessions (session_id, agent_name, started_at, status, total_tokens_in, total_tokens_out)
     VALUES (?, 'test-agent', ?, 'completed', 100, 50)`
  ).run(id, `${date}T12:00:00Z`);
}

// Helper: generate a date string N days before a base date
function daysAgo(n, base = new Date("2026-01-01")) {
  const d = new Date(base);
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

beforeAll(() => {
  // Trigger lazy initialization of mockDb
  require("../db").getDb();
});

beforeEach(() => {
  if (mockDb) {
    mockDb.exec("DELETE FROM events");
    mockDb.exec("DELETE FROM sessions");
  }
});

afterAll(() => {
  if (mockDb) mockDb.close();
});

describe("GET /analytics — sessionsOverTime", () => {
  test("returns data in chronological (ASC) order for the frontend", async () => {
    // Insert sessions on 3 known dates (out of order to be thorough)
    insertSession("s1", "2025-12-01");
    insertSession("s2", "2025-12-15");
    insertSession("s3", "2025-12-10");

    const app = createApp();
    const res = await request(app).get("/analytics").expect(200);

    const days = res.body.sessions_over_time.map((r) => r.day);
    // Should be sorted chronologically (oldest first)
    expect(days).toEqual([...days].sort());
  });

  test("limits to 90 entries even when more days exist", async () => {
    // Insert 100 distinct days of sessions
    for (let i = 0; i < 100; i++) {
      insertSession(`s-${i}`, daysAgo(i));
    }

    const app = createApp();
    const res = await request(app).get("/analytics").expect(200);

    expect(res.body.sessions_over_time.length).toBeLessThanOrEqual(90);
  });

  test("returns the MOST RECENT 90 days, not the oldest (#19)", async () => {
    // Insert 100 distinct days of sessions — days 0..99 ago from 2026-01-01
    for (let i = 0; i < 100; i++) {
      insertSession(`s-${i}`, daysAgo(i));
    }

    const app = createApp();
    const res = await request(app).get("/analytics").expect(200);

    const days = res.body.sessions_over_time.map((r) => r.day);

    // The most recent day (daysAgo(0) = "2026-01-01") must be included
    expect(days).toContain(daysAgo(0));

    // The oldest day (daysAgo(99) = "2025-09-24") must NOT be included
    // because we only keep the 90 most recent
    expect(days).not.toContain(daysAgo(99));
    expect(days).not.toContain(daysAgo(98));
    expect(days).not.toContain(daysAgo(97));

    // The 90th most recent day (daysAgo(89)) SHOULD be included
    expect(days).toContain(daysAgo(89));

    // Verify chronological order (ASC) for the chart
    expect(days).toEqual([...days].sort());
  });
});
