import type { ReactNode } from "react";

/**
 * Two-column page with a tall chat on the right. On large screens the header and the side panel share the
 * left column and the chat runs the full height beside them; on a phone it is header, chat, then the panel,
 * so the chat input is on screen as soon as the page opens.
 */
export function ChatWorkspace({ header, chat, side }: { header: ReactNode; chat: ReactNode; side: ReactNode }) {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-12 lg:grid-rows-[auto_1fr] lg:gap-x-6 lg:gap-y-0">
      <div className="min-w-0 lg:col-span-4 lg:col-start-1 lg:row-start-1 lg:pb-4">{header}</div>
      <div className="min-w-0 lg:sticky lg:top-20 lg:col-span-8 lg:col-start-5 lg:row-span-2 lg:row-start-1">{chat}</div>
      <div className="min-w-0 space-y-4 lg:col-span-4 lg:col-start-1 lg:row-start-2">{side}</div>
    </div>
  );
}
