// app/api/proxy/[...path]/route.ts
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  return proxyRequest(req);
}

export async function POST(req: NextRequest) {
  return proxyRequest(req);
}

async function proxyRequest(req: NextRequest) {
  const clientHost = req.headers.get("host")?.split(":")[0] || "localhost";
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/flask/, ""); // strip /flask prefix

  const targetUrl = `http://${clientHost}:8011/api${path}${url.search}`;

  const fetchOptions: RequestInit = {
    method: req.method,
    headers: req.headers,
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    fetchOptions.body = req.body;
    fetchOptions.duplex = "half"; // required for streaming body
  }

  const res = await fetch(targetUrl, fetchOptions);
  const body = await res.arrayBuffer();

  return new NextResponse(body, {
    status: res.status,
    headers: res.headers,
  });
}
