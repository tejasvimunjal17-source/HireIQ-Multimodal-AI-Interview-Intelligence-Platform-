/**
 * Transcription status inside the whole app. MOCKED: backend API, microphone, MediaRecorder, timers.
 * (Day 2 flow tests live in App.test.tsx and are unchanged.)
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./services/api";
import { advance, recordAndSubmit, setup, startInterview } from "./test/flow";
import { createFakeApi, makeSession, makeTranscription } from "./test/helpers";

describe("transcription status in the interview", () => {
  it("goes from queued to processing to the finished transcript", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn()
        .mockResolvedValueOnce([]) // the server has not registered the answer yet
        .mockResolvedValueOnce([makeTranscription({ status: "processing" })])
        .mockResolvedValue([makeTranscription({
          status: "completed", transcript: "An index speeds up reads.", language: "english", duration_seconds: 3, provider: "openai",
        })]),
    });
    const { user } = setup(api);
    await startInterview(user);
    await recordAndSubmit(user);

    expect(screen.getByText(/Waiting in the queue/)).toBeInTheDocument(); // upload done, nothing reported yet
    await advance(900);
    expect(screen.getByText(/Waiting in the queue/)).toBeInTheDocument(); // first poll returned nothing yet
    await advance(2100);
    expect(screen.getByText(/Transcribing your answer/)).toBeInTheDocument();
    await advance(3100);
    expect(await screen.findByText("An index speeds up reads.")).toBeInTheDocument();
    expect(screen.getByText(/Language: english/)).toBeInTheDocument();
    expect(screen.queryByText(/Transcribing your answer/)).not.toBeInTheDocument();
  });

  it("uses the session id when asking for the status", async () => {
    const api = createFakeApi();
    const { user } = setup(api);
    await startInterview(user);
    await recordAndSubmit(user);
    await advance(1000);
    expect(api.listTranscriptions).toHaveBeenCalledWith("sess-1");
  });

  it("shows a failure and lets the candidate re-queue it", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn().mockResolvedValue([makeTranscription({
        status: "failed", can_retry: true, error_code: "provider_timeout",
        error_message: "The transcription service took too long. Please try again.",
      })]),
      retryTranscription: vi.fn(async () => makeTranscription({ status: "pending" })),
    });
    const { user } = setup(api);
    await startInterview(user);
    await recordAndSubmit(user);
    await advance(1000);
    expect(await screen.findByText(/took too long/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try transcribing again" }));
    expect(api.retryTranscription).toHaveBeenCalledWith("sess-1", "resp-q1");
    expect(await screen.findByText(/Waiting in the queue/)).toBeInTheDocument();
  });

  it("tells the candidate when no speech was detected", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn().mockResolvedValue([makeTranscription({ status: "completed", transcript: "", no_speech_detected: true })]),
    });
    const { user } = setup(api);
    await startInterview(user);
    await recordAndSubmit(user);
    await advance(1000);
    expect(await screen.findByText("No speech detected")).toBeInTheDocument();
  });

  it("keeps working when the status request fails and recovers on the next poll", async () => {
    const api = createFakeApi({
      listTranscriptions: vi.fn()
        .mockRejectedValueOnce(new ApiError("network", "Cannot reach the server."))
        .mockResolvedValue([makeTranscription({ status: "completed", transcript: "Recovered text." })]),
    });
    const { user } = setup(api);
    await startInterview(user);
    await recordAndSubmit(user);
    await advance(1000);
    expect(await screen.findByText(/Could not refresh the status/)).toBeInTheDocument();
    await advance(2500);
    expect(await screen.findByText("Recovered text.")).toBeInTheDocument();
    expect(screen.queryByText(/Could not refresh the status/)).not.toBeInTheDocument();
  });

  it("does not block moving on: the next question works while transcription is still running", async () => {
    const api = createFakeApi({ listTranscriptions: vi.fn().mockResolvedValue([makeTranscription({ status: "processing" })]) });
    const { user } = setup(api);
    await startInterview(user);
    await recordAndSubmit(user);
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/Question 2 of 2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start recording" })).toBeEnabled();
  });

  it("shows earlier transcripts again after resuming a session", async () => {
    window.sessionStorage.setItem("hireiq.sessionId", "sess-1");
    const api = createFakeApi({
      getSession: vi.fn(async () => makeSession({ answered_question_ids: ["q1"], status: "in_progress" })),
      listTranscriptions: vi.fn().mockResolvedValue([makeTranscription({ status: "completed", transcript: "Saved earlier." })]),
    });
    const { user } = setup(api);
    await screen.findByText(/Question 2 of 2/);
    await advance(1000);
    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Saved earlier.")).toBeInTheDocument();
  });
});
