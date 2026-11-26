/** Shared UI-driving helpers for the transcription tests. Browser audio + backend are MOCKED. */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../App";
import { createFakeApi, installFakeMedia } from "./helpers";

export type Api = ReturnType<typeof createFakeApi>;
export type User = ReturnType<typeof userEvent.setup>;

export function setup(api: Api = createFakeApi()) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  installFakeMedia();
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  render(<App api={api} demoMode={false} />);
  return { api, user };
}

export async function startInterview(user: User, firstScreen: RegExp = /Question 1 of 2/) {
  await screen.findByText("Backend Engineer Interview");
  await user.type(screen.getByLabelText("Full name"), "Asha Verma");
  await user.type(screen.getByLabelText("Email address"), "asha@example.com");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Start interview" }));
  await screen.findByText(firstScreen);
}

export async function recordAndSubmit(user: User) {
  await user.click(screen.getByRole("button", { name: "Start recording" }));
  await screen.findByText("Recording");
  act(() => void vi.advanceTimersByTime(2000));
  await user.click(screen.getByRole("button", { name: "Stop" }));
  await screen.findByLabelText("Preview of your recorded answer");
  await user.click(screen.getByRole("button", { name: "Submit answer" }));
  await screen.findByText("Answer submitted successfully.");
}

/** Let the polling timer fire and its promise settle. */
export async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
