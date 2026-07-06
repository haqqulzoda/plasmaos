import { NextResponse } from "next/server";

import { auth } from "@/app/api/auth/[...nextauth]/route";
import { resolveBackendApiBase } from "@/lib/backendApiBase";

const backendApiBase = resolveBackendApiBase();

function safeErrorDetail(status: number, rawBody: string): string {
  let detail = rawBody.trim();

  if (detail) {
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") {
        detail = parsed.detail;
      }
    } catch {
      // Plain text backend errors are handled below.
    }
  }

  if (!detail) {
    if (status === 401) return "Unauthorized";
    if (status === 403) return "You do not have access to this document.";
    if (status === 404) return "Document file is unavailable. Please re-sync documents for this tender.";
    return "Failed to download document.";
  }

  if (status >= 500) {
    return "Document download failed. Please try again or re-sync documents for this tender.";
  }

  return detail;
}

export async function proxyTenderDocumentDownload(id: string) {
  const session = await auth();
  const accessToken = (session as { accessToken?: string } | null)?.accessToken;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  let backendResponse: Response;

  try {
    backendResponse = await fetch(
      `${backendApiBase}/tenders/documents/${id}/download`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
        cache: "no-store",
      },
    );
  } catch (error) {
    console.error("Document proxy request failed", {
      documentId: id,
      error: error instanceof Error ? error.message : "Unknown error",
    });
    return NextResponse.json(
      { detail: "Document service is unavailable. Please try again later." },
      { status: 502 },
    );
  }

  if (!backendResponse.ok || !backendResponse.body) {
    const rawDetail = await backendResponse.text();
    return NextResponse.json(
      { detail: safeErrorDetail(backendResponse.status, rawDetail) },
      { status: backendResponse.status || 502 },
    );
  }

  const contentType =
    backendResponse.headers.get("Content-Type") ?? "application/octet-stream";
  const contentDisposition =
    backendResponse.headers.get("Content-Disposition") ?? "";

  const responseHeaders: Record<string, string> = {
    "Content-Type": contentType,
  };

  if (contentDisposition) {
    responseHeaders["Content-Disposition"] = contentDisposition;
  }

  const contentLength = backendResponse.headers.get("Content-Length");
  if (contentLength) {
    responseHeaders["Content-Length"] = contentLength;
  }

  return new NextResponse(backendResponse.body, {
    headers: responseHeaders,
  });
}
