import { ArrowLeftRight, Brain, FileUser, Github, Settings, Sparkles } from "lucide-react";
import Link from "next/link";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { UserMenu } from "@/components/layout/user-menu";
import { cn } from "@/lib/utils";

const navItems = [
  { label: "RAG Agent", href: "/rag", icon: Sparkles },
  { label: "GitHub", href: "/github", icon: Github },
  { label: "Resume", href: "/resume", icon: FileUser },
  { label: "Compare Code", href: "/compare", icon: ArrowLeftRight },
];

export function AppHeader({ activePath }: { activePath: string }) {
  const isActive = (href: string) => activePath === href || activePath.startsWith(`${href}/`);

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <Link href="/rag" className="flex shrink-0 items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Brain className="size-4" />
          </div>
          <span className="hidden text-lg font-semibold tracking-tight sm:inline">
            RAG Agent
          </span>
        </Link>

        <nav className="flex min-w-0 items-center gap-1 overflow-x-auto" aria-label="Main">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(item.href) ? "page" : undefined}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive(item.href)
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <item.icon className="size-4" />
              <span className="hidden sm:inline">{item.label}</span>
              <span className="sm:hidden">{item.label.split(" ")[0]}</span>
            </Link>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          <Link
            href="/settings"
            aria-label="Settings"
            title="Settings"
            className={cn(
              "flex size-9 items-center justify-center rounded-lg transition-colors",
              isActive("/settings")
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            <Settings className="size-4" />
          </Link>
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
