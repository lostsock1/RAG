import { describe, expect, test, vi } from "vitest"

import { listDocuments } from "../src/api"

describe("public API client", () => {
  test("listDocuments calls the public API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    })

    await listDocuments(fetchMock, {
      baseUrl: "http://localhost:8000",
      token: "token",
    })

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/documents",
      expect.objectContaining({ method: "GET" }),
    )
  })
})
