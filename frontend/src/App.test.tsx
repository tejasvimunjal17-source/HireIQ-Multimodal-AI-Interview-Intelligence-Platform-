/**
 * Whole-app flow tests with React Testing Library.
 * MOCKED: the backend API (createFakeApi), the microphone and MediaRecorder (installFakeMedia).
 * These tests verify UI logic. They are NOT real microphone or real backend tests.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError } from "./services/api";
import { createFakeApi, installFakeMedia, installNoMediaSupport, makeSession } from "./test/helpers";
import type { UploadInput } from "./types/interview";

type Api = ReturnType<typeof createFakeApi>;
type User = ReturnType<typeof userEvent.setup>;

function setup(api: Api = createFakeApi(), media: Parameters<typeof installFakeMedia>[0] = {}) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fakeMedia = installFakeMedia(media);
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  render(<App api={api} demoMode={false} />);
  return { api, user, fakeMedia };
}

/** With a single available interview the form selects it automatically. */
async function startInterview(user: User, firstScreen: RegExp = /Question 1 of 2/) {
  await screen.findByRole("heading", { name: /Welcome to your AI-assisted interview/ });
  await screen.findByText("Backend Engineer Interview");
  await user.type(screen.getByLabelText("Full name"), "  Asha Verma ");
  await user.type(screen.getByLabelText("Email address"), "asha@example.com");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Start interview" }));
  await screen.findByText(firstScreen);
}

async function recordAnswer(user: User, seconds = 2) {
  await user.click(screen.getByRole("button", { name: "Start recording" }));
  await screen.findByText("Recording");
  act(() => void vi.advanceTimersByTime(seconds * 1000));
  await user.click(screen.getByRole("button", { name: "Stop" }));
  await screen.findByLabelText("Preview of your recorded answer");
}

beforeEach(() => {
  window.sessionStorage.clear();
});

describe("welcome screen", () => {
  it("shows branding, instructions and the interview list", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: /Welcome to your AI-assisted interview/ })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent("HireIQ");
    expect(screen.getByRole("heading", { name: "Before you begin" })).toBeInTheDocument();
    expect(await screen.findByText("Backend Engineer Interview")).toBeInTheDocument();
    expect(screen.getByText(/2 questions/)).toBeInTheDocument();
  });

  it("validates the form before calling the backend", async () => {
    const { api, user } = setup();
    await screen.findByText("Backend Engineer Interview");
    await user.click(screen.getByRole("button", { name: "Start interview" }));
    expect(await screen.findByText("Please enter your full name.")).toBeInTheDocument();
    expect(screen.getByText("Please enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("You need to agree before the interview can start.")).toBeInTheDocument();
    expect(api.startSession).not.toHaveBeenCalled();
  });

  it("sends trimmed details and consent to the backend", async () => {
    const { api, user } = setup();
    await startInterview(user);
    expect(api.startSession).toHaveBeenCalledWith({
      interview_id: "int-1", candidate_name: "Asha Verma", candidate_email: "asha@example.com", consent: true,
    });
    expect(window.sessionStorage.getItem("hireiq.sessionId")).toBe("sess-1");
  });

  it("shows an error if the interview cannot be started", async () => {
    const api = createFakeApi({ startSession: vi.fn().mockRejectedValue(new ApiError("http", "A session already exists for this email and interview.", 409)) });
    const { user } = setup(api);
    await screen.findByText("Backend Engineer Interview");
    await user.click(screen.getByRole("radio"));
    await user.type(screen.getByLabelText("Full name"), "Asha");
    await user.type(screen.getByLabelText("Email address"), "asha@example.com");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Start interview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A session already exists");
    expect(screen.getByRole("button", { name: "Start interview" })).toBeEnabled();
  });

  it("offers a retry when interviews cannot be loaded", async () => {
    const listInterviews = vi.fn().mockRejectedValueOnce(new ApiError("network", "Cannot reach the server.")).mockResolvedValue([{
      id: "int-1", title: "Backend Engineer Interview", description: null, interview_type: "mixed", question_count: 2, total_time_limit_seconds: null,
    }]);
    const { user } = setup(createFakeApi({ listInterviews }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Backend Engineer Interview")).toBeInTheDocument();
  });

  it("warns when the browser cannot record", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installNoMediaSupport();
    render(<App api={createFakeApi()} demoMode={false} />);
    expect(await screen.findByText("This browser cannot record audio")).toBeInTheDocument();
  });

  it("shows the demo banner only in demo mode", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installFakeMedia();
    render(<App api={createFakeApi()} demoMode />);
    expect(await screen.findByRole("note")).toHaveTextContent(/DEMO MODE/);
  });
});

