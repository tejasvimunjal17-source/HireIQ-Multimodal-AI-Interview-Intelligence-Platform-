import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { makeTranscription } from "../test/helpers";
import type { Transcription } from "../types/interview";
import { TranscriptionPanel } from "./TranscriptionPanel";

function renderPanel(transcription: Transcription | undefined, extra: Partial<Parameters<typeof TranscriptionPanel>[0]> = {}) {
  const props = {
    transcription, pollError: null, timedOut: false, retrying: false, onRetry: vi.fn(), onCheckAgain: vi.fn(), ...extra,
  };
  render(<TranscriptionPanel {...props} />);
  return props;
}

describe("TranscriptionPanel", () => {
  it("shows a queued message before the server has reported anything", () => {
    renderPanel(undefined);
    expect(screen.getByText(/Waiting in the queue/)).toBeInTheDocument();
  });

  it("shows the pending state", () => {
    renderPanel(makeTranscription({ status: "pending" }));
    expect(screen.getByText(/Waiting in the queue/)).toBeInTheDocument();
  });

  it("shows the processing indicator", () => {
    renderPanel(makeTranscription({ status: "processing" }));
    expect(screen.getByText(/Transcribing your answer/)).toBeInTheDocument();
  });

  it("shows the transcript with language and length when completed", () => {
    renderPanel(makeTranscription({
      status: "completed", transcript: "An index is a sorted lookup structure.", language: "english",
      duration_seconds: 75, provider: "openai",
    }));
    expect(screen.getByText("An index is a sorted lookup structure.")).toBeInTheDocument();
    expect(screen.getByText(/Language: english/)).toBeInTheDocument();
    expect(screen.getByText(/Length: 01:15/)).toBeInTheDocument();
    expect(screen.queryByText(/Placeholder text/)).not.toBeInTheDocument();
  });

  it.each(["mock", "demo"])("labels %s transcripts as placeholders, not real recognition", (provider: string) => {
    renderPanel(makeTranscription({ status: "completed", transcript: "[MOCK] text", provider }));
    expect(screen.getByText(/Placeholder text: not real speech recognition/)).toBeInTheDocument();
  });

  it("explains when no speech was detected", () => {
    renderPanel(makeTranscription({ status: "completed", transcript: "", no_speech_detected: true }));
    expect(screen.getByText("No speech detected")).toBeInTheDocument();
    expect(document.querySelector("blockquote")).toBeNull();
  });

  it("shows a failure with a retry button when recovery is possible", async () => {
    const props = renderPanel(makeTranscription({
      status: "failed", error_message: "The transcription service took too long. Please try again.", can_retry: true,
    }));
    expect(screen.getByRole("alert")).toHaveTextContent("took too long");
    await userEvent.click(screen.getByRole("button", { name: "Try transcribing again" }));
    expect(props.onRetry).toHaveBeenCalledWith("resp-q1");
  });

  it("disables the retry button while retrying", () => {
    renderPanel(makeTranscription({ status: "failed", can_retry: true, error_message: "x" }), { retrying: true });
    expect(screen.getByRole("button", { name: "Retrying…" })).toBeDisabled();
  });

  it("reassures the candidate when a failure cannot be retried", () => {
    renderPanel(makeTranscription({ status: "failed", can_retry: false, error_message: "The recording could not be read." }));
    expect(screen.queryByRole("button", { name: /Try transcribing again/ })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Your answer was saved");
  });

  it("mentions a refresh problem only while waiting", () => {
    renderPanel(makeTranscription({ status: "processing" }), { pollError: "Cannot reach the server." });
    expect(screen.getByText(/Could not refresh the status/)).toBeInTheDocument();
  });

  it("offers Check again after polling timed out", async () => {
    const props = renderPanel(makeTranscription({ status: "processing" }), { timedOut: true });
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(props.onCheckAgain).toHaveBeenCalled();
  });
});
