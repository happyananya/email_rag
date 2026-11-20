"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/** Google redirects here after consent; we verify `state` and hand the code to the API. */
export default function OAuthCallback() {
  const router = useRouter();
  const [message, setMessage] = useState("Connecting your account…");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const expected = sessionStorage.getItem("oauth_state");
    sessionStorage.removeItem("oauth_state");

    if (params.get("error")) return setMessage(`Google returned an error: ${params.get("error")}`);
    if (!code || !state || state !== expected) return setMessage("Invalid OAuth response (state mismatch).");

    api
      .gmailCallback(code)
      .then(() => router.replace("/accounts/"))
      .catch((e) => setMessage(`Failed to connect: ${e.message}`));
  }, [router]);

  return <p>{message}</p>;
}
