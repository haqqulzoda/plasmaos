import { proxyTenderDocumentDownload } from "@/lib/documentProxy";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyTenderDocumentDownload(id);
}
