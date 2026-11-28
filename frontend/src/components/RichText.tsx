"use client";

import type { ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type RichTextProps = {
  children: string;
};

export function RichText({ children }: RichTextProps) {
  const markdown = children.replace(/^\s*[•●▪]\s+/gm, "- ");

  return (
    <div className="rich-text">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children: linkText, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer noopener">
              {linkText as ReactNode}
            </a>
          ),
        }}
      >
        {markdown}
      </Markdown>
    </div>
  );
}
