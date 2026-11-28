"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type EmailBodyProps = {
  html: string | null;
  text: string;
  title: string;
};

const SAFETY_HEAD = `
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: data:; style-src 'unsafe-inline' https:; font-src https: data:; media-src https:; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'">
  <meta name="referrer" content="no-referrer">
  <style>
    html, body { margin: 0; padding: 0; background: #fff; color: #111; }
    body { overflow-wrap: anywhere; }
    img { max-width: 100%; height: auto; }
  </style>
`;

function isolatedEmailDocument(html: string): string {
  const head = html.match(/<head(?:\s[^>]*)?>/i)?.[0];
  if (head) return html.replace(head, `${head}${SAFETY_HEAD}`);

  const root = html.match(/<html(?:\s[^>]*)?>/i)?.[0];
  if (root) return html.replace(root, `${root}<head>${SAFETY_HEAD}</head>`);

  return `<!doctype html><html><head>${SAFETY_HEAD}</head><body>${html}</body></html>`;
}

export function EmailBody({ html, text, title }: EmailBodyProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const resizeObserver = useRef<ResizeObserver | null>(null);
  const [height, setHeight] = useState(480);
  const document = useMemo(() => html ? isolatedEmailDocument(html) : "", [html]);

  useEffect(() => {
    setHeight(480);
    return () => resizeObserver.current?.disconnect();
  }, [html]);

  function fitFrame() {
    resizeObserver.current?.disconnect();
    const emailDocument = frame.current?.contentDocument;
    if (!emailDocument) return;

    const resize = () => {
      const contentHeight = Math.max(
        emailDocument.documentElement.scrollHeight,
        emailDocument.body?.scrollHeight ?? 0,
      );
      setHeight(Math.min(Math.max(contentHeight, 320), 1200));
    };

    resize();
    resizeObserver.current = new ResizeObserver(resize);
    resizeObserver.current.observe(emailDocument.documentElement);
  }

  if (!html) return <p className="email-body-text">{text}</p>;

  return (
    <iframe
      ref={frame}
      className="email-frame"
      srcDoc={document}
      title={title}
      height={height}
      loading="lazy"
      onLoad={fitFrame}
      referrerPolicy="no-referrer"
      sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"
    />
  );
}
