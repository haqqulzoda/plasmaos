import { NextResponse } from "next/server";

import { auth } from "@/app/api/auth/[...nextauth]/route";

const backendApiBase = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"
).replace(/\/$/, "");

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const session = await auth();
  const accessToken = (session as { accessToken?: string } | null)?.accessToken;

  if (!accessToken) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const backendResponse = await fetch(
    `${backendApiBase}/tenders/documents/${id}/download`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
      cache: "no-store",
    },
  );

  if (!backendResponse.ok || !backendResponse.body) {
    const detail = await backendResponse.text();
    return NextResponse.json(
      { detail: detail || "Failed to download document" },
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
