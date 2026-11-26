/** API client tests. fetch and XMLHttpRequest are MOCKED, so no network is used. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeXHR, installFakeXhr } from "../test/helpers";
import { ApiError, createHttpApi, extensionFor, httpErrorMessage } from "./api";

const BASE = "http://api.test";

function stubFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("JSON requests (mocked fetch)", () => {
  it("builds the URL from the base address and parses the response", async () => {
    const fetchMock = stubFetch(200, [{ id: "i1" }]);
    const result = await createHttpApi(BASE).listInterviews();
    expect(result).toEqual([{ id: "i1" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/interviews");
  });

  it("posts the session start request as JSON", async () => {
    const fetchMock = stubFetch(201, { session_id: "s1" });
    await createHttpApi(BASE).startSession({
      interview_id: "i1", candidate_name: "A", candidate_email: "a@b.co", consent: true,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/sessions");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      interview_id: "i1", candidate_name: "A", candidate_email: "a@b.co", consent: true,
    });
  });

  it("encodes the session id in the URL", async () => {
    const fetchMock = stubFetch(200, {});
    await createHttpApi(BASE).getSession("a/b");
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/sessions/a%2Fb");
  });

  it("turns HTTP errors into ApiError with the server's message", async () => {
    stubFetch(409, { detail: "A session already exists for this email and interview." });
    await expect(createHttpApi(BASE).listInterviews()).rejects.toMatchObject({
      kind: "http", status: 409, message: "A session already exists for this email and interview.",
    });
  });

  it("reads FastAPI validation error lists", async () => {
    stubFetch(422, { detail: [{ msg: "consent must be given" }, { msg: "bad email" }] });
    await expect(createHttpApi(BASE).listInterviews()).rejects.toMatchObject({
      status: 422, message: expect.stringContaining("consent must be given; bad email"),
    });
  });

  it("reports a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(createHttpApi(BASE).listInterviews()).rejects.toMatchObject({ kind: "network" });
  });

  it("reports a timeout when the request is aborted", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new DOMException("aborted", "AbortError"); }));
    await expect(createHttpApi(BASE).listInterviews()).rejects.toMatchObject({ kind: "timeout" });
  });
});

describe("audio upload (mocked XMLHttpRequest)", () => {
  let Xhr: typeof FakeXHR;
  beforeEach(() => {
    Xhr = installFakeXhr();
  });
  afterEach(() => {
    Xhr.instances = [];
  });

  const audio = () => new Blob(["abc"], { type: "audio/webm;codecs=opus" });
  const receipt = { response_id: "r1", question_id: "q1", transcription_status: "pending", size_bytes: 3, content_type: "audio/webm" };

  it("sends multipart form data to the responses endpoint", async () => {
    const promise = createHttpApi(BASE).uploadResponse({
      sessionId: "s1", questionId: "q1", audio: audio(), durationSeconds: 2.46,
    });
    const xhr = Xhr.instances[0];
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("http://api.test/api/sessions/s1/responses");
    expect(xhr.body).toBeInstanceOf(FormData);
    expect(xhr.body?.get("question_id")).toBe("q1");
    expect(xhr.body?.get("duration_seconds")).toBe("2.5");
    const file = xhr.body?.get("audio") as File;
    expect(file.name).toBe("answer.webm");
    expect(file.type).toBe("audio/webm;codecs=opus");
    expect(file.size).toBe(3);
    xhr.respond(201, receipt);
    await expect(promise).resolves.toEqual(receipt);
  });

  it("reports upload progress between 0 and 1", async () => {
    const onProgress = vi.fn();
    const promise = createHttpApi(BASE).uploadResponse({
      sessionId: "s1", questionId: "q1", audio: audio(), durationSeconds: 1, onProgress,
    });
    Xhr.instances[0].progress(50, 200);
    expect(onProgress).toHaveBeenLastCalledWith(0.25);
    Xhr.instances[0].respond(201, receipt);
    await promise;
    expect(onProgress).toHaveBeenLastCalledWith(1);
  });

  it.each([
    [413, "too large"],
    [415, "not supported"],
    [500, "server had a problem"],
  ])("maps HTTP %i to a friendly message", async (status: number, fragment: string) => {
    const promise = createHttpApi(BASE).uploadResponse({
      sessionId: "s1", questionId: "q1", audio: audio(), durationSeconds: 1,
    });
    Xhr.instances[0].respond(status, { detail: "ignored" });
    await expect(promise).rejects.toMatchObject({ kind: "http", status, message: expect.stringContaining(fragment) });
  });

  it("keeps the server's text for 409 conflicts", async () => {
    const promise = createHttpApi(BASE).uploadResponse({
      sessionId: "s1", questionId: "q1", audio: audio(), durationSeconds: 1,
    });
    Xhr.instances[0].respond(409, { detail: "This question has already been answered." });
    await expect(promise).rejects.toMatchObject({ status: 409, message: "This question has already been answered." });
  });

  it("reports network errors and timeouts", async () => {
    const first = createHttpApi(BASE).uploadResponse({ sessionId: "s", questionId: "q", audio: audio(), durationSeconds: 1 });
    Xhr.instances[0].onerror?.();
    await expect(first).rejects.toMatchObject({ kind: "network" });

    const second = createHttpApi(BASE).uploadResponse({ sessionId: "s", questionId: "q", audio: audio(), durationSeconds: 1 });
    Xhr.instances[1].ontimeout?.();
    await expect(second).rejects.toMatchObject({ kind: "timeout" });
  });

  it("sets a request timeout and supports cancelling", async () => {
    const controller = new AbortController();
    const promise = createHttpApi(BASE).uploadResponse({
      sessionId: "s", questionId: "q", audio: audio(), durationSeconds: 1, signal: controller.signal,
    });
    expect(Xhr.instances[0].timeout).toBeGreaterThan(0);
    controller.abort();
    expect(Xhr.instances[0].aborted).toBe(true);
    await expect(promise).rejects.toMatchObject({ kind: "aborted" });
  });
});

describe("helpers", () => {
  it("picks file extensions from MIME types", () => {
    expect(extensionFor("audio/webm;codecs=opus")).toBe("webm");
    expect(extensionFor("audio/mp4")).toBe("mp4");
    expect(extensionFor("audio/ogg")).toBe("ogg");
    expect(extensionFor("application/x-unknown")).toBe("bin");
  });
  it("describes status codes", () => {
    expect(httpErrorMessage(404)).toContain("could not be found");
    expect(new ApiError("http", "x", 400).status).toBe(400);
  });
});
