import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Root from "./Root";

afterEach(() => { window.location.hash = ""; });

describe("Root routing", () => {
  it("shows the candidate interview app at the default address, with no dashboard link", () => {
    render(<Root />);
    expect(screen.queryByText(/dashboard/i)).not.toBeInTheDocument();
  });

  it("shows the manager dashboard at #/dashboard", () => {
    window.location.hash = "#/dashboard";
    render(<Root />);
    expect(screen.getByRole("heading", { name: "Hiring manager dashboard" })).toBeInTheDocument();
  });
});
