"use client";

import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";
import { Amplify } from "aws-amplify";
import Link from "next/link";
import type { ReactNode } from "react";

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_USER_POOL_ID ?? "",
      userPoolClientId: process.env.NEXT_PUBLIC_USER_POOL_CLIENT_ID ?? "",
      loginWith: { email: true },
    },
  },
});

export function Providers({ children }: { children: ReactNode }) {
  return (
    <Authenticator signUpAttributes={["email"]}>
      {({ signOut, user }) => (
        <div className="shell">
          <nav className="nav">
            <strong>Email RAG</strong>
            <Link href="/inbox/">Inbox</Link>
            <Link href="/ask/">Ask</Link>
            <Link href="/actions/">Action items</Link>
            <Link href="/accounts/">Accounts</Link>
            <span className="spacer" />
            <span className="muted">{user?.signInDetails?.loginId}</span>
            <button onClick={signOut}>Sign out</button>
          </nav>
          <main>{children}</main>
        </div>
      )}
    </Authenticator>
  );
}
