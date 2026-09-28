// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Documents } from "./Documents";
import { ToastProvider } from "../components/Toast";
import { api, ApiError } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      listDocuments: vi.fn(),
      uploadDocument: vi.fn(),
    },
  };
});

function renderDocuments() {
  return render(
    <ToastProvider>
      <Documents />
    </ToastProvider>,
  );
}

function makeFile(name: string, contents = "hello", type = "text/plain") {
  return new File([contents], name, { type });
}

function uploadFile(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("Documents upload", () => {
  it("uploads an accepted file via multipart FormData and refreshes the list", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue({ items: [], nextCursor: null });
    vi.mocked(api.uploadDocument).mockResolvedValue({
      id: "doc_1",
      originalFilename: "notes.md",
      byteSize: 5,
      status: "uploaded",
      failureCode: null,
      createdAt: new Date().toISOString(),
    });

    renderDocuments();
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalled());

    uploadFile(makeFile("notes.md", "# hi", "text/markdown"));

    await waitFor(() => expect(api.uploadDocument).toHaveBeenCalledTimes(1));
    expect(api.uploadDocument).toHaveBeenCalledWith(expect.any(File));
    expect(screen.queryByText("Upload failed — please try again")).not.toBeInTheDocument();
  });

  it("rejects an unsupported extension client-side without calling the API", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue({ items: [], nextCursor: null });

    renderDocuments();
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalled());

    uploadFile(makeFile("archive.zip", "binary", "application/zip"));

    expect(await screen.findByText(/isn't supported yet — accepted types: .txt, .md, .pdf/)).toBeInTheDocument();
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it("shows an actionable message when the API rejects the file as unsupported media", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue({ items: [], nextCursor: null });
    vi.mocked(api.uploadDocument).mockRejectedValue(
      new ApiError(415, { error: { code: "unsupported_media_type", message: "nope", requestId: "r1" } }, null),
    );

    renderDocuments();
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalled());

    uploadFile(makeFile("report.pdf", "%PDF-1.7", "application/pdf"));

    expect(
      await screen.findByText(/"report.pdf" isn't supported yet — accepted types: .txt, .md, .pdf/),
    ).toBeInTheDocument();
  });

  it("shows the size-limit message for oversized files without calling the API", async () => {
    vi.mocked(api.listDocuments).mockResolvedValue({ items: [], nextCursor: null });

    renderDocuments();
    await waitFor(() => expect(api.listDocuments).toHaveBeenCalled());

    const big = makeFile("large.txt", "x", "text/plain");
    Object.defineProperty(big, "size", { value: 26 * 1024 * 1024 });
    uploadFile(big);

    expect(await screen.findByText("File exceeds the 25 MB limit")).toBeInTheDocument();
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });
});
