import { AppShell } from "@/components/layout/app-shell";
import { ChatWorkspace } from "@/components/chat/chat-workspace";

export default function ChatPage() {
  return (
    <AppShell activePath="/chat">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Chat</h1>
        <p className="mt-1 text-muted-foreground">
          Study your documents and code projects in depth, or compare them side by side
        </p>
      </div>

      <ChatWorkspace />
    </AppShell>
  );
}