describe("interview questions and progress", () => {
  it("shows the first question, its type and progress", async () => {
    const { user } = setup();
    await startInterview(user);
    expect(screen.getByText(/Explain what an index does/)).toBeInTheDocument();
    expect(screen.getByText("Technical")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Interview progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "2");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("runs the interview timer", async () => {
    const { user } = setup();
    await startInterview(user);
    act(() => void vi.advanceTimersByTime(5000));
    expect(screen.getByLabelText(/Time elapsed 00:0[5-6]/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Time left 09:5/)).toBeInTheDocument();
  });
});

describe("recording controls", () => {
  it("shows recording status, pause/resume and stop", async () => {
    const { user } = setup();
    await startInterview(user);
    await user.click(screen.getByRole("button", { name: "Start recording" }));
    expect(await screen.findByText("Recording")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByText("Paused")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Resume" }));
    expect(screen.getByText("Recording")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("previews the recording and lets the candidate record again", async () => {
    const { user } = setup();
    await startInterview(user);
    await recordAnswer(user);
    expect(screen.getByLabelText("Preview of your recorded answer")).toHaveAttribute("src", "blob:fake-preview");
    await user.click(screen.getByRole("button", { name: "Record again" }));
    expect(screen.queryByLabelText("Preview of your recorded answer")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start recording" })).toBeEnabled();
  });

  it("stops by itself at the question time limit", async () => {
    const api = createFakeApi({
      startSession: vi.fn(async () => makeSession({
        questions: [
          { id: "q1", position: 1, question_type: "technical", time_limit_seconds: 3, text: "Short question" },
          { id: "q2", position: 2, question_type: "behavioral", time_limit_seconds: 3, text: "Second" },
        ],
      })),
    });
    const { user } = setup(api);
    await startInterview(user);
    await user.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByText("Recording");
    act(() => void vi.advanceTimersByTime(3600));
    expect(await screen.findByLabelText("Preview of your recorded answer")).toBeInTheDocument();
  });

  it("locks navigation while a recording is waiting to be submitted", async () => {
    const { user } = setup();
    await startInterview(user);
    await recordAnswer(user);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByText(/Submit this answer or choose/)).toBeInTheDocument();
  });
});

describe("recording problems", () => {
  it("explains a denied microphone and offers Try again", async () => {
    const { user } = setup(createFakeApi(), { error: "NotAllowedError" });
    await startInterview(user);
    await user.click(screen.getByRole("button", { name: "Start recording" }));
    expect(await screen.findByText(/Microphone access was blocked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("explains a missing microphone", async () => {
    const { user } = setup(createFakeApi(), { error: "NotFoundError" });
    await startInterview(user);
    await user.click(screen.getByRole("button", { name: "Start recording" }));
    expect(await screen.findByText(/No microphone was found/)).toBeInTheDocument();
  });

  it("refuses an empty recording and offers no Submit button", async () => {
    const { user, api } = setup(createFakeApi(), { payload: "" });
    await startInterview(user);
    await user.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByText("Recording");
    act(() => void vi.advanceTimersByTime(2000));
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByText(/Nothing was recorded/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit answer" })).not.toBeInTheDocument();
    expect(api.uploadResponse).not.toHaveBeenCalled();
  });

  it("disables recording and explains why when the browser has no MediaRecorder", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    installNoMediaSupport();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App api={createFakeApi()} demoMode={false} />);
    await startInterview(user);
    expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
    expect(screen.getByText("Recording unavailable")).toBeInTheDocument();
  });
});

describe("submitting answers", () => {
  it("uploads the recording with session and question ids, then confirms", async () => {
    const { user, api } = setup();
    await startInterview(user);
    await recordAnswer(user);
    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(await screen.findByText("Answer submitted successfully.")).toBeInTheDocument();
    expect(api.uploadResponse).toHaveBeenCalledTimes(1);
    const input = api.uploadResponse.mock.calls[0][0];
    expect(input.sessionId).toBe("sess-1");
    expect(input.questionId).toBe("q1");
    expect(input.audio.size).toBeGreaterThan(0);
    expect(input.durationSeconds).toBeGreaterThan(1);
    expect(screen.getByText(/This answer has been submitted/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
  });

  it("shows the upload error, keeps the recording, and allows a retry", async () => {
    const api = createFakeApi();
    api.uploadResponse.mockRejectedValueOnce(new ApiError("network", "Cannot reach the server. Check your internet connection and try again."));
    const { user } = setup(api);
    await startInterview(user);
    await recordAnswer(user);
    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(await screen.findByText(/Cannot reach the server/)).toBeInTheDocument();
    expect(screen.getByLabelText("Preview of your recorded answer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry upload" }));
    expect(await screen.findByText("Answer submitted successfully.")).toBeInTheDocument();
    expect(api.uploadResponse).toHaveBeenCalledTimes(2);
  });

  it("shows upload progress and prevents duplicate submissions", async () => {
    let resolveUpload: (value: unknown) => void = () => {};
    const api = createFakeApi();
    api.uploadResponse.mockImplementationOnce(async (input: UploadInput) => {
      input.onProgress?.(0.4);
      await new Promise((resolve) => { resolveUpload = resolve; });
      return { response_id: "r", question_id: input.questionId, transcription_status: "pending", size_bytes: 1, content_type: "audio/webm" };
    });
    const { user } = setup(api);
    await startInterview(user);
    await recordAnswer(user);
    const button = screen.getByRole("button", { name: "Submit answer" });
    fireEvent.click(button);
    fireEvent.click(button); // double tap
    expect(await screen.findByText(/Uploading… 40%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();
    expect(api.uploadResponse).toHaveBeenCalledTimes(1);
    await act(async () => resolveUpload(undefined));
    expect(await screen.findByText("Answer submitted successfully.")).toBeInTheDocument();
    expect(api.uploadResponse).toHaveBeenCalledTimes(1);
  });

  it("treats a 409 as success when the server already has the answer", async () => {
    const api = createFakeApi();
    api.uploadResponse.mockRejectedValueOnce(new ApiError("http", "This question has already been answered.", 409));
    api.getSession.mockResolvedValueOnce(makeSession({ answered_question_ids: ["q1"], status: "in_progress" }));
    const { user } = setup(api);
    await startInterview(user);
    await recordAnswer(user);
    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(await screen.findByText(/already submitted earlier/)).toBeInTheDocument();
  });

  it("keeps the error when a 409 is not about this question", async () => {
    const api = createFakeApi();
    api.uploadResponse.mockRejectedValueOnce(new ApiError("http", "This interview has already been submitted.", 409));
    const { user } = setup(api);
    await startInterview(user);
    await recordAnswer(user);
    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(await screen.findByText("This interview has already been submitted.")).toBeInTheDocument();
  });
});

describe("navigation and finishing", () => {
  it("moves between questions and finishes only when all are answered", async () => {
    const { user, api } = setup();
    await startInterview(user);
    await recordAnswer(user);
    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    await screen.findByText("Answer submitted successfully.");

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/Question 2 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/Describe a time you fixed a difficult bug/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish interview" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText(/Question 1 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/This answer has been submitted/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await recordAnswer(user);
    await user.click(screen.getByRole("button", { name: "Submit answer" }));
    await screen.findByText("Answer submitted successfully.");
    const finish = screen.getByRole("button", { name: "Finish interview" });
    expect(finish).toBeEnabled();
    await user.click(finish);

    expect(await screen.findByRole("heading", { name: "Interview submitted" })).toBeInTheDocument();
    expect(api.completeSession).toHaveBeenCalledWith("sess-1");
    expect(window.sessionStorage.getItem("hireiq.sessionId")).toBeNull();
  });

  it("tells the candidate how many questions are still unanswered", async () => {
    const api = createFakeApi({ startSession: vi.fn(async () => makeSession({ answered_question_ids: ["q1"] })) });
    const { user } = setup(api);
    await startInterview(user, /Question 2 of 2/);
    expect(await screen.findByText(/1 question still unanswered/)).toBeInTheDocument();
  });

  it("shows an error if finishing fails", async () => {
    const api = createFakeApi({
      startSession: vi.fn(async () => makeSession({ answered_question_ids: ["q1", "q2"] })),
      completeSession: vi.fn().mockRejectedValue(new ApiError("http", "The server had a problem. Please try again in a moment.", 500)),
    });
    const { user } = setup(api);
    await startInterview(user, /Question 2 of 2/);
    await user.click(await screen.findByRole("button", { name: "Finish interview" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/server had a problem/)).toBeInTheDocument();
  });
});

describe("resuming after a refresh", () => {
  it("continues at the first unanswered question", async () => {
    window.sessionStorage.setItem("hireiq.sessionId", "sess-1");
    const api = createFakeApi({ getSession: vi.fn(async () => makeSession({ answered_question_ids: ["q1"], status: "in_progress" })) });
    setup(api);
    expect(await screen.findByText(/Question 2 of 2/)).toBeInTheDocument();
    expect(api.getSession).toHaveBeenCalledWith("sess-1");
  });

  it("shows the finished page for an already submitted session", async () => {
    window.sessionStorage.setItem("hireiq.sessionId", "sess-1");
    setup(createFakeApi({ getSession: vi.fn(async () => makeSession({ status: "submitted" })) }));
    expect(await screen.findByRole("heading", { name: "Interview submitted" })).toBeInTheDocument();
  });

  it("falls back to the welcome screen if the saved session no longer exists", async () => {
    window.sessionStorage.setItem("hireiq.sessionId", "gone");
    setup(createFakeApi({ getSession: vi.fn().mockRejectedValue(new ApiError("http", "not found", 404)) }));
    expect(await screen.findByRole("heading", { name: /Welcome to your AI-assisted interview/ })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("hireiq.sessionId")).toBeNull();
  });
});
